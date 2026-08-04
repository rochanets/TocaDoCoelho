# -*- coding: utf-8 -*-
"""Modelo do bundled_credentials.py — copie para `bundled_credentials.py` e preencha.

O arquivo real NÃO é versionado (está no .gitignore). O repositório
`rochanets/TocaDoCoelho` é PÚBLICO: uma chave commitada aqui vira uma chave
vazada, porque robôs varrem o GitHub atrás de prefixos como `tvly-` e `sk-`
poucos minutos depois do push.

Diferente do `graph_credentials.py`, que guarda só o tenant/client ID do
Microsoft 365 — identificadores públicos por design no fluxo PKCE, e por isso
versionados sem problema —, aqui ficam segredos de verdade.

Como isto chega ao usuário final: o PyInstaller embarca o arquivo no build
(`--add-data "bundled_credentials.py;."` + `--hidden-import bundled_credentials`
— ver PASSO_A_PASSO_BUILD_CMD.md). Instalações novas passam a funcionar sem o
usuário configurar nada.

Precedência em tempo de execução (ver _resolve_bundled_setting em app.py):
    1. chave que o usuário salvou em Configurações > Integrações;
    2. variável de ambiente (ex.: TAVILY_API_KEY);
    3. o valor daqui.

Para rotacionar uma chave: edite aqui e gere um build novo. Como o valor não é
gravado no banco de cada usuário, todo mundo passa a usar a nova no próximo
update.
"""

# Busca web do Account Planning, Mapeamento de Ambiente e insights de campanha.
TAVILY_API_KEY = ''
