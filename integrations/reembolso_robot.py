# -*- coding: utf-8 -*-
"""Robô visual do submódulo Reembolsos.

Abre o portal e-Reembolso (https://ereembolso.stefanini.com.br) num navegador
controlado (Playwright) visível na máquina do usuário, preenche os campos dos
fluxos "Deslocamento & Estacionamento" (/Reembolso/Deslocamentos.aspx) e
"Almoço com Cliente" (/Reembolso/OutrasDespesas.aspx), e para no botão final
para o usuário revisar e enviar manualmente — o robô nunca envia sozinho.

Diferente do robô do Chamado Jurídico (Microsoft Forms, perguntas numeradas),
este portal é ASP.NET com campos nomeados. Os campos são localizados por
texto do label mais próximo, com fallback documentado quando o seletor não
bate — os seletores exatos (id/name dos combos) foram parcialmente
inspecionados e serão ajustados na primeira execução real junto com o
usuário (ver docs/superpowers/specs/2026-07-14-autotoca-reembolsos-design.md,
seção "Itens a confirmar ao vivo").
"""

import os
import sys
import threading
import uuid
from pathlib import Path

_ROBOT_LOCK = threading.Lock()

LOGIN_TIMEOUT_SECONDS = 300
REVIEW_TIMEOUT_SECONDS = 900
TYPE_DELAY_MS = 30

DESLOCAMENTOS_URL = 'https://ereembolso.stefanini.com.br/Reembolso/Deslocamentos.aspx'
OUTRAS_DESPESAS_URL = 'https://ereembolso.stefanini.com.br/Reembolso/OutrasDespesas.aspx'


class ReembolsoRobotError(Exception):
    pass


def _profile_dir():
    base = (
        Path.home() / 'AppData' / 'Roaming' / 'toca-do-coelho'
        if sys.platform == 'win32'
        else Path.home() / '.toca-do-coelho'
    )
    path = base / 'reembolso-robot-profile'
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def gerar_comprovante_corrompido(target_dir):
    """Gera um arquivo de imagem propositalmente inválido (não é um JPEG real),
    usado como anexo quando o campo de pedágio é exigido pelo site mas o
    usuário não anexou nenhum comprovante próprio."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f'sem-comprovante-{uuid.uuid4().hex[:8]}.jpg'
    path.write_bytes(b'\x00\x00\x00 nao-e-um-jpeg-valido \x00\x00\x00')
    return path


def _detect_default_browser_channel():
    if sys.platform != 'win32':
        return None
    try:
        import winreg
        key_path = r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            prog_id = (winreg.QueryValueEx(key, 'ProgId')[0] or '').lower()
        if 'chrome' in prog_id:
            return 'chrome'
        if 'edge' in prog_id:
            return 'msedge'
    except Exception:
        pass
    return None


def _launch_context(pw, headless):
    profile = _profile_dir()
    args = ['--disable-blink-features=AutomationControlled']
    kwargs = dict(headless=headless, args=args)
    if headless:
        kwargs['viewport'] = {'width': 1280, 'height': 920}
    else:
        kwargs['viewport'] = None
        args.append('--start-maximized')
    last_error = None

    channels = []
    detected = _detect_default_browser_channel()
    if detected:
        channels.append(detected)
    for channel in ('chrome', 'msedge'):
        if channel not in channels:
            channels.append(channel)
    channels.append(None)

    for channel in channels:
        try:
            if channel:
                return pw.chromium.launch_persistent_context(profile, channel=channel, **kwargs)
            return pw.chromium.launch_persistent_context(profile, **kwargs)
        except Exception as e:
            last_error = e
    raise ReembolsoRobotError(f'Não foi possível abrir um navegador (Chrome/Edge). Detalhe: {last_error}')


def _field_container(page, label_text):
    """Encontra o container do campo a partir do texto do label — sobe até o
    ancestral mais próximo que também contenha um input/select/div de combo."""
    label = page.get_by_text(label_text, exact=False).first
    return label.locator(
        'xpath=ancestor::*[.//input or .//select or .//textarea][1]'
    ).first


def fill_text_field(page, label_text, value):
    container = _field_container(page, label_text)
    target = container.locator('input[type="text"], textarea').first
    target.click(timeout=8000)
    target.fill('')
    target.type(str(value), delay=TYPE_DELAY_MS)
    actual = (target.input_value(timeout=4000) or '').strip()
    if actual != str(value).strip():
        raise ReembolsoRobotError(f'campo "{label_text}" não reteve o valor digitado (esperado "{value}", ficou "{actual}")')


def select_native_option(page, label_text, option_text):
    container = _field_container(page, label_text)
    select = container.locator('select').first
    select.select_option(label=option_text, timeout=8000)


def choose_select2_option(page, label_text, option_text):
    """Para combos Select2-like: clica para abrir, digita para filtrar,
    clica na primeira opção visível que contenha o texto."""
    container = _field_container(page, label_text)
    container.locator('.select2-selection, [role="combobox"]').first.click(timeout=8000)
    page.keyboard.type(option_text, delay=TYPE_DELAY_MS)
    page.wait_for_timeout(400)
    option = page.get_by_role('option', name=option_text).first
    if option.count() == 0:
        option = page.get_by_text(option_text, exact=False).first
    option.click(timeout=8000)


def upload_files(page, label_text, file_paths):
    container = _field_container(page, label_text)
    file_input = container.locator('input[type="file"]').first
    file_input.set_input_files(file_paths, timeout=20000)


def _br_date(iso_value):
    from datetime import datetime
    return datetime.strptime(iso_value, '%Y-%m-%d').strftime('%d/%m/%Y')


def _wait_for_login(page, host):
    import time as _time
    deadline = _time.time() + LOGIN_TIMEOUT_SECONDS
    while True:
        if page.is_closed():
            raise ReembolsoRobotError('A janela do robô foi fechada antes do preenchimento.')
        try:
            if host in (page.url or '') and page.locator('label').first.count() > 0:
                return
        except Exception:
            pass
        if _time.time() > deadline:
            raise ReembolsoRobotError('Tempo esgotado aguardando o portal carregar (login pendente?).')
        _time.sleep(1.0)


def _finish_and_wait_submit(page, context, pw, on_progress):
    import time as _time
    on_progress(88, 'Campos preenchidos. Revise e clique em Enviar na janela do robô.')
    submitted = False
    try:
        submit = page.get_by_role('button', name='Enviar').first
        if submit.count() > 0:
            submit.scroll_into_view_if_needed(timeout=8000)
    except Exception:
        pass
    review_deadline = _time.time() + REVIEW_TIMEOUT_SECONDS
    while _time.time() < review_deadline:
        if page.is_closed():
            break
        _time.sleep(1.5)
    # O robô não detecta confirmação de envio automaticamente neste site
    # (sem uma "thank you page" fixa como no Forms) — fica com o usuário
    # fechar a janela após confirmar visualmente que enviou.
    return {'submitted': submitted}


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


def _fill_outros_deslocamentos_common(page, quantidade, periodo_inicio, periodo_fim, valor_total, comprovantes, descricao):
    select_native_option(page, 'QUANTIDADE', str(quantidade).zfill(2))
    container = _field_container(page, 'PERIODO')
    dates = container.locator('input').all()
    if len(dates) >= 2:
        dates[0].fill(_br_date(periodo_inicio))
        dates[1].fill(_br_date(periodo_fim))
    fill_text_field(page, 'VALOR TOTAL EM R$', f'{valor_total:.2f}'.replace('.', ','))
    upload_files(page, 'COMPROVANTE', comprovantes)
    fill_text_field(page, 'DESCRIÇÃO', descricao)


def run_deslocamento_robot(payload, file_paths, on_progress):
    """payload esperado:
      {
        'celula_custo': str, 'descricao_despesa': str,
        'sub_fluxo': 'deslocamento' | 'estacionamento',
        # sub_fluxo == 'deslocamento':
        'origem': str, 'destino': str, 'data_deslocamento': 'YYYY-MM-DD',
        'tipo_transporte': 'Carro da Empresa ou Alugado' | 'Carro Próprio',
        'ida_e_volta': bool, 'conta': str,
        'pedagio_valor_total': float | None,
        # sub_fluxo == 'estacionamento':
        'quantidade': int, 'periodo_inicio': 'YYYY-MM-DD', 'periodo_fim': 'YYYY-MM-DD',
        'valor_total': float, 'descricao_estacionamento': str,
      }
    file_paths: {'data_deslocamento_comprovante': [str], 'pedagio_comprovantes': [str],
                 'estacionamento_comprovantes': [str]}
    on_progress(pct, step) alimenta a barra de progresso.
    Retorna {'submitted': bool}.
    """
    if not _ROBOT_LOCK.acquire(blocking=False):
        raise ReembolsoRobotError('Já existe um robô de Reembolsos em execução. Aguarde ele terminar.')
    try:
        return _run_deslocamento_locked(payload, file_paths, on_progress)
    finally:
        _ROBOT_LOCK.release()


def _run_deslocamento_locked(payload, file_paths, on_progress):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ReembolsoRobotError('Playwright não está instalado neste ambiente (pip install playwright).') from e

    on_progress(8, 'Abrindo o navegador do robô...')
    headless = os.environ.get('TOCA_ROBOT_HEADLESS') == '1'
    pw = sync_playwright().start()
    context = None
    try:
        context = _launch_context(pw, headless)
        page = context.pages[0] if context.pages else context.new_page()

        on_progress(15, 'Carregando o portal e-Reembolso...')
        page.goto(DESLOCAMENTOS_URL, wait_until='domcontentloaded', timeout=60000)
        _wait_for_login(page, 'ereembolso.stefanini.com.br')

        on_progress(30, 'Preenchendo Célula Custo...')
        choose_select2_option(page, 'CÉLULA CUSTO', payload['celula_custo'])
        page.wait_for_timeout(800)  # possível cascata Célula Custo -> Cliente

        on_progress(38, 'Preenchendo Cliente e Serviço...')
        choose_select2_option(page, 'CLIENTE', 'Stefanini - Sao Paulo')
        choose_select2_option(page, 'SERVIÇO', 'Prospecção')
        fill_text_field(page, 'DESCRIÇÃO DA DESPESA', payload['descricao_despesa'])

        if payload['sub_fluxo'] == 'deslocamento':
            on_progress(50, 'Preenchendo Origem e Destino...')
            fill_text_field(page, 'ORIGEM', payload['origem'])
            fill_text_field(page, 'DESTINO', payload['destino'])
            fill_text_field(page, 'DATA DO DESLOCAMENTO', _br_date(payload['data_deslocamento']))
            choose_select2_option(page, 'TIPO DO TRANSPORTE', payload['tipo_transporte'])
            if payload.get('ida_e_volta'):
                page.get_by_text('DESLOCAMENTO IDA E VOLTA', exact=False).first.click(timeout=8000)
            descricao_deslocamento = (
                f"Visita ao cliente {payload['conta']}, de {payload['origem']} à {payload['destino']}"
            )
            fill_text_field(page, 'DESCRIÇÃO DO DESLOCAMENTO', descricao_deslocamento)
            on_progress(65, 'Adicionando deslocamento...')
            page.get_by_role('button', name='adicionar').first.click(timeout=8000)
            page.wait_for_timeout(500)

            pedagio_paths = file_paths.get('pedagio_comprovantes') or []
            if payload.get('pedagio_valor_total'):
                on_progress(75, 'Preenchendo Pedágio...')
                choose_select2_option(page, 'TIPO DO DESLOCAMENTO', 'Pedágio')
                _fill_outros_deslocamentos_common(
                    page, quantidade=len(pedagio_paths) or 1,
                    periodo_inicio=payload['data_deslocamento'], periodo_fim=payload['data_deslocamento'],
                    valor_total=payload['pedagio_valor_total'],
                    comprovantes=pedagio_paths,
                    descricao=f"Deslocamento para visitar cliente {payload['conta']}",
                )
                page.get_by_role('button', name='adicionar').first.click(timeout=8000)
        else:  # estacionamento
            on_progress(55, 'Preenchendo Estacionamento...')
            choose_select2_option(page, 'TIPO DO DESLOCAMENTO', 'Estacionamento')
            _fill_outros_deslocamentos_common(
                page, quantidade=payload['quantidade'],
                periodo_inicio=payload['periodo_inicio'], periodo_fim=payload['periodo_fim'],
                valor_total=payload['valor_total'],
                comprovantes=file_paths.get('estacionamento_comprovantes') or [],
                descricao=payload['descricao_estacionamento'],
            )
            page.get_by_role('button', name='adicionar').first.click(timeout=8000)

        return _finish_and_wait_submit(page, context, pw, on_progress)
    except ReembolsoRobotError:
        _cleanup(pw, context)
        raise
    except Exception as e:
        _cleanup(pw, context)
        raise ReembolsoRobotError(f'Falha no robô de Deslocamento: {e}') from e
