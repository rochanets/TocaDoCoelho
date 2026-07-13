# -*- coding: utf-8 -*-
"""Robô visual do Chamado Jurídico.

Abre o Microsoft Forms num navegador controlado (Playwright) visível na
máquina do usuário, preenche as 22 perguntas do formulário (texto, escolha
única, data e upload de arquivo) com um cursor animado (coelhinho 🐇) e para
no botão Enviar para o usuário revisar e concluir. A submissão é uma
resposta genuína do Forms, feita na sessão Microsoft do próprio usuário —
nenhuma pergunta é respondida além das mapeadas (o item 21, por decisão de
negócio, nunca recebe um campo e portanto nunca é tocado).

O login Microsoft é feito uma única vez: o perfil do navegador é
persistido em disco e reutilizado nas execuções seguintes.

Cada campo é localizado prioritariamente pelo texto normalizado da
pergunta (resiliente a reordenação do formulário); quando nenhum termo
bate com nada na página, cai para a posição numérica (`q`) informada pelo
chamador — esse caso é reportado separadamente para o usuário conferir
visualmente, já que uma resposta jurídica na pergunta errada é pior do que
uma pergunta deixada em branco.
"""

import os
import re
import sys
import time
import threading
import unicodedata
import urllib.parse
from datetime import datetime
from pathlib import Path

# Uma execução por vez: o perfil persistente do navegador não pode ser
# compartilhado entre duas janelas simultâneas.
_ROBOT_LOCK = threading.Lock()

# Referências do navegador deixado aberto para revisão do usuário na
# execução anterior — fechadas no início da execução seguinte.
_leftover = {'playwright': None, 'context': None}
_leftover_lock = threading.Lock()

LOGIN_TIMEOUT_SECONDS = 300       # espera máxima pelo login Microsoft
REVIEW_TIMEOUT_SECONDS = 900      # espera máxima pela revisão + envio manual
TYPE_DELAY_MS = 30                # digitação caractere a caractere
CALENDAR_MAX_MONTH_CLICKS = 36    # até 3 anos de navegação no calendário

QUESTION_SELECTOR = '[data-automation-id="questionItem"], div[role="listitem"]'
TEXT_INPUT_SELECTOR = (
    'input[data-automation-id="textInput"], textarea[data-automation-id="textInput"], '
    'input[type="text"], textarea, input:not([type])'
)
RADIO_OPTION_SELECTOR = '[role="radio"], input[type="radio"]'
FILE_INPUT_SELECTOR = 'input[type="file"]'
CALENDAR_BUTTON_SELECTOR = (
    'button[aria-label*="alend" i], button[data-icon-name="Calendar"], '
    'button[aria-label*="data" i]'
)
DATEPICKER_HEADER_SELECTOR = '.ms-DatePicker-monthAndYear, [class*="monthAndYear"]'
DATEPICKER_NEXT_SELECTOR = (
    'button[aria-label*="róxim" i], button[aria-label*="next" i], '
    '[data-automation-id="DatePickerNextMonthNavButton"]'
)
DATEPICKER_PREV_SELECTOR = (
    'button[aria-label*="nterior" i], button[aria-label*="prev" i], '
    '[data-automation-id="DatePickerPrevMonthNavButton"]'
)
DATEPICKER_DAY_SELECTOR = '.ms-DatePicker-day:not(.ms-DatePicker-day--outfocus)'
SUBMIT_SELECTOR = 'button[data-automation-id="submitButton"]'
THANK_YOU_SELECTOR = '[data-automation-id="thankYouPageMessage"]'

_PT_MONTHS = [
    'janeiro', 'fevereiro', 'marco', 'abril', 'maio', 'junho',
    'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro',
]
_EN_MONTHS = [
    'january', 'february', 'march', 'april', 'may', 'june',
    'july', 'august', 'september', 'october', 'november', 'december',
]


class FormsRobotError(Exception):
    pass


def _normalize(value):
    text = unicodedata.normalize('NFD', str(value or ''))
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()


def _profile_dir():
    base = (
        Path.home() / 'AppData' / 'Roaming' / 'toca-do-coelho'
        if sys.platform == 'win32'
        else Path.home() / '.toca-do-coelho'
    )
    path = base / 'forms-robot-profile'
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _close_leftover():
    with _leftover_lock:
        ctx, pw = _leftover.get('context'), _leftover.get('playwright')
        _leftover['context'] = None
        _leftover['playwright'] = None
    for obj, method in ((ctx, 'close'), (pw, 'stop')):
        if obj is not None:
            try:
                getattr(obj, method)()
            except Exception:
                pass


def _store_leftover(pw, ctx):
    with _leftover_lock:
        _leftover['playwright'] = pw
        _leftover['context'] = ctx


def _launch_context(pw, headless):
    """Abre o navegador com perfil persistente. Prefere Edge/Chrome já
    instalados na máquina (não exige `playwright install`)."""
    profile = _profile_dir()
    kwargs = dict(
        headless=headless,
        viewport={'width': 1280, 'height': 920},
        args=['--disable-blink-features=AutomationControlled'],
    )
    last_error = None
    custom_path = (os.environ.get('TOCA_ROBOT_BROWSER_PATH') or '').strip()
    if custom_path:
        try:
            return pw.chromium.launch_persistent_context(profile, executable_path=custom_path, **kwargs)
        except Exception as e:
            last_error = e
    for channel in ['msedge', 'chrome', None]:
        try:
            if channel:
                return pw.chromium.launch_persistent_context(profile, channel=channel, **kwargs)
            return pw.chromium.launch_persistent_context(profile, **kwargs)
        except Exception as e:
            last_error = e
    raise FormsRobotError(
        f'Não foi possível abrir um navegador (Edge/Chrome). Detalhe: {last_error}'
    )


_CURSOR_JS = """
() => {
    if (document.getElementById('__tocaRobotCursor')) return;
    const cursor = document.createElement('div');
    cursor.id = '__tocaRobotCursor';
    cursor.textContent = '🐇';
    cursor.style.cssText = [
        'position:fixed', 'left:40px', 'top:40px', 'z-index:2147483647',
        'font-size:30px', 'pointer-events:none',
        'filter:drop-shadow(0 3px 6px rgba(0,0,0,.35))',
        'transition:left .65s cubic-bezier(.45,.05,.35,1), top .65s cubic-bezier(.45,.05,.35,1)',
    ].join(';');
    document.body.appendChild(cursor);
    const badge = document.createElement('div');
    badge.id = '__tocaRobotBadge';
    badge.textContent = 'Robô do Toca preenchendo — revise antes de enviar';
    badge.style.cssText = [
        'position:fixed', 'left:50%', 'bottom:18px', 'transform:translateX(-50%)',
        'z-index:2147483647', 'background:#065f46', 'color:#fff',
        'padding:8px 18px', 'border-radius:99px', 'font-size:13px',
        'font-family:Segoe UI,sans-serif', 'box-shadow:0 4px 14px rgba(0,0,0,.25)',
        'pointer-events:none',
    ].join(';');
    document.body.appendChild(badge);
    window.__tocaRobotMove = (x, y) => {
        cursor.style.left = (x - 8) + 'px';
        cursor.style.top = (y - 26) + 'px';
    };
    window.__tocaRobotBadge = (text) => { badge.textContent = text; };
}
"""

_HIGHLIGHT_JS = """
(el) => {
    el.style.outline = '3px solid #10b981';
    el.style.outlineOffset = '2px';
    el.style.transition = 'outline-color .3s';
    setTimeout(() => { el.style.outlineColor = 'transparent'; }, 1600);
}
"""

_PULSE_SUBMIT_JS = """
(el) => {
    if (!document.getElementById('__tocaRobotPulse')) {
        const style = document.createElement('style');
        style.id = '__tocaRobotPulse';
        style.textContent = '@keyframes tocaRobotPulse {0%,100%{box-shadow:0 0 0 0 rgba(16,185,129,.7)} 50%{box-shadow:0 0 0 12px rgba(16,185,129,0)}}';
        document.head.appendChild(style);
    }
    el.style.animation = 'tocaRobotPulse 1.2s ease-in-out infinite';
}
"""

# Casa cada campo com a pergunta do Forms pelo texto normalizado (sem
# acentos). Cada pergunta só é usada uma vez; a ordem dos campos importa —
# os termos mais específicos devem vir primeiro.
_MATCH_JS = """
(args) => {
    const { questionSelector, fields } = args;
    const normalize = (v) => String(v || '')
        .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')
        .toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
    const questions = Array.from(document.querySelectorAll(questionSelector));
    const texts = questions.map(q => normalize(q.innerText || ''));
    const used = new Set();
    const mapping = {};
    for (const field of fields) {
        const terms = (field.terms || []).map(normalize);
        const idx = texts.findIndex((t, i) => !used.has(i) && terms.some(term => term && t.includes(term)));
        if (idx >= 0) { used.add(idx); mapping[field.key] = idx; }
    }
    return { mapping, total: questions.length };
}
"""


def _move_cursor_to(page, x, y):
    try:
        page.evaluate('([x, y]) => window.__tocaRobotMove && window.__tocaRobotMove(x, y)', [x, y])
    except Exception:
        pass


def _set_badge(page, text):
    try:
        page.evaluate('(t) => window.__tocaRobotBadge && window.__tocaRobotBadge(t)', text)
    except Exception:
        pass


def _highlight_and_point(page, question, target=None):
    try:
        box = (target or question).bounding_box()
        if box:
            _move_cursor_to(page, box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            time.sleep(0.6)
    except Exception:
        pass
    try:
        question.evaluate(_HIGHLIGHT_JS)
    except Exception:
        pass


def _fill_text(page, question, value):
    target = question.locator(TEXT_INPUT_SELECTOR).first
    target.scroll_into_view_if_needed(timeout=8000)
    _highlight_and_point(page, question, target)
    target.click(timeout=8000)
    target.fill('')
    target.type(str(value), delay=TYPE_DELAY_MS)


def _select_radio_option(page, question, option_terms):
    options = question.locator(RADIO_OPTION_SELECTOR)
    count = options.count()
    normalized_terms = [_normalize(t) for t in option_terms]
    for i in range(count):
        option = options.nth(i)
        try:
            label_text = option.evaluate("""
                (el) => {
                    const aria = el.getAttribute('aria-label') || '';
                    const labelledBy = el.getAttribute('aria-labelledby');
                    const byId = labelledBy
                        ? labelledBy.split(' ').map(id => document.getElementById(id)?.innerText || '').join(' ')
                        : '';
                    const closestLabel = el.closest('label')?.innerText || '';
                    const parentText = el.parentElement?.innerText || '';
                    return [aria, byId, closestLabel, parentText].join(' | ');
                }
            """)
        except Exception:
            continue
        norm = _normalize(label_text)
        if any(term and term in norm for term in normalized_terms):
            _highlight_and_point(page, question, option)
            option.click(timeout=8000, force=True)
            return True
    return False


def _parse_calendar_header(text):
    norm = _normalize(text)
    year_match = re.search(r'(20\d{2})', norm)
    year = int(year_match.group(1)) if year_match else None
    month = None
    for months in (_PT_MONTHS, _EN_MONTHS):
        for i, name in enumerate(months):
            if name in norm:
                month = i + 1
                break
        if month:
            break
    return month, year


def _fill_date(page, question, iso_value):
    target_date = datetime.strptime(iso_value, '%Y-%m-%d').date()
    calendar_btn = question.locator(CALENDAR_BUTTON_SELECTOR).first
    calendar_btn.scroll_into_view_if_needed(timeout=8000)
    _highlight_and_point(page, question, calendar_btn)
    calendar_btn.click(timeout=8000)
    page.wait_for_timeout(400)

    header = page.locator(DATEPICKER_HEADER_SELECTOR).first
    for _ in range(CALENDAR_MAX_MONTH_CLICKS):
        header_text = header.inner_text(timeout=4000)
        month, year = _parse_calendar_header(header_text)
        if month == target_date.month and year == target_date.year:
            break
        if month is None or year is None:
            raise FormsRobotError('não foi possível ler o mês/ano exibido no calendário do Forms')
        target_ord = target_date.year * 12 + target_date.month
        current_ord = year * 12 + month
        nav_selector = DATEPICKER_NEXT_SELECTOR if target_ord > current_ord else DATEPICKER_PREV_SELECTOR
        page.locator(nav_selector).first.click(timeout=4000)
        page.wait_for_timeout(250)
    else:
        raise FormsRobotError('não cheguei ao mês/ano esperado no calendário do Forms')

    day_str = str(target_date.day)
    days = page.locator(DATEPICKER_DAY_SELECTOR)
    for i in range(days.count()):
        day_el = days.nth(i)
        if (day_el.inner_text(timeout=2000) or '').strip() == day_str:
            day_el.click(timeout=4000)
            return
    raise FormsRobotError(f'não localizei o dia {day_str} no calendário do Forms')


def _fill_file(question, file_paths):
    target = question.locator(FILE_INPUT_SELECTOR).first
    target.set_input_files(file_paths, timeout=20000)


def _is_form_ready(page, forms_host):
    """Pronto quando a página voltou ao host do Forms (pós-login) e as
    perguntas estão renderizadas."""
    try:
        if forms_host and forms_host not in (page.url or ''):
            return False
        return page.locator(QUESTION_SELECTOR).count() > 0
    except Exception:
        return False


def run_chamado_juridico_robot(forms_url, fields, on_progress):
    """Executa o robô. `fields` é uma lista ordenada de dicts:
      {'key', 'label', 'terms', 'q' (posição 1-based no formulário),
       'type': 'text'|'radio'|'radio_yes_no'|'date'|'file',
       'value': str (text/date/radio_yes_no),
       'option_terms': [str] (radio),
       'file_paths': [str] (file)}
    `on_progress(pct, step)` alimenta a barra de progresso.

    Retorna {'submitted', 'filled', 'unmatched', 'errors', 'positional', 'questions_found'}.
    """
    if not _ROBOT_LOCK.acquire(blocking=False):
        raise FormsRobotError('Já existe um robô em execução. Aguarde ele terminar.')
    try:
        return _run_locked(forms_url, fields, on_progress)
    finally:
        _ROBOT_LOCK.release()


def _is_fillable(field):
    ftype = field.get('type')
    if ftype in ('text', 'date'):
        return bool((field.get('value') or '').strip())
    if ftype == 'file':
        return bool(field.get('file_paths'))
    if ftype in ('radio', 'radio_yes_no'):
        return True
    return False


def _run_locked(forms_url, fields, on_progress):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise FormsRobotError(
            'Playwright não está instalado neste ambiente (pip install playwright).'
        ) from e

    _close_leftover()
    on_progress(8, 'Abrindo o navegador do robô...')
    headless = os.environ.get('TOCA_ROBOT_HEADLESS') == '1'

    pw = sync_playwright().start()
    context = None
    try:
        context = _launch_context(pw, headless)
        page = context.pages[0] if context.pages else context.new_page()

        on_progress(15, 'Carregando o Microsoft Forms...')
        page.goto(forms_url, wait_until='domcontentloaded', timeout=60000)

        forms_host = urllib.parse.urlparse(forms_url).netloc
        deadline = time.time() + LOGIN_TIMEOUT_SECONDS
        notified_login = False
        while not _is_form_ready(page, forms_host):
            if page.is_closed():
                raise FormsRobotError('A janela do robô foi fechada antes do preenchimento.')
            if time.time() > deadline:
                raise FormsRobotError(
                    'Tempo esgotado aguardando o formulário carregar. '
                    'Se o Forms pediu login, conclua-o e execute o robô novamente.'
                )
            if not notified_login and forms_host not in (page.url or ''):
                notified_login = True
                on_progress(20, 'Aguardando seu login Microsoft na janela do robô...')
            time.sleep(1.0)

        on_progress(35, 'Formulário carregado. Iniciando preenchimento...')
        page.evaluate(_CURSOR_JS)

        match = page.evaluate(_MATCH_JS, {
            'questionSelector': QUESTION_SELECTOR,
            'fields': [{'key': f['key'], 'terms': f.get('terms') or []} for f in fields],
        })
        mapping = match.get('mapping') or {}
        total_questions = int(match.get('total') or 0)

        filled, unmatched, errors, positional = [], [], [], []
        fillable = [f for f in fields if _is_fillable(f)]
        step_span = 50.0 / max(len(fillable), 1)
        progress = 35.0

        for field in fillable:
            progress += step_span
            label = field.get('label') or field['key']
            idx = mapping.get(field['key'])
            used_position = False
            if idx is None and field.get('q'):
                fallback_idx = int(field['q']) - 1
                if 0 <= fallback_idx < total_questions:
                    idx = fallback_idx
                    used_position = True
            if idx is None:
                unmatched.append(label)
                continue

            on_progress(int(progress), f'Preenchendo "{label}"...')
            try:
                question = page.locator(QUESTION_SELECTOR).nth(idx)
                ftype = field['type']
                if ftype == 'text':
                    _fill_text(page, question, field['value'])
                elif ftype == 'date':
                    question.scroll_into_view_if_needed(timeout=8000)
                    _fill_date(page, question, field['value'])
                elif ftype == 'file':
                    question.scroll_into_view_if_needed(timeout=8000)
                    _highlight_and_point(page, question)
                    _fill_file(question, field['file_paths'])
                elif ftype == 'radio':
                    question.scroll_into_view_if_needed(timeout=8000)
                    if not _select_radio_option(page, question, field['option_terms']):
                        raise FormsRobotError('opção não encontrada entre as escolhas do formulário')
                elif ftype == 'radio_yes_no':
                    question.scroll_into_view_if_needed(timeout=8000)
                    terms = ['sim'] if field['value'] == 'Sim' else ['nao']
                    if not _select_radio_option(page, question, terms):
                        raise FormsRobotError('opção Sim/Não não encontrada no formulário')
                filled.append(label)
                if used_position:
                    positional.append(label)
            except Exception as e:
                unmatched.append(label)
                errors.append(f'{label}: {e}')

        # Leva o coelhinho até o botão Enviar e deixa a decisão com o usuário.
        submitted = False
        on_progress(88, 'Campos preenchidos. Revise, anexe arquivos e clique em Enviar na janela do robô.')
        try:
            submit = page.locator(SUBMIT_SELECTOR).first
            submit.scroll_into_view_if_needed(timeout=8000)
            box = submit.bounding_box()
            if box:
                _move_cursor_to(page, box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            submit.evaluate(_PULSE_SUBMIT_JS)
        except Exception:
            pass
        _set_badge(page, 'Revise os campos, anexe os arquivos e clique em Enviar')

        review_deadline = time.time() + REVIEW_TIMEOUT_SECONDS
        while time.time() < review_deadline:
            if page.is_closed():
                break
            try:
                if page.locator(THANK_YOU_SELECTOR).first.is_visible():
                    submitted = True
                    break
            except Exception:
                if page.is_closed():
                    break
            time.sleep(1.5)

        if submitted:
            on_progress(97, 'Envio confirmado pelo Microsoft Forms!')
            time.sleep(2.5)
            try:
                context.close()
            except Exception:
                pass
            try:
                pw.stop()
            except Exception:
                pass
        else:
            # Janela fica aberta para o usuário concluir no seu tempo;
            # será fechada automaticamente na próxima execução do robô.
            _store_leftover(pw, context)

        return {
            'submitted': submitted,
            'filled': filled,
            'unmatched': unmatched,
            'errors': errors,
            'positional': positional,
            'questions_found': total_questions,
        }
    except FormsRobotError:
        _cleanup(pw, context)
        raise
    except Exception as e:
        _cleanup(pw, context)
        raise FormsRobotError(f'Falha no robô de preenchimento: {e}') from e


def _cleanup(pw, context):
    try:
        if context is not None:
            context.close()
    except Exception:
        pass
    try:
        pw.stop()
    except Exception:
        pass
