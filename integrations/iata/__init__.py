# -*- coding: utf-8 -*-
"""Lógica pura do iAta, dividida por responsabilidade:

- `reconcile.py` — normalização de nomes e reconciliação da hierarquia com
  a ata anterior (Task 2).
- `llm.py` — prompt de extração e parsing da resposta da IA para o formato
  canônico (Task 3).
- `render.py` — renderização em texto e e-mail (Tasks 4-5). 210 linhas.
- `edit.py` — casamento da hierarquia reestruturada por um re-parse com a
  hierarquia antiga da MESMA ata, ao editar o texto de uma ata já salva
  (Task 9; extraído de `routes/autotoca_iata.py` na revisão final para morar
  ao lado de `reconcile.py`, mesma classe de problema).

Este `__init__.py` reexporta tudo num namespace só, porque o resto do
projeto (rotas em `app.py`, Tasks 6-10 do plano) importa como
`from integrations import iata as iata_lib` e chama `iata_lib.reconcile`,
`iata_lib.parse_hierarchy`, `iata_lib.SEM_UPDATE` etc. sem se importar com
o arquivo interno onde cada coisa mora — dividir o pacote não pode mudar
esse contrato. Inclui `_loads_tolerante` em `__all__`, mesmo sendo privada
de `llm.py` por convenção de nome, porque rotas (reparse da ata) chamam-na
diretamente — mantê-la fora de `__all__` contradiria esta própria docstring.
"""

from .reconcile import (
    GERENTE_NAO_IDENTIFICADO,
    SEM_UPDATE,
    match_account_name,
    normalize_name,
    reconcile,
)
from .llm import (
    MAX_TRANSCRICAO_CHARS,
    build_extraction_prompt,
    build_reparse_prompt,
    merge_hierarchies,
    parse_hierarchy,
    split_transcricao,
    _loads_tolerante,
)
from .render import (
    render_markdown,
    render_email_html,
    email_subject,
)
from .edit import (
    carregar_campos_anteriores,
    flatten_opportunities,
    match_previous_accounts,
    match_previous_items,
    titulo_apos_edicao,
)

__all__ = [
    'GERENTE_NAO_IDENTIFICADO',
    'SEM_UPDATE',
    'normalize_name',
    'reconcile',
    'MAX_TRANSCRICAO_CHARS',
    'build_extraction_prompt',
    'build_reparse_prompt',
    'merge_hierarchies',
    'parse_hierarchy',
    'split_transcricao',
    '_loads_tolerante',
    'match_account_name',
    'render_markdown',
    'render_email_html',
    'email_subject',
    'carregar_campos_anteriores',
    'flatten_opportunities',
    'match_previous_accounts',
    'match_previous_items',
    'titulo_apos_edicao',
]
