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
