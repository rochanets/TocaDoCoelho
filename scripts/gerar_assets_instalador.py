# -*- coding: utf-8 -*-
"""Gera os bitmaps de identidade visual do instalador NSIS (verde + coelho).

Saidas (usadas por installer.nsi via MUI_HEADERIMAGE_BITMAP /
MUI_WELCOMEFINISHPAGE_BITMAP):
  - installer_assets/header.bmp   (150x57  — banner do topo das paginas internas)
  - installer_assets/welcome.bmp  (164x314 — ilustracao lateral de boas-vindas/conclusao)

NSIS exige BMP Windows 3.x de 24 bits sem compressao nesses tamanhos exatos —
por isso os bitmaps sao gerados em vez de editados a mao.

Dependencias: pip install pillow
Uso: python scripts/gerar_assets_instalador.py  (a partir da raiz do projeto)
"""
import os

from PIL import Image

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICONE = os.path.join(RAIZ, 'coelho_icon_transparent.ico')
SAIDA = os.path.join(RAIZ, 'installer_assets')

VERDE_ESCURO = (6, 78, 59)     # #065f46
VERDE_MEDIO = (5, 150, 105)    # #059669
VERDE_CLARO = (16, 185, 129)   # #10b981


def gradiente_vertical(w, h, topo, base):
    img = Image.new('RGB', (w, h))
    px = img.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        cor = tuple(int(topo[i] + (base[i] - topo[i]) * t) for i in range(3))
        for x in range(w):
            px[x, y] = cor
    return img


def gradiente_horizontal(w, h, esquerda, direita):
    img = Image.new('RGB', (w, h))
    px = img.load()
    for x in range(w):
        t = x / max(w - 1, 1)
        cor = tuple(int(esquerda[i] + (direita[i] - esquerda[i]) * t) for i in range(3))
        for y in range(h):
            px[x, y] = cor
    return img


def colar_icone_ajustado(base, icone, largura_max, altura_max, centro_x, centro_y):
    w, h = icone.size
    escala = min(largura_max / w, altura_max / h)
    redimensionado = icone.resize((max(1, int(w * escala)), max(1, int(h * escala))), Image.LANCZOS)
    x = centro_x - redimensionado.width // 2
    y = centro_y - redimensionado.height // 2
    base.paste(redimensionado, (x, y), redimensionado)


def main():
    os.makedirs(SAIDA, exist_ok=True)
    icone_bruto = Image.open(ICONE).convert('RGBA')
    icone = icone_bruto.crop(icone_bruto.getbbox())

    header = gradiente_horizontal(150, 57, VERDE_MEDIO, VERDE_ESCURO)
    colar_icone_ajustado(header, icone, 48, 48, 150 - 30, 57 // 2)
    header.convert('RGB').save(os.path.join(SAIDA, 'header.bmp'), 'BMP')

    lateral = gradiente_vertical(164, 314, VERDE_CLARO, VERDE_ESCURO)
    colar_icone_ajustado(lateral, icone, 118, 118, 164 // 2, 95)
    lateral.convert('RGB').save(os.path.join(SAIDA, 'welcome.bmp'), 'BMP')

    print('Gerado:', os.listdir(SAIDA))


if __name__ == '__main__':
    main()
