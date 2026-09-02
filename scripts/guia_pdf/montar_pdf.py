# -*- coding: utf-8 -*-
"""Monta o PDF do guia de primeiro acesso a partir das capturas com spotlight."""
import sys
from pathlib import Path

from reportlab.lib.colors import HexColor, Color
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Frame

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capturar_telas import SHOTS  # noqa: E402  reaproveita legendas e ordem

HERE = Path(__file__).resolve().parent
SHOTS_DIR = HERE / 'shots'
OUT_PDF = (HERE.parents[1] / 'public' / 'assets' / 'tutorial'
           / 'Toca-do-Coelho-Primeiro-Acesso.pdf')

PAGE = landscape(A4)          # 841.89 x 595.28
PW, PH = PAGE

# ---------------------------------------------------------------- paleta
DEEP = HexColor('#0d3b2c')
PRIMARY = HexColor('#047857')
MINT = HexColor('#34d399')
INK = HexColor('#111d18')
MUTED = HexColor('#61756d')
GROUND = HexColor('#f5f7f3')
LINE = HexColor('#d8e0d8')
AMBER = HexColor('#96590a')
AMBER_BG = HexColor('#fdf6e6')
DANGER = HexColor('#9c2f22')
DANGER_BG = HexColor('#fcf0ed')
WHITE = HexColor('#ffffff')

# ---------------------------------------------------------------- fontes
FONTS = Path('C:/Windows/Fonts')
_reg = []
for name, fn in [('Serif', 'georgia.ttf'), ('SerifB', 'georgiab.ttf'),
                 ('SerifI', 'georgiai.ttf'), ('Mono', 'consola.ttf'),
                 ('MonoB', 'consolab.ttf')]:
    try:
        pdfmetrics.registerFont(TTFont(name, str(FONTS / fn)))
        _reg.append(name)
    except Exception as e:
        print(f'[fonte] {name} indisponível ({e}) — usando fallback')
BODY = 'Serif' if 'Serif' in _reg else 'Times-Roman'
BOLD = 'SerifB' if 'SerifB' in _reg else 'Times-Bold'
ITAL = 'SerifI' if 'SerifI' in _reg else 'Times-Italic'
MONO = 'Mono' if 'Mono' in _reg else 'Courier'
MONOB = 'MonoB' if 'MonoB' in _reg else 'Courier-Bold'

# sem registerFontFamily o reportlab ignora <b>/<i> dentro de Paragraph
if 'Serif' in _reg:
    pdfmetrics.registerFontFamily('Serif', normal='Serif',
                                  bold=BOLD, italic=ITAL, boldItalic=BOLD)

# ---------------------------------------------------------------- conteúdo

FASES = {
    1: ('Fase 1', 'Instalar e abrir'),
    2: ('Fase 2', 'Identidade e chaves'),
    3: ('Fase 3', 'Dados de negócio'),
    4: ('Fase 4', 'IA, conhecimento e rotina'),
}

# passo -> (fase, título, selo, onde fica)
PASSOS = {
    1:  (1, 'Instalar o aplicativo', 'OBRIGATÓRIO',
         'TocaDoCoelho-Setup.exe'),
    2:  (1, 'Abrir o app e ir às Configurações', 'OBRIGATÓRIO',
         'Barra superior › ícone de engrenagem'),
    3:  (2, 'Cadastrar o seu usuário', 'OBRIGATÓRIO',
         'Configurações › Cadastro do Usuário'),
    4:  (2, 'Configurar as chaves de IA', 'OBRIGATÓRIO PARA IA',
         'Configurações › Integrações de API'),
    5:  (2, 'Adicionar a chave da Tavily', 'RECOMENDADO',
         'Configurações › Integrações de API › Tavily API Key'),
    6:  (2, 'Conectar a conta Microsoft 365', 'RECOMENDADO',
         'Configurações › Integrações de API › Conexão Microsoft 365'),
    7:  (2, 'Sincronizar o WhatsApp pelo QR code', 'RECOMENDADO',
         'Configurações › Integrações de API › Sincronizar WhatsApp'),
    8:  (2, 'Carregar a extensão do Chrome (uma única vez)', 'RECOMENDADO',
         'AutoToca · chrome://extensions'),
    9:  (2, 'Ajustar sistema, atualizações e tema', 'OPCIONAL',
         'Configurações › Sistema · Ajuda e Atualizações'),
    10: (3, 'Cadastrar os contatos', 'OBRIGATÓRIO',
         'Gestão de Contatos › Novo Contato · Importar Excel'),
    11: (3, 'Completar o cadastro de cada conta', 'OBRIGATÓRIO',
         'Gestão de Conta › Contas › Editar Conta'),
    12: (3, 'Registrar os Serviços Stefanini da conta', 'OBRIGATÓRIO',
         'Gestão de Conta › Contas › Serviço Stefanini'),
    13: (3, 'Cadastrar as ofertas do portfólio', 'RECOMENDADO',
         'Portifólio › Soluções STF › ✦ Nova Oferta'),
    14: (3, 'Criar os agrupamentos de cargos', 'RECOMENDADO',
         'Configurações › Agrupamento de Cargos'),
    15: (3, 'Calibrar a Faixa de Status', 'OPCIONAL',
         'Configurações › Faixa de Status'),
    16: (3, 'Escrever as MSG Padrão', 'RECOMENDADO',
         'Configurações › MSG Padrão'),
    17: (3, 'Registrar as primeiras atividades', 'OBRIGATÓRIO',
         'Atividades › Nova Atividade'),
    18: (4, 'Abastecer a WikiToca', 'RECOMENDADO',
         'WikiToca › Conhecimentos · Documentos · Capacitação'),
    19: (4, 'Rodar o Base Update do iToca', 'OBRIGATÓRIO PARA O ASSISTENTE',
         'iToca › ✦ Base Update'),
    20: (4, 'Experimentar as automações do AutoToca', 'OPCIONAL',
         'AutoToca'),
    21: (4, 'Campanha, Account Planning e AutoMapping', 'OPCIONAL',
         'Campanha · Gestão de Conta › Account Planning'),
    22: (4, 'Fechar o ciclo com backup fora da máquina', 'OBRIGATÓRIO',
         'Configurações › Backup do Banco de Dados › Exportar Banco'),
    23: (4, 'Onde olhar quando algo falhar', 'REFERÊNCIA',
         'Configurações › Logs de Depuração'),
}

SELO_COR = {
    'OBRIGATÓRIO': (DEEP, WHITE),
    'OBRIGATÓRIO PARA IA': (DEEP, WHITE),
    'OBRIGATÓRIO PARA O ASSISTENTE': (DEEP, WHITE),
    'RECOMENDADO': (HexColor('#e3f2ea'), PRIMARY),
    'OPCIONAL': (GROUND, MUTED),
    'REFERÊNCIA': (GROUND, MUTED),
}

# Passo 1 não tem tela: acontece fora do app.
PAGINA_TEXTO_1 = [
    'A instalação é por usuário e não pede UAC: duplo clique em '
    'TocaDoCoelho-Setup.exe, Next → Next → Install. Os binários vão para '
    '%LocalAppData%\\TocaDoCoelho e um atalho aparece na Área de Trabalho.',
    'Você não precisa instalar Python, FFmpeg nem Node.js — os três vêm dentro '
    'do pacote. Seus dados (banco SQLite, uploads, logs) ficam separados dos '
    'binários, em %AppData%\\toca-do-coelho\\, e o instalador nunca os toca.',
    'Se havia uma instalação antiga em C:\\Program Files\\TocaDoCoelho, ela é '
    'migrada automaticamente na atualização. A desinstalação preserva os dados '
    'do usuário por padrão.',
]



# ------------------------------------------------- imagens para impressão
LARGURA_ALVO = 1800          # px; a 640pt de largura dá ~203 DPI
QUALIDADE_JPEG = 84
CACHE_JPG = HERE / 'shots_jpg'


def preparar_imagem(png_path):
    """Reduz e converte para JPEG, cacheando. Devolve o caminho a usar no PDF."""
    from PIL import Image
    CACHE_JPG.mkdir(exist_ok=True)
    destino = CACHE_JPG / (png_path.stem + '.jpg')
    if destino.exists() and destino.stat().st_mtime >= png_path.stat().st_mtime:
        return destino
    with Image.open(png_path) as im:
        im = im.convert('RGB')
        if im.width > LARGURA_ALVO:
            alt = round(im.height * LARGURA_ALVO / im.width)
            im = im.resize((LARGURA_ALVO, alt), Image.LANCZOS)
        im.save(destino, 'JPEG', quality=QUALIDADE_JPEG, optimize=True,
                progressive=True)
    return destino


# ------------------------------------------------- saneamento de glifos
# Georgia não tem "→", "✦", "✓"; Consolas não tem "✦".
# Sem isto o PDF sai com quadradinhos de "glifo ausente" no lugar.
SUBST = {
    '→': '›',      # seta  -> chevron
    '✦': '',            # estrela de IA -> removida (nome do botão basta)
    '✓': '-',
    '★': '*',
    '▸': '›',
}


def san(txt):
    if not isinstance(txt, str):
        return txt
    for a, b in SUBST.items():
        txt = txt.replace(a, b)
    while '  ' in txt:
        txt = txt.replace('  ', ' ')
    return txt.strip()


def checar_glifos(strings):
    """Aborta se alguma string usar caractere que a fonte não tem."""
    problemas = []
    for nome in (BODY, BOLD, MONO, MONOB):
        try:
            cmap = pdfmetrics.getFont(nome).face.charToGlyph
        except Exception:
            continue
        faltando = set()
        for t in strings:
            for ch in t:
                if ch.isspace():
                    continue
                    continue
                if ord(ch) not in cmap:
                    faltando.add(ch)
        if faltando:
            problemas.append((nome, sorted(faltando)))
    return problemas

# ---------------------------------------------------------------- helpers

def texto(c, x, y, s, fonte, tam, cor, leading=None):
    c.setFont(fonte, tam)
    c.setFillColor(cor)
    c.drawString(x, y, san(s))
    return y - (leading or tam * 1.35)


def paragrafo(c, x, y, w, h, html, fonte=BODY, tam=10.5, leading=14.5,
              cor=INK, align=TA_LEFT):
    st = ParagraphStyle('p', fontName=fonte, fontSize=tam, leading=leading,
                        textColor=cor, alignment=align)
    p = Paragraph(san(html), st)
    fr = Frame(x, y, w, h, leftPadding=0, rightPadding=0,
               topPadding=0, bottomPadding=0, showBoundary=0)
    fr.addFromList([p], c)


def selo(c, x, y, label):
    bg, fg = SELO_COR.get(label, (GROUND, MUTED))
    c.setFont(MONOB, 6.8)
    w = c.stringWidth(san(label), MONOB, 6.8) + 12
    c.setFillColor(bg)
    c.roundRect(x, y - 2.5, w, 13, 2.5, stroke=0, fill=1)
    if label in ('OPCIONAL', 'REFERÊNCIA', 'RECOMENDADO'):
        c.setStrokeColor(LINE if label != 'RECOMENDADO' else PRIMARY)
        c.setLineWidth(0.5)
        c.roundRect(x, y - 2.5, w, 13, 2.5, stroke=1, fill=0)
    c.setFillColor(fg)
    c.drawString(x + 6, y + 1.5, san(label))
    return w


def badge_numero(c, cx, cy, n, obrigatorio):
    r = 13
    if obrigatorio:
        c.setFillColor(DEEP)
        c.circle(cx, cy, r, stroke=0, fill=1)
        c.setFillColor(GROUND)
    else:
        c.setFillColor(WHITE)
        c.setStrokeColor(LINE)
        c.setLineWidth(0.9)
        c.circle(cx, cy, r, stroke=1, fill=1)
        c.setFillColor(DEEP)
    s = str(n)
    c.setFont(MONOB, 12)
    c.drawCentredString(cx, cy - 4.2, s)


def rodape(c, pagina, total, fase_txt):
    c.setStrokeColor(LINE)
    c.setLineWidth(0.6)
    c.line(40, 30, PW - 40, 30)
    c.setFont(MONO, 7.4)
    c.setFillColor(MUTED)
    c.drawString(40, 19, 'Toca do Coelho · Guia de Primeiro Acesso')
    c.drawCentredString(PW / 2, 19, fase_txt)
    c.drawRightString(PW - 40, 19, f'{pagina} / {total}')


# ---------------------------------------------------------------- páginas

def capa(c):
    c.setFillColor(DEEP)
    c.rect(0, 0, PW, PH, stroke=0, fill=1)

    # faixa de acento
    c.setFillColor(MINT)
    c.rect(0, PH - 6, PW, 6, stroke=0, fill=1)

    y = PH - 96
    c.setFont(MONOB, 9)
    c.setFillColor(MINT)
    c.drawString(64, y, 'TOCA DO COELHO  ·  ROTEIRO DE IMPLANTAÇÃO')

    y -= 54
    c.setFont(BOLD, 44)
    c.setFillColor(WHITE)
    c.drawString(64, y, 'Primeiro Acesso')
    y -= 50
    c.drawString(64, y, 'à Toca do Coelho')

    y -= 40
    paragrafo(c, 64, y - 62, 470, 66,
              'Vinte e três passos na ordem em que as dependências exigem — do '
              'instalador até o assistente respondendo sobre os seus próprios '
              'dados. Cada passo traz a tela real do sistema com o ponto exato '
              'em destaque.',
              fonte=BODY, tam=12.5, leading=17.5, cor=HexColor('#c9ded4'))

    # blocos de fase
    bx, by = 64, 150
    bw = (PW - 128 - 3 * 14) / 4
    faixas = [('Passos 1–2', 'Instalar e abrir'),
              ('Passos 3–9', 'Identidade e chaves'),
              ('Passos 10–17', 'Dados de negócio'),
              ('Passos 18–23', 'IA e rotina')]
    for i, (rng, nome) in enumerate(faixas):
        x = bx + i * (bw + 14)
        c.setStrokeColor(HexColor('#1d5a45'))
        c.setLineWidth(1)
        c.setFillColor(HexColor('#0f4635'))
        c.roundRect(x, by, bw, 66, 5, stroke=1, fill=1)
        c.setFont(MONOB, 7.2)
        c.setFillColor(MINT)
        c.drawString(x + 13, by + 46, rng.upper())
        c.setFont(BOLD, 12.5)
        c.setFillColor(WHITE)
        c.drawString(x + 13, by + 24, nome)

    c.setFont(MONO, 7.6)
    c.setFillColor(HexColor('#7fb6a0'))
    c.drawString(64, 62, 'Capturas geradas em instância isolada (banco fictício) — '
                         'nenhum dado de produção aparece neste documento.')
    c.showPage()


def pagina_aviso(c, total):
    c.setFillColor(WHITE)
    c.rect(0, 0, PW, PH, stroke=0, fill=1)

    y = PH - 60
    c.setFont(MONOB, 8.4)
    c.setFillColor(DANGER)
    c.drawString(40, y, 'ANTES DE COMEÇAR')
    y -= 34
    c.setFont(BOLD, 26)
    c.setFillColor(DEEP)
    c.drawString(40, y, 'Proteja o banco em uso')

    y -= 26
    c.setFillColor(DANGER_BG)
    c.setStrokeColor(DANGER)
    c.setLineWidth(0.8)
    box_h = 150
    c.roundRect(40, y - box_h, PW - 80, box_h, 4, stroke=1, fill=1)

    paragrafo(c, 58, y - box_h + 14, PW - 116, box_h - 26,
              '<b>Duas ações da ferramenta apagam ou substituem o banco de '
              'produção, e ambas ficam a um clique de distância.</b><br/><br/>'
              '<b>Configurações › Backup do Banco › Importar Banco</b> substitui o '
              'banco atual pelo arquivo escolhido. Ele grava um backup automático '
              'antes, mas confira o que está importando.<br/><br/>'
              '<b>RESETAR_BANCO.bat</b>, na pasta do projeto, apaga o banco e cria '
              'um novo em branco. Não faz parte de nenhum fluxo de configuração — '
              'não rode.',
              tam=11, leading=15.5)

    y = y - box_h - 30
    paragrafo(c, 40, y - 78, (PW - 96) / 2, 78,
              '<b>Faça um backup antes do primeiro passo.</b><br/>'
              'Em <b>Configurações › Backup do Banco de Dados</b>, use '
              '<b>Exportar Banco</b> e guarde o arquivo fora da máquina. O backup '
              'automático existe — a cada 3 dias, em '
              '%AppData%\\toca-do-coelho\\backups\\ — mas só roda quando o app é '
              'aberto.', tam=10.5, leading=14.5)

    paragrafo(c, 40 + (PW - 96) / 2 + 16, y - 78, (PW - 96) / 2, 78,
              '<b>Como ler os selos deste guia.</b><br/>'
              'Número <b>preenchido</b> = passo obrigatório: sem ele, os seguintes '
              'ficam sem matéria-prima. Número <b>vazado</b> = recomendado ou '
              'opcional. Em cada tela, a área em cores normais é onde você atua; o '
              'resto está escurecido de propósito.',
              tam=10.5, leading=14.5)

    rodape(c, 2, total, 'Aviso')
    c.showPage()


def pagina_indice(c, total):
    c.setFillColor(WHITE)
    c.rect(0, 0, PW, PH, stroke=0, fill=1)

    c.setFont(MONOB, 8.4)
    c.setFillColor(PRIMARY)
    c.drawString(40, PH - 52, 'ROTEIRO COMPLETO')
    c.setFont(BOLD, 24)
    c.setFillColor(DEEP)
    c.drawString(40, PH - 82, 'Os 23 passos, em ordem')

    col_w = (PW - 80 - 26) / 2
    y0 = PH - 116
    y = y0
    x = 40
    fase_atual = None
    for n in sorted(PASSOS):
        fase, titulo, tag, onde = PASSOS[n]
        if n == 13:                      # quebra de coluna
            x = 40 + col_w + 26
            y = y0
            fase_atual = None
        if fase != fase_atual:
            fase_atual = fase
            y -= 6
            c.setFont(MONOB, 7.2)
            c.setFillColor(PRIMARY)
            c.drawString(x, y, f'{FASES[fase][0].upper()} · {FASES[fase][1].upper()}')
            y -= 15
        obrig = tag.startswith('OBRIGAT')
        c.setFont(MONOB, 9)
        c.setFillColor(DEEP if obrig else MUTED)
        c.drawRightString(x + 15, y, str(n))
        c.setFont(BOLD if obrig else BODY, 10.2)
        c.setFillColor(INK)
        c.drawString(x + 22, y, san(titulo)[:58])
        y -= 13
        c.setFont(MONO, 7.4)
        c.setFillColor(MUTED)
        c.drawString(x + 22, y, san(onde)[:74])
        y -= 17

    rodape(c, 3, total, 'Índice')
    c.showPage()


def pagina_passo(c, n, legenda, img_path, pagina, total, sufixo=''):
    fase, titulo, tag, onde = PASSOS[n]
    obrig = tag.startswith('OBRIGAT')

    c.setFillColor(WHITE)
    c.rect(0, 0, PW, PH, stroke=0, fill=1)

    # ---- cabeçalho
    top = PH - 30
    c.setFont(MONOB, 7.4)
    c.setFillColor(PRIMARY)
    c.drawString(40, top - 8, f'{FASES[fase][0].upper()} · {FASES[fase][1].upper()}')

    badge_numero(c, 53, top - 40, n, obrig)

    c.setFont(BOLD, 17)
    c.setFillColor(DEEP)
    tx = 76
    c.drawString(tx, top - 45, san(titulo + sufixo))
    tw = c.stringWidth(san(titulo + sufixo), BOLD, 17)
    selo(c, tx + tw + 12, top - 45, tag)

    c.setFont(MONO, 8.4)
    c.setFillColor(MUTED)
    c.drawString(tx, top - 61, san(onde))

    # ---- grade vertical fixa: legenda tem altura garantida, imagem usa o resto
    #      (frame apertado faz o reportlab descartar o parágrafo em silêncio)
    CAP_Y, CAP_H = 42.0, 64.0          # caixa da legenda
    img_top = top - 74                 # abaixo do cabeçalho
    img_bottom = CAP_Y + CAP_H + 10

    # ---- imagem
    if img_path is not None:
        ir = ImageReader(str(preparar_imagem(img_path)))
        iw, ih = ir.getSize()
        disp_h = img_top - img_bottom
        img_w = disp_h * iw / ih
        if img_w > PW - 80:            # não passa das margens laterais
            img_w = PW - 80.0
            disp_h = img_w * ih / iw
        ix = (PW - img_w) / 2
        iy = img_top - disp_h
        c.setStrokeColor(LINE)
        c.setLineWidth(0.8)
        c.rect(ix - 1, iy - 1, img_w + 2, disp_h + 2, stroke=1, fill=0)
        c.drawImage(ir, ix, iy, width=img_w, height=disp_h)

    # ---- legenda
    if img_path is not None:
        c.setFillColor(GROUND)
        c.setStrokeColor(LINE)
        c.setLineWidth(0.6)
        c.roundRect(40, CAP_Y, PW - 80, CAP_H, 3, stroke=1, fill=1)
        paragrafo(c, 56, CAP_Y + 9, PW - 112, CAP_H - 16,
                  legenda, tam=10.8, leading=14.8)
    else:
        cap_top = top - 96
        yy = cap_top
        for bloco in legenda:
            paragrafo(c, 40, yy - 62, (PW - 80) * 0.62, 62, bloco,
                      tam=11.5, leading=16.5)
            yy -= 68

    rodape(c, pagina, total, f'Passo {n}')
    c.showPage()


# ---------------------------------------------------------------- main

def main():
    faltando = [s['slug'] for s in SHOTS
                if not (SHOTS_DIR / f"{s['slug']}.png").exists()]
    if faltando:
        print('FALTAM capturas:', faltando)
        return 1

    todas = []
    for n, (fase, titulo, tag, onde) in PASSOS.items():
        todas += [san(titulo), san(tag), san(onde)]
    todas += [san(x['legenda']) for x in SHOTS]
    todas += [san(x) for x in PAGINA_TEXTO_1]
    probs = checar_glifos(todas)
    if probs:
        for fonte, chars in probs:
            print(f'GLIFO AUSENTE em {fonte}: ' +
                  ' '.join(f'U+{ord(ch):04X}' for ch in chars))
        return 1

    # ordena as capturas pelo número do passo, mantendo a ordem interna
    ordenadas = sorted(SHOTS, key=lambda s: (s['n'], SHOTS.index(s)))

    # numeração: capa + aviso + índice + passo 1 (texto) + capturas
    total = 3 + 1 + len(ordenadas)

    c = canvas.Canvas(str(OUT_PDF), pagesize=PAGE)
    c.setTitle('Toca do Coelho — Guia de Primeiro Acesso')
    c.setAuthor('Toca do Coelho')
    c.setSubject('Configuração inicial passo a passo, com telas destacadas')

    capa(c)
    pagina_aviso(c, total)
    pagina_indice(c, total)

    pag = 4
    pagina_passo(c, 1, PAGINA_TEXTO_1, None, pag, total)
    pag += 1

    # sufixos quando um passo tem mais de uma tela
    vistos = {}
    contagem = {}
    for s in ordenadas:
        contagem[s['n']] = contagem.get(s['n'], 0) + 1

    for s in ordenadas:
        n = s['n']
        vistos[n] = vistos.get(n, 0) + 1
        sufixo = ''
        if contagem[n] > 1:
            sufixo = f'  ({vistos[n]} de {contagem[n]})'
        pagina_passo(c, n, s['legenda'], SHOTS_DIR / f"{s['slug']}.png",
                     pag, total, sufixo)
        pag += 1

    c.save()
    kb = OUT_PDF.stat().st_size / 1024
    print(f'OK  {OUT_PDF.name}  —  {pag - 1} páginas, {kb:.0f} KB')
    return 0


if __name__ == '__main__':
    sys.exit(main())
