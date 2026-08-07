# -*- coding: utf-8 -*-
"""Prompt de extração e parsing da resposta da IA para o formato canônico
consumido por `reconcile()`. Sem Flask, sem SQLite, sem rede. Task 3 do
plano iAta."""

import itertools
import json
import re

from .reconcile import GERENTE_NAO_IDENTIFICADO

# Tamanho máximo da transcrição embutida no prompt de extração — protege
# contra reuniões gigantes estourando o limite de contexto do template SAI.
MAX_TRANSCRICAO_CHARS = 30000


def build_extraction_prompt(raw_text):
    """Monta o prompt enviado à IA para extrair a hierarquia Gerente → Conta
    → Oportunidade da transcrição bruta da reunião."""
    return (
        "Você é um analista comercial. Leia a transcrição de uma reunião de pipeline "
        "e extraia a estrutura Gerente Comercial → Conta → Oportunidade.\n"
        "Retorne EXCLUSIVAMENTE um objeto JSON válido, sem markdown, sem comentários:\n"
        '{"title":"Título da reunião",'
        '"meeting_date":"DD/MM/AAAA ou null","meeting_time":"HH:MM ou null",'
        '"topic":"Tema central em uma frase",'
        '"participants":[{"name":"Nome","role":"Cargo/empresa se mencionado"}],'
        '"managers":[{"name":"Nome do gerente comercial",'
        '"accounts":[{"name":"Nome da conta/cliente",'
        '"opportunities":[{"name":"Nome da oportunidade",'
        '"update":"O que foi dito sobre ela NESTA reunião",'
        '"responsible":"Quem ficou responsável pela ação"}]}]}]}\n'
        "REGRAS OBRIGATÓRIAS:\n"
        "- Um gerente pode ter N contas; uma conta pode ter N oportunidades;\n"
        "- Se o gerente responsável por um bloco não for identificável, use "
        f'"{GERENTE_NAO_IDENTIFICADO}";\n'
        "- responsible: se ninguém for citado, deixe string vazia — o sistema "
        "atribui ao gerente do bloco;\n"
        "- update: apenas o que foi dito NESTA reunião, sem repetir histórico;\n"
        "- Não invente contas, oportunidades ou nomes que não estejam no texto;\n"
        "- Preserve nomes próprios como aparecem no texto.\n\n"
        f"TRANSCRIÇÃO DA REUNIÃO:\n{(raw_text or '')[:MAX_TRANSCRICAO_CHARS]}"
    )


def build_reparse_prompt(body_markdown):
    """Monta o prompt que converte o texto da ata (editado à mão pelo
    usuário na tela) de volta para o JSON estruturado, para a rota de
    edição do corpo (Task 9). Diferente de `build_extraction_prompt`
    (que extrai de uma transcrição bruta de reunião), aqui a entrada já é
    uma ata formatada — a instrução é para ESTRUTURAR o que já está escrito,
    não reinterpretar ou resumir."""
    return (
        "O texto abaixo é uma ata de reunião comercial editada à mão. "
        "Converta-a de volta para JSON, preservando exatamente o conteúdo escrito.\n"
        "Retorne EXCLUSIVAMENTE JSON válido:\n"
        '{"title":"Título","meeting_date":"DD/MM/AAAA ou null","meeting_time":"HH:MM ou null",'
        '"topic":"Tema","participants":[{"name":"Nome","role":""}],'
        '"managers":[{"name":"Gerente","accounts":[{"name":"Conta",'
        '"opportunities":[{"name":"Oportunidade","update":"texto do Update",'
        '"responsible":"texto do Responsável"}]}]}]}\n'
        "REGRAS:\n"
        "- Não reescreva, não resuma e não corrija o texto — apenas estruture;\n"
        "- Quando a linha da oportunidade tiver 'Nome: status', o status é o histórico "
        "anterior e NÃO deve ir para 'update';\n"
        "- Preserve a ordem em que gerentes, contas e oportunidades aparecem.\n\n"
        f"ATA:\n{(body_markdown or '')[:MAX_TRANSCRICAO_CHARS]}"
    )


# Aspas tipográficas que alguns modelos usam no lugar de aspas retas — se
# aparecerem como delimitador de string, o JSON nem chega a parsear. Trocamos
# só como tentativa de reparo (depois que o parse "normal" já falhou), nunca
# como primeira tentativa, para não alterar conteúdo legítimo à toa.
_ASPAS_CURVAS = str.maketrans({
    '\u201c': '"', '\u201d': '"', '\u2018': "'", '\u2019': "'",
})


def _strip_code_fence(raw):
    texto = str(raw or '').strip()
    if texto.startswith('```'):
        m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', texto, flags=re.IGNORECASE)
        if m:
            texto = m.group(1).strip()
    return texto


def _tentar_json(texto):
    try:
        return json.loads(texto)
    except Exception:
        return None


# Limite de posições de '{' tentadas por _raw_decode_a_partir_de — evita
# varredura quadrática (uma tentativa de parse por posição) em uma resposta
# de LLM anormalmente longa cheia de chaves soltas. O valor é folgado de
# propósito: um modelo que ecoa o schema pedido no prompt antes de responder
# já produz várias chaves soltas, e o custo medido de tentar centenas de
# posições fica na casa dos microssegundos — um cap apertado rejeitaria uma
# resposta boa, que é o erro caro aqui.
_MAX_TENTATIVAS_RAW_DECODE = 500

_decoder_json = json.JSONDecoder()


def _raw_decode_a_partir_de(texto):
    """Tenta decodificar um objeto JSON a partir de cada ocorrência de '{'
    em `texto`, na ordem em que aparecem, aceitando a primeira que resultar
    num dict válido.

    `raw_decode` (diferente de `json.loads`) para de ler assim que o objeto
    fecha e ignora qualquer coisa depois — resolve lixo DEPOIS do JSON sem
    precisar cortar a string. Tentar a partir de cada '{' (não só do
    primeiro) resolve lixo ANTES também: uma chave solta no texto explicativo
    ("Segue conforme {template} solicitado: {...json real...}") faz a
    tentativa a partir do primeiro '{' falhar, mas a tentativa seguinte, a
    partir do '{' do JSON de verdade, funciona — em vez de fazer a extração
    inteira falhar por causa de um recorte ingênuo do primeiro '{' ao
    último '}', que engoliria a chave solta como se fizesse parte do JSON.
    """
    for match in itertools.islice(re.finditer(r'\{', texto), _MAX_TENTATIVAS_RAW_DECODE):
        try:
            obj, _fim = _decoder_json.raw_decode(texto, match.start())
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _loads_tolerante(raw):
    """Extrai um objeto JSON de uma resposta de LLM, tolerando: bloco de
    código markdown (com ou sem a tag `json`), texto explicativo antes e/ou
    depois do objeto (mesmo com chaves soltas nesse texto), e aspas
    tipográficas usadas como delimitador de string. Não tenta recuperar JSON
    truncado — nesse caso devolve None (o chamador trata como falha de
    extração, não inventa dado)."""
    texto = _strip_code_fence(raw)
    if not texto:
        return None

    resultado = _tentar_json(texto)
    if resultado is not None:
        return resultado

    resultado = _raw_decode_a_partir_de(texto)
    if resultado is not None:
        return resultado

    # Última tentativa: reparo de aspas curvas sobre o texto inteiro, tanto
    # via parse direto quanto via raw_decode posição a posição (cobre aspas
    # curvas combinadas com lixo ao redor do objeto).
    reparado = texto.translate(_ASPAS_CURVAS)
    if reparado == texto:
        return None
    resultado = _tentar_json(reparado)
    if resultado is not None:
        return resultado
    return _raw_decode_a_partir_de(reparado)


def _clean_null(value):
    v = str(value or '').strip()
    return None if not v or v.lower() in ('null', 'none', 'n/a', '-') else v


def _field(d, *keys):
    """Primeiro valor não vazio dentre `keys` em `d` — usado para tolerar
    respostas que fogem do esquema em inglês pedido no prompt (o LLM às
    vezes devolve chaves em português mesmo assim: 'titulo', 'gerentes')."""
    for k in keys:
        v = d.get(k)
        if v not in (None, ''):
            return v
    return None


def _as_item_list(value, name_key='name', item_keys=()):
    """Normaliza `value` (o valor de 'managers'/'accounts'/'opportunities'
    ou similar) para uma lista de dicts.

    Tolera quatro desvios comuns de um LLM em relação ao esquema pedido:
    - um objeto único em vez de lista (`{"name": "Ana"}` em vez de
      `[{"name": "Ana"}]`) — comum quando só há um item;
    - a coleção inteira vinda como MAPA nome->objeto em vez de lista
      (`{"Ana": {...}, "Bruno": {...}}` em vez de
      `[{"name": "Ana", ...}, {"name": "Bruno", ...}]`) — igualmente
      plausível sem grammar estrita, e MUITO mais perigoso de confundir com
      o caso anterior: tratar o mapa como "um objeto único" produz UM item
      vazio/mal formado e todos os itens reais desaparecem sem nenhum
      sinal (não vira None, não loga). Distinguimos os dois formatos por
      `item_keys`: se o dict tem alguma chave de item conhecida daquele
      nível (`name`/`nome`, ou uma chave estrutural como `accounts`/
      `contas`), é item único; senão, se todos os *valores* do dict são
      eles próprios dicts, é mapa — e a chave do mapa vira o `name` de
      cada item que não tiver nome próprio, para não perder nem esse dado;
    - um item da lista sendo uma string solta em vez de objeto
      (`["Ana"]` em vez de `[{"name": "Ana"}]`) — vira `{name_key: "Ana"}`;
    - `None`/tipo inesperado — vira lista vazia, nunca lança exceção.

    Sem o tratamento de mapa, um `for x in dict` itera as CHAVES do dict
    como se fossem itens (silenciosamente descartados no
    `isinstance(x, dict)` seguinte), apagando a hierarquia inteira sem
    nenhum sinal de erro.
    """
    if value is None:
        return []
    if isinstance(value, dict):
        tem_chave_de_item = any(k in value for k in item_keys)
        eh_mapa = not tem_chave_de_item and bool(value) and all(
            isinstance(v, dict) for v in value.values())
        if eh_mapa:
            expandido = []
            for chave, item_bruto in value.items():
                item = dict(item_bruto)
                if not str(item.get(name_key) or item.get('nome') or '').strip():
                    item[name_key] = chave
                expandido.append(item)
            value = expandido
        else:
            value = [value]
    if not isinstance(value, list):
        return []
    saida = []
    for item in value:
        if isinstance(item, dict):
            saida.append(item)
        else:
            texto = str(item or '').strip()
            if texto:
                saida.append({name_key: texto})
    return saida


# Chaves cuja presença no dict sinaliza "isto é um item único", não um mapa
# nome->objeto — usadas por `_as_item_list` em cada nível da hierarquia.
_MANAGER_ITEM_KEYS = ('name', 'nome', 'accounts', 'contas')
_ACCOUNT_ITEM_KEYS = ('name', 'nome', 'opportunities', 'oportunidades')
_OPPORTUNITY_ITEM_KEYS = ('name', 'nome', 'update', 'update_text',
                          'atualizacao', 'atualização',
                          'responsible', 'responsavel', 'responsável')
_PARTICIPANT_ITEM_KEYS = ('name', 'nome', 'role', 'cargo', 'papel', 'empresa')


def _parse_participants(raw_participants):
    """
    LIMITAÇÃO CONHECIDA (aceita, não é perda de dado): quando `participants`
    vem como uma única string, o fallback abaixo separa por vírgula/ponto-e-
    vírgula/barra. Isso é correto para "Ana, Bruno", mas fragmenta em falso
    um único participante descrito como "Bruno Costa, Diretor Comercial da
    Ambev" em dois participantes — "Bruno Costa" e "Diretor Comercial da
    Ambev". Não há como distinguir os dois casos de forma confiável sem mais
    contexto (nenhuma pontuação separa "nome" de "cargo" de forma
    inequívoca), e o custo de errar é baixo — um participante espúrio na
    lista, não uma oportunidade comercial desaparecendo da ata.
    """
    saida = []
    if isinstance(raw_participants, str):
        nomes = [n.strip() for n in re.split(r'[,;/]', raw_participants) if n.strip()]
        return [{'name': n, 'role': ''} for n in nomes]
    for p in _as_item_list(raw_participants, item_keys=_PARTICIPANT_ITEM_KEYS):
        nome = str(_field(p, 'name', 'nome') or '').strip()
        papel = str(_field(p, 'role', 'cargo', 'papel', 'empresa') or '').strip()
        if nome:
            saida.append({'name': nome, 'role': papel})
    return saida


# Chaves em que provedores de LLM embrulham a resposta real. O `_llm_prompt`
# do projeto devolve o corpo HTTP do SAI SEM desembrulhar, então o que chega
# aqui costuma ser `{"answer": "```json{...ata...}```"}` e não a ata direto.
_CHAVES_ENVELOPE = ('answer', 'output', 'result', 'text', 'response',
                    'content', 'data', 'message', 'resposta')


def _desembrulhar_envelope(parsed, profundidade=0):
    """Se `parsed` for o envelope do provedor em vez da ata, devolve o objeto
    de dentro.

    Sem isto, `json.loads` casa com o envelope, `title` não existe e a
    extração inteira é descartada como "a IA não retornou uma ata utilizável"
    — com a resposta boa dentro do dicionário. Foi exatamente o que aconteceu
    em produção com o template SAI, cuja resposta vem embrulhada.
    """
    if not isinstance(parsed, dict) or profundidade > 3:
        return parsed
    if _field(parsed, 'title', 'titulo', 'título'):
        return parsed
    for chave in _CHAVES_ENVELOPE:
        valor = parsed.get(chave)
        if isinstance(valor, str) and valor.strip():
            interno = _loads_tolerante(valor)
            if isinstance(interno, dict):
                return _desembrulhar_envelope(interno, profundidade + 1)
        elif isinstance(valor, dict):
            return _desembrulhar_envelope(valor, profundidade + 1)
    return parsed


def parse_hierarchy(raw):
    """Converte a resposta bruta da IA (string) no formato canônico que
    `reconcile()` consome. Devolve `None` se a resposta não trouxer sequer um
    título — sinal de que a extração falhou (recusa, texto livre, JSON
    truncado) e não deve ser tratada como uma ata vazia válida."""
    parsed = _desembrulhar_envelope(_loads_tolerante(raw))
    if not isinstance(parsed, dict):
        return None
    titulo = str(_field(parsed, 'title', 'titulo', 'título') or '').strip()
    if not titulo:
        return None

    managers = []
    for manager in _as_item_list(_field(parsed, 'managers', 'gerentes'),
                                  item_keys=_MANAGER_ITEM_KEYS):
        contas = []
        for account in _as_item_list(_field(manager, 'accounts', 'contas'),
                                      item_keys=_ACCOUNT_ITEM_KEYS):
            # Conta sem nome não é descartada: uma extração ruidosa da IA
            # ainda pode ter capturado update/responsável reais para uma
            # oportunidade real — jogar o bloco inteiro fora (em vez de
            # manter com name vazio, como reconcile() já faz para o lado
            # "anterior") apagaria negócio comercial da ata sem aviso.
            nome_conta = str(_field(account, 'name', 'nome') or '').strip()
            opps = []
            for opp in _as_item_list(_field(account, 'opportunities', 'oportunidades'),
                                      item_keys=_OPPORTUNITY_ITEM_KEYS):
                opps.append({
                    'name': str(_field(opp, 'name', 'nome') or '').strip(),
                    'update_text': str(_field(opp, 'update', 'update_text', 'atualizacao',
                                               'atualização') or '').strip(),
                    'responsible': str(_field(opp, 'responsible', 'responsavel',
                                               'responsável') or '').strip(),
                })
            contas.append({'name': nome_conta, 'account_id': None,
                           'match_confidence': None, 'opportunities': opps})
        managers.append({
            'name': str(_field(manager, 'name', 'nome') or '').strip() or GERENTE_NAO_IDENTIFICADO,
            'accounts': contas,
        })

    return {
        'header': {
            'title': titulo,
            'meeting_date': _clean_null(_field(parsed, 'meeting_date', 'data_reuniao', 'data')),
            'meeting_time': _clean_null(_field(parsed, 'meeting_time', 'horario', 'horário', 'hora')),
            'topic': str(_field(parsed, 'topic', 'tema') or '').strip() or titulo,
            'participants': _parse_participants(_field(parsed, 'participants', 'participantes')),
        },
        'managers': managers,
    }
