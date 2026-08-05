# -*- coding: utf-8 -*-
"""Lógica pura do iAta, dividida por responsabilidade:

- `reconcile.py` — normalização de nomes e reconciliação da hierarquia com
  a ata anterior (Task 2).
- `llm.py` — prompt de extração e parsing da resposta da IA para o formato
  canônico (Task 3).
- `render.py` — renderização em texto e e-mail (Tasks 4-5, ainda vazio).

Este `__init__.py` reexporta tudo num namespace só, porque o resto do
projeto (rotas em `app.py`, Tasks 6-10 do plano) importa como
`from integrations import iata as iata_lib` e chama `iata_lib.reconcile`,
`iata_lib.parse_hierarchy`, `iata_lib.SEM_UPDATE` etc. sem se importar com
o arquivo interno onde cada coisa mora — dividir o pacote não pode mudar
esse contrato. Inclui `_loads_tolerante`, mesmo sendo privada de `llm.py`,
porque rotas de tasks futuras (reparse da ata) chamam-na diretamente.
"""

from .reconcile import (
    GERENTE_NAO_IDENTIFICADO,
    SEM_UPDATE,
    normalize_name,
    reconcile,
)
from .llm import (
    MAX_TRANSCRICAO_CHARS,
    build_extraction_prompt,
    parse_hierarchy,
    _loads_tolerante,
)
from .render import (
    render_markdown,
    render_email_html,
    email_subject,
)

__all__ = [
    'GERENTE_NAO_IDENTIFICADO',
    'SEM_UPDATE',
    'normalize_name',
    'reconcile',
    'MAX_TRANSCRICAO_CHARS',
    'build_extraction_prompt',
    'parse_hierarchy',
    'render_markdown',
    'render_email_html',
    'email_subject',
]
