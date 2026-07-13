# -*- coding: utf-8 -*-
"""Gera os assets do coelho verde a partir de public/videos/Loading_Bunny.mp4.

Saidas:
  - public/images/coelho-correndo.webp  (WebP animado com fundo transparente,
    usado pela classe .coelho-run nas barras de progresso do index.html)
  - coelho_icon_transparent.ico         (icone multi-tamanho 16-256px usado pelo
    exe/PyInstaller, atalhos do instalador NSIS e icone de bandeja)

Como funciona a remocao do fundo preto:
  - O fundo do video e preto puro; um chroma key global apagaria tambem as
    pupilas e contornos escuros do coelho. Por isso a mascara e construida por
    flood fill: so vira transparente a regiao escura CONECTADA as bordas do
    quadro (scipy.ndimage.label), preservando pixels escuros internos.
  - A marca d'agua "Veo" (canto inferior direito) e forcada a transparente.
  - MP4/H.264 nao suporta canal alfa — por isso o formato de saida e WebP
    animado (alfa nativo, suportado pelo WebView2/Chromium e navegadores).

Dependencias: pip install pillow numpy scipy imageio-ffmpeg
Uso: python scripts/gerar_assets_coelho.py  (a partir da raiz do projeto)
"""
import os
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage
import imageio_ffmpeg

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO = os.path.join(RAIZ, 'public', 'videos', 'Loading_Bunny.mp4')
WEBP_SAIDA = os.path.join(RAIZ, 'public', 'images', 'coelho-correndo.webp')
ICO_SAIDA = os.path.join(RAIZ, 'coelho_icon_transparent.ico')

LIMIAR_ESCURO = 45      # max(R,G,B) <= isto e candidato a fundo
MARCA_X, MARCA_Y = 900, 500  # regiao da marca d'agua (sempre transparente)
FRAME_LOOP = 46         # frame mais parecido com o frame 0 (loop suave)
FRAME_ICONE = 51        # pose mais "quadrada" e simpatica para o icone
ALTURA_WEBP = 144


def remover_fundo(caminho_png):
    rgb = np.array(Image.open(caminho_png).convert('RGB'))
    escuro = rgb.max(axis=2).astype(int) <= LIMIAR_ESCURO
    rotulos, _ = ndimage.label(escuro)
    borda = set(np.unique(np.concatenate([
        rotulos[0, :], rotulos[-1, :], rotulos[:, 0], rotulos[:, -1]])))
    borda.discard(0)
    fundo = np.isin(rotulos, list(borda))
    alfa = np.where(fundo, 0, 255).astype(np.uint8)
    alfa[MARCA_Y:, MARCA_X:] = 0
    # suaviza a borda do recorte (antialias) sem comer o contorno
    alfa = np.array(Image.fromarray(alfa).filter(ImageFilter.GaussianBlur(0.8)))
    return np.dstack([rgb, alfa])


def main():
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([ffmpeg, '-y', '-hide_banner', '-loglevel', 'error',
                        '-i', VIDEO, os.path.join(tmp, 'f%04d.png')], check=True)
        arquivos = sorted(f for f in os.listdir(tmp) if f.endswith('.png'))
        quadros = [remover_fundo(os.path.join(tmp, f))
                   for f in arquivos[:max(FRAME_LOOP, FRAME_ICONE + 1)]]

    loop = quadros[:FRAME_LOOP]

    # recorte pela uniao das areas visiveis do loop (+margem)
    uniao = np.zeros(loop[0].shape[:2], bool)
    for q in loop:
        uniao |= q[:, :, 3] > 8
    ys, xs = np.where(uniao)
    m = 6
    x0, x1 = max(0, xs.min() - m), min(uniao.shape[1], xs.max() + 1 + m)
    y0, y1 = max(0, ys.min() - m), min(uniao.shape[0], ys.max() + 1 + m)

    # 24fps -> 12fps (frames alternados) para reduzir tamanho
    imagens = []
    for i in range(0, len(loop), 2):
        im = Image.fromarray(loop[i][y0:y1, x0:x1])
        larg = round(im.width * ALTURA_WEBP / im.height)
        imagens.append(im.resize((larg, ALTURA_WEBP), Image.LANCZOS))
    imagens[0].save(WEBP_SAIDA, save_all=True, append_images=imagens[1:],
                    duration=83, loop=0, quality=85, method=6)
    print('gerado:', WEBP_SAIDA, os.path.getsize(WEBP_SAIDA), 'bytes')

    # icone: frame estatico centralizado em quadrado transparente
    q = quadros[FRAME_ICONE]
    vis = q[:, :, 3] > 8
    ys, xs = np.where(vis)
    rec = Image.fromarray(q[ys.min():ys.max() + 1, xs.min():xs.max() + 1])
    lado = max(rec.size) + 16
    quadrado = Image.new('RGBA', (lado, lado), (0, 0, 0, 0))
    quadrado.paste(rec, ((lado - rec.width) // 2, (lado - rec.height) // 2))
    base = quadrado.resize((256, 256), Image.LANCZOS)
    base.save(ICO_SAIDA, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                (64, 64), (128, 128), (256, 256)])
    print('gerado:', ICO_SAIDA, os.path.getsize(ICO_SAIDA), 'bytes')


if __name__ == '__main__':
    main()
