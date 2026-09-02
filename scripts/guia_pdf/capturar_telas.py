# -*- coding: utf-8 -*-
"""Captura as telas do Toca do Coelho com efeito spotlight para o guia em PDF.

Roda contra a instância ISOLADA (porta 3111, TOCA_DB_PATH no scratchpad).
Nunca abre o banco de produção.
"""
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = 'http://localhost:3111'
OUT = Path(__file__).resolve().parent / 'shots'
OUT.mkdir(exist_ok=True)

PROBE_ONLY = '--probe' in sys.argv

HELPERS = r"""
'use strict';
window.__clear = function () {
  document.querySelectorAll('.__spotlight').forEach(e => e.remove());
};
window.__draw = function (rect, pad, radius) {
  var p = (pad == null ? 10 : pad), rad = (radius == null ? 12 : radius);
  var d = document.createElement('div');
  d.className = '__spotlight';
  d.style.cssText = 'position:fixed;left:' + (rect.left - p) + 'px;top:' + (rect.top - p) +
    'px;width:' + (rect.width + 2 * p) + 'px;height:' + (rect.height + 2 * p) +
    'px;border-radius:' + rad + 'px;box-shadow:0 0 0 99999px rgba(6,14,11,.55),' +
    '0 0 0 2.5px #34d399, 0 0 26px 7px rgba(52,211,153,.38);pointer-events:none;' +
    'z-index:2147483647;';
  document.body.appendChild(d);
  return { w: Math.round(rect.width), h: Math.round(rect.height), top: Math.round(rect.top) };
};
window.__union = function (els) {
  var l = 1e9, t = 1e9, r = -1e9, b = -1e9;
  els.forEach(function (el) {
    var k = el.getBoundingClientRect();
    l = Math.min(l, k.left); t = Math.min(t, k.top);
    r = Math.max(r, k.right); b = Math.max(b, k.bottom);
  });
  return { left: l, top: t, width: r - l, height: b - t };
};

/* rola o ancestral scrollável para que o retângulo fique no centro da viewport */
window.__center = function (el, rect) {
  var want = (window.innerHeight / 2) - (rect.height / 2);
  var dy = rect.top - want;
  if (Math.abs(dy) < 4) return;
  var node = el.parentElement;
  while (node && node !== document.body) {
    var st = getComputedStyle(node);
    if (/(auto|scroll|overlay)/.test(st.overflowY) && node.scrollHeight > node.clientHeight + 2) {
      node.scrollBy(0, dy);
      return;
    }
    node = node.parentElement;
  }
  window.scrollBy(0, dy);
};
/* alvo por seletor simples */
window.__spot = function (sel, pad, radius) {
  window.__clear();
  var el = document.querySelector(sel);
  if (!el) return 'NOT_FOUND:' + sel;
  el.scrollIntoView({ block: 'center', inline: 'center' });
  window.__center(el, el.getBoundingClientRect());
  return window.__draw(el.getBoundingClientRect(), pad, radius);
};
/* alvo = ancestral (ex.: o cartão que contém o campo) */
window.__spotUp = function (sel, upSel, pad, radius) {
  window.__clear();
  var i = document.querySelector(sel);
  var el = i && i.closest(upSel);
  if (!el) return 'NOT_FOUND:' + sel + ' -> ' + upSel;
  el.scrollIntoView({ block: 'center', inline: 'center' });
  window.__center(el, el.getBoundingClientRect());
  return window.__draw(el.getBoundingClientRect(), pad, radius);
};
/* alvo = união de vários seletores */
window.__spotUnion = function (sels, pad, radius) {
  window.__clear();
  var els = sels.map(function (s) { return document.querySelector(s); });
  if (els.some(function (e) { return !e; })) return 'NOT_FOUND:' + JSON.stringify(sels);
  els[0].scrollIntoView({ block: 'center', inline: 'center' });
  window.__center(els[0], window.__union(els));
  return window.__draw(window.__union(els), pad, radius);
};

/* abre o cartão do acordeão de Configurações (todos iniciam fechados) */
window.__openCard = function (text) {
  var t = text.toLowerCase();
  var card = Array.from(document.querySelectorAll('#configuracoes section.settings-card'))
    .find(function (s) {
      var h = s.querySelector('h3');
      return h && h.textContent.toLowerCase().indexOf(t) !== -1;
    });
  if (!card) return 'NO_CARD:' + text;
  var title = card.querySelector('h3');
  if (card.classList.contains('settings-collapsed')) title.click();
  return card.classList.contains('settings-collapsed') ? 'AINDA_FECHADO' : 'aberto';
};

/* alvo = união dos ancestrais (inclui o <label> de cada campo no destaque) */
window.__spotUnionUp = function (sels, upSel, pad, radius) {
  window.__clear();
  var els = sels.map(function (s) {
    var i = document.querySelector(s);
    return i && i.closest(upSel);
  });
  if (els.some(function (e) { return !e; })) return 'NOT_FOUND_UP:' + JSON.stringify(sels);
  els[0].scrollIntoView({ block: 'center', inline: 'center' });
  window.__center(els[0], window.__union(els));
  return window.__draw(window.__union(els), pad, radius);
};
/* alvo = cartão de Configurações cujo título contém o texto */
window.__spotCard = function (text, pad, radius) {
  window.__clear();
  var t = text.toLowerCase();
  var card = Array.from(document.querySelectorAll('#configuracoes section.settings-card'))
    .find(function (s) {
      var h = s.querySelector('h3');
      return h && h.textContent.toLowerCase().indexOf(t) !== -1;
    });
  if (!card) return 'NOT_FOUND_CARD:' + text;
  card.scrollIntoView({ block: 'center', inline: 'center' });
  window.__center(card, card.getBoundingClientRect());
  return window.__draw(card.getBoundingClientRect(), pad, radius);
};
"""

# ---------------------------------------------------------------------------
# Roteiro de capturas. `js` prepara a tela; `spot` define o destaque.
# ---------------------------------------------------------------------------

SHOTS = [
    dict(n=2,  slug='02-onde-fica-configuracoes', tab='home',
         spot=('__spot', ['#topbarSettingsButton', 10, 999]),
         legenda='A engrenagem no topo direito abre as Configurações. Na primeira '
                 'abertura o app leva você para cá automaticamente.'),

    dict(n=3,  slug='03-cadastro-usuario', tab='configuracoes', card='Cadastro do Usu',
         spot=('__spotUp', ['#userProfileForm', 'section.settings-card', 12, 16]),
         legenda='Nome completo, apelido, cargo, e-mail, telefone e foto são todos '
                 'obrigatórios — faltando um, o formulário recusa o salvamento.'),

    dict(n=4,  slug='04-chave-sai', tab='configuracoes', card='Integra',
         spot=('__spotUnionUp', [['#itocaSaiApiKey', '#itocaSaiBaseUrl'], '.form-group', 12, 14]),
         legenda='O SAI é o motor principal de IA. Template ID e Base URL já vêm com '
                 'o valor padrão — normalmente só a API Key precisa ser colada.'),

    dict(n=4,  slug='04b-chave-openrouter', tab='configuracoes', card='Integra',
         spot=('__spotUnionUp', [['#openrouterApiKey', '#openrouterModel'], '.form-group', 12, 14]),
         legenda='O OpenRouter é o fallback. A chave é validada no momento de salvar: '
                 'se estiver errada, o app avisa em vez de aceitar em silêncio. Sem '
                 'SAI nem OpenRouter, todo botão marcado com ✦ para de responder.'),

    dict(n=5,  slug='05-tavily', tab='configuracoes', card='Integra',
         spot=('__spotUp', ['#tavilyApiKey', '.form-group', 10, 12]),
         legenda='A chave da Tavily habilita Account Planning, AutoMapping e os '
                 'insights de campanha — e só eles.'),

    dict(n=6,  slug='06-microsoft-365', tab='configuracoes', card='Integra',
         spot=('__spotUp', ['#connMicrosoftStatus', 'div[style*="border"]', 10, 14]),
         legenda='Tenant e Client ID já vêm preenchidos no build: é só clicar em '
                 'Conexão Microsoft 365 e autorizar na janela da Microsoft.'),

    dict(n=7,  slug='07-whatsapp', tab='configuracoes', card='Integra',
         spot=('__spotUp', ['#connWhatsappStatus', 'div[style*="border"]', 10, 14]),
         legenda='Sincronizar WhatsApp abre o QR code. O servidor WAHA-lite já vem '
                 'embutido no app — não há nada para instalar.'),

    dict(n=7,  slug='07b-verificar-conexoes', tab='configuracoes', card='Integra',
         spot=('__spotUp', ['#waStartupCheckToggle', 'label', 10, 10]),
         legenda='Marque esta opção: o app passa a avisar quando o WhatsApp cair ou '
                 'uma chave expirar, em vez de você descobrir na hora do disparo.'),

    dict(n=8,  slug='08-extensao-automacoes', tab='autotoca',
         spot=('__spotUnion', [['#reportsBtn_preparar-reuniao',
                                '#autoTocaBtn_reembolsos'], 12, 14]),
         legenda='Estas automações dependem da extensão do Chrome. Carregue-a uma '
                 'única vez em chrome://extensions › Modo do desenvolvedor › '
                 'Carregar sem compactação, apontando para a pasta '
                 '%AppData%\\toca-do-coelho\\extension.'),

    dict(n=9,  slug='09-iniciar-com-windows', tab='configuracoes', card='Sistema',
         spot=('__spot', ['#startupSettingsCard', 12, 16]),
         legenda='Envios agendados e o verificador de respostas só rodam com o app '
                 'aberto — por isso vale deixar o Toca subir com o Windows.'),

    dict(n=9,  slug='09b-atualizacoes', tab='configuracoes', card='Ajuda e Atualiza',
         spot=('__spotCard', ['Ajuda e Atualiza', 12, 16]),
         legenda='Owner e repositório já apontam para o repositório oficial. O token '
                 'do GitHub é opcional: serve só para não bater no limite de consultas.'),

    dict(n=10, slug='10-novo-contato', tab='clientes',
         spot=('__spotUp', ['button[onclick*="openClientModal"]', '.section-title', 12, 14]),
         legenda='Comece pelos contatos, não pelas contas. Para carga inicial em '
                 'volume, use Importar Excel.'),

    dict(n=10, slug='10b-contato-empresa', tab='clientes', open_modal='client',
         spot=('__spotUp', ['#clientCompanySelect', '.form-group', 10, 12]),
         legenda='O campo Empresa é a espinha da estrutura: cada empresa nova '
                 'digitada aqui cria automaticamente a Conta correspondente.'),

    dict(n=10, slug='10c-contato-target-frio', tab='clientes', open_modal='client',
         spot=('__spotUnionUp', [['#clientColdContact', '#clientIsTarget'], '.form-group', 10, 12]),
         legenda='Contato Frio e Cliente TARGET trocam a régua de status daquele '
                 'contato: target cobra contato mais frequente; frio, muito menos.'),

    dict(n=11, slug='11-nova-conta', tab='gestao-conta',
         spot=('__spot', ['button[onclick="openAccountModal()"]', 12, 12]),
         legenda='As contas criadas a partir dos contatos nascem só com o nome. '
                 'Abra cada uma para completar o cadastro.'),

    dict(n=11, slug='11b-conta-autofill', tab='gestao-conta', open_modal='account',
         spot=('__spot', ['#accountAutoFillBtn', 10, 10]),
         legenda='O ✦ AutoFill busca razão social, CNPJ, setor e logo na web e '
                 'preenche para você revisar antes de salvar.'),

    dict(n=11, slug='11c-ponto-focal', tab='gestao-conta', open_modal='account',
         spot=('__spotUp', ['#accountMainContactsHidden', '.form-group', 10, 12]),
         legenda='O Ponto Focal Principal só lista contatos que já existem — é por '
                 'isso que os contatos vêm antes das contas.'),

    dict(n=12, slug='12-servico-stefanini', tab='gestao-conta', open_modal='account',
         spot=('__spot', ['button[onclick^="openPresenceModal"]', 10, 12]),
         legenda='Cada entrega ativa na conta é um serviço. É o que soma o Total '
                 'Mensal e o que o Whitespace cruza com o portfólio.'),

    dict(n=13, slug='13-nova-oferta', tab='portfolio',
         spot=('__spot', ['button[onclick*="openNewOfferModal"]', 10, 12]),
         legenda='Sem ofertas cadastradas aqui, a aba Whitespace do Portifólio fica '
                 'vazia — ela é o cruzamento ofertas × serviços.'),

    dict(n=14, slug='14-agrupamento-cargos', tab='configuracoes', card='Agrupamento de Cargos',
         spot=('__spotCard', ['Agrupamento de Cargos', 12, 16]),
         legenda='Sem agrupamentos, o Mapeamento Organizacional cria uma coluna por '
                 'cargo literal digitado e vira uma tabela ilegível.'),

    dict(n=15, slug='15-faixa-status', tab='configuracoes', card='Faixa de Status',
         spot=('__spotCard', ['Faixa de Status', 12, 16]),
         legenda='Já vem com padrão funcional: A universal 7/14 dias, C target 5/10, '
                 'D contato frio 45/60. A regra B abre exceções por cargo.'),

    dict(n=16, slug='16-msg-padrao', tab='configuracoes', card='MSG Padr',
         spot=('__spotCard', ['MSG Padr', 12, 16]),
         legenda='As variáveis são clicáveis e o sistema as substitui no disparo. '
                 'São estes modelos que a Mala Direta e o WhatsApp Update oferecem.'),

    dict(n=17, slug='17-nova-atividade', tab='atividades',
         spot=('__spotUp', ['button[onclick*="openActivityModal"]', '.section-title', 12, 14]),
         legenda='Atividade é o combustível do sistema: zera o contador de dias sem '
                 'contato, move o Dashboard, alimenta o Radar e o Relatório Semanal.'),

    dict(n=18, slug='18-wikitoca', tab='wikitoca',
         spot=('__spot', ['.wiki-submodule-bar', 12, 14]),
         legenda='Conhecimentos são registros curtos; Documentos têm o texto extraído '
                 'e indexado; Capacitação é isolada e não entra na base do iToca.'),

    dict(n=19, slug='19-base-update', tab='iata',
         spot=('__spotUnion', [['#itocaBaseUpdateBtn', '#itocaBaseUpdatedAt'], 10, 12]),
         legenda='Antes de rodar o Base Update, o assistente não sabe nada sobre os '
                 'seus dados. A indexação é incremental — repetir é barato.'),

    dict(n=20, slug='20-automacoes-autotoca', tab='autotoca',
         spot=('__spotUp', ['#reportsBtn_preparar-reuniao', 'div[style*="flex-wrap"]', 12, 14]),
         legenda='Nove automações, cada uma consumindo um pedaço do que foi '
                 'configurado na Fase 2: LinkedIn e extensão, Microsoft 365, WAHA, '
                 'robô de formulário e transcrição de áudio.'),

    dict(n=21, slug='21-account-planning', tab='gestao-conta',
         spot=('__spot', ['#gestaoContaSubBtn_planning', 10, 12]),
         legenda='Account Planning, Campanha e AutoMapping combinam LLM, busca web e '
                 'a sua base de contas. Com a carteira vazia, a IA analisa o vazio — '
                 'deixe para depois dos passos 10 a 17.'),

    dict(n=22, slug='22-backup', tab='configuracoes', card='Backup do Banco',
         spot=('__spotCard', ['Backup do Banco', 12, 16]),
         legenda='Exportar Banco gera a cópia que você guarda fora da máquina. '
                 'Importar Banco SUBSTITUI o banco atual — confira o que importa.'),

    dict(n=23, slug='23-logs-depuracao', tab='configuracoes', card='Logs de Depura',
         spot=('__spot', ['#debugLogsSettingsCard', 12, 16]),
         legenda='Quando algo falhar de forma intermitente, ligue o modo depuração: '
                 'o cliente passa a mandar os eventos dele para o app.log do servidor.'),
]


def close_modals(page):
    """Usa os fechadores do próprio app e remove modais criados via JS.

    `#accountModal` é inserido no DOM a cada abertura; sem remover a cópia
    anterior, `document.querySelector` passa a acertar a versão antiga (oculta,
    rect 0x0) e o destaque sai vazio.
    """
    page.evaluate("""() => {
        ['closePresenceModal', 'closeAccountModal', 'closeClientModal',
         'closeAccountViewModal'].forEach(fn => {
            try { if (typeof window[fn] === 'function') window[fn](); } catch (e) {}
        });
        document.querySelectorAll('#accountModal, #presenceModal').forEach(m => m.remove());
        document.querySelectorAll('.modal').forEach(m => m.classList.remove('active'));
        window.__clear && window.__clear();
    }""")
    page.wait_for_timeout(350)


def goto_tab(page, tab):
    page.evaluate(f"() => switchTab(null, '{tab}')")
    page.wait_for_timeout(1400)


def open_modal(page, kind):
    if kind == 'client':
        page.evaluate("() => openClientModal()")
    elif kind == 'account':
        acc = page.evaluate("""async () => {
            const r = await fetch('/api/accounts');
            const l = await r.json();
            return Array.isArray(l) && l.length ? l[0].id : null;
        }""")
        if acc is None:
            return False
        page.evaluate(f"() => openAccountModal({acc})")
    page.wait_for_timeout(1800)
    return True


def main():
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={'width': 1500, 'height': 940},
                                  device_scale_factor=2,
                                  locale='pt-BR')
        page = ctx.new_page()
        page.goto(BASE, wait_until='networkidle')
        page.wait_for_timeout(3500)
        page.add_init_script(HELPERS)
        page.evaluate('() => {' + HELPERS + '}')

        for shot in SHOTS:
            slug = shot['slug']
            try:
                close_modals(page)
                goto_tab(page, shot['tab'])
                if shot.get('card'):
                    page.evaluate('() => {' + HELPERS + '}')
                    st = page.evaluate("(t) => window.__openCard(t)", shot['card'])
                    if st != 'aberto':
                        results.append((slug, f'CARD:{st}'))
                        continue
                    page.wait_for_timeout(700)
                if shot.get('open_modal'):
                    if not open_modal(page, shot['open_modal']):
                        results.append((slug, 'SEM_DADOS_PARA_MODAL'))
                        continue
                page.evaluate('() => {' + HELPERS + '}')
                fn, args = shot['spot']
                out = page.evaluate(
                    f"(a) => window.{fn}.apply(null, a)", args)
                if isinstance(out, str) and out.startswith('NOT_FOUND'):
                    results.append((slug, out))
                    continue
                page.wait_for_timeout(450)
                if not PROBE_ONLY:
                    page.screenshot(path=str(OUT / f'{slug}.png'))
                results.append((slug, out))
            except Exception as e:
                results.append((slug, f'ERRO: {type(e).__name__}: {e}'))

        browser.close()

    ok = [r for r in results if not isinstance(r[1], str)]
    bad = [r for r in results if isinstance(r[1], str)]
    for slug, info in results:
        flag = '  ' if not isinstance(info, str) else 'XX'
        print(f'{flag} {slug:34s} {info}')
    print(f'\n{len(ok)} ok / {len(bad)} com problema de {len(results)}')
    (OUT / 'resultado.json').write_text(
        json.dumps([[s, i if isinstance(i, str) else 'ok'] for s, i in results],
                   ensure_ascii=False, indent=2), encoding='utf-8')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
