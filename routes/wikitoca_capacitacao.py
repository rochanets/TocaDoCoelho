# -*- coding: utf-8 -*-
# Rotas do submódulo "Capacitação" do WikiToca (sessões, mensagens, documentos
# de treino e chamadas de LLM com barra de progresso).
# Este arquivo é executado no namespace de app.py por _load_route_modules(),
# depois de routes/wikitoca.py: tem acesso a todos os helpers/globals de
# app.py (incluindo `_wiki_norm`, definida lá) e registra as rotas no mesmo
# objeto Flask `app`, com URLs idênticas às originais.

import math

# Palavras curtas e conectivos não distinguem trecho relevante de irrelevante.
# Cobre português e inglês: material de capacitação técnico em inglês é
# plausível neste projeto, e sem as function words em inglês o ranking erra
# em acervos pequenos — ex.: "how can you set the retry policy for when a
# request fails" contava how/can/you/for/when como termos de conteúdo e um
# FAQ de ruído vencia o documento que realmente respondia.
_WIKI_STOPWORDS = {
    # Português: artigos, pronomes, preposições, interrogativos, conectivos.
    'a', 'ao', 'aos', 'as', 'com', 'como', 'da', 'das', 'de', 'do', 'dos', 'e', 'em',
    'na', 'nas', 'no', 'nos', 'o', 'os', 'ou', 'para', 'pela', 'pelo', 'por', 'qual',
    'quais', 'que', 'quem', 'se', 'sobre', 'um', 'uma',
    # Inglês: artigos/demonstrativos, pronomes, auxiliares/modais, preposições,
    # interrogativos comuns.
    'the', 'this', 'that', 'these', 'those',
    'you', 'your', 'she', 'her', 'him', 'his', 'its', 'they', 'them', 'their',
    'who', 'whom', 'whose', 'what', 'which',
    'are', 'was', 'were', 'has', 'had', 'have', 'can', 'could', 'will', 'would',
    'should', 'does', 'did', 'been', 'being',
    'for', 'with', 'from', 'into', 'about', 'after', 'before', 'between',
    'during', 'over', 'under', 'without', 'and', 'of', 'to',
    'how', 'when', 'where', 'why',
}

_WIKI_CHUNK_SIZE = 1200
_WIKI_CHUNK_OVERLAP = 150
_WIKI_MIN_CHUNK_SCORE = 1.0


def _wiki_tokens(texto):
    """Termos significativos de um texto, normalizados.

    `_wiki_norm` (definida em routes/wikitoca.py, disponível aqui pelo namespace
    compartilhado) já derruba acento, caixa e caracteres de formatação, então o
    split por `[^a-z0-9]+` basta.
    """
    brutos = re.split(r'[^a-z0-9]+', _wiki_norm(texto))
    return [t for t in brutos if len(t) >= 3 and t not in _WIKI_STOPWORDS]


def _wiki_split_chunks(texto):
    """Quebra o texto em blocos com sobreposição. A sobreposição não evita que
    uma frase seja cortada ao meio (qualquer corte fixo por tamanho pode cair
    no meio de uma frase) — ela garante que frases menores que o tamanho da
    sobreposição sobrevivam íntegras em pelo menos um bloco."""
    texto = (texto or '').strip()
    if not texto:
        return []
    if len(texto) <= _WIKI_CHUNK_SIZE:
        return [texto]
    blocos = []
    passo = _WIKI_CHUNK_SIZE - _WIKI_CHUNK_OVERLAP
    for ini in range(0, len(texto), passo):
        # Sem essa guarda, a última iteração pode gerar uma cauda minúscula
        # (ex.: 38 caracteres) que é puro substring do bloco anterior — o
        # bloco anterior, terminando em ini_anterior + _WIKI_CHUNK_SIZE =
        # ini + _WIKI_CHUNK_OVERLAP, já cobre tudo que sobra quando o restante
        # do texto é <= à sobreposição. `ini and` preserva a primeira janela
        # (ini=0), que sempre deve ser gerada mesmo em texto curto.
        if ini and len(texto) - ini <= _WIKI_CHUNK_OVERLAP:
            break
        bloco = texto[ini:ini + _WIKI_CHUNK_SIZE].strip()
        if bloco:
            blocos.append(bloco)
    return blocos


def _wiki_build_blocks(sources):
    """Quebra as fontes em blocos já tokenizados: [{'label', 'chunk', 'tokens'}].

    Separado de `_wiki_rank_blocks` porque esta é a metade CARA e a única que
    não depende da pergunta — medido na Task 5, com 50 documentos de 100 KB
    (4.800 blocos) o ranking inteiro leva ~1,66 s, dos quais ~1,63 s são
    tokenização. Sendo independente da pergunta, o resultado dá para memoizar
    entre mensagens de chat (ver `_wiki_cap_base_blocks`).

    `sources` é uma lista de {'label': str, 'text': str}.
    """
    blocos = []
    for src in sources or []:
        label = (src.get('label') or 'documento')
        for chunk in _wiki_split_chunks(src.get('text')):
            blocos.append({'label': label, 'chunk': chunk, 'tokens': set(_wiki_tokens(chunk))})
    return blocos


def _wiki_rank_chunks(sources, question, top_n=6, min_score=_WIKI_MIN_CHUNK_SCORE):
    """Seleciona os trechos mais relevantes para a pergunta.

    `sources` é uma lista de {'label': str, 'text': str}. Cada termo distinto da
    pergunta presente no bloco vale 1 ponto, mais um bônus pela raridade do termo
    no conjunto (um termo presente em quase todo bloco distingue pouco). O piso
    de 1 ponto por termo é o que faz `min_score=1.0` significar "casou pelo menos
    um termo significativo": só com o bônus de raridade, um conjunto de poucos
    blocos daria pontuação abaixo de 1 mesmo para o bloco certo.

    O bônus de raridade (IDF) é calculado só a partir dos blocos desta chamada
    — então scores NÃO são comparáveis entre chamadas com acervos de tamanhos
    diferentes: o mesmo match perfeito vale mais pontos num acervo de milhares
    de blocos do que num acervo de um único bloco. Qualquer limiar absoluto
    introduzido depois (ex.: na cascata) precisa levar isso em conta.

    `top_n` é o número de blocos desejado, não um teto opcional: valores < 1
    são erro de programação do chamador (não "nenhum resultado") e levantam
    ValueError, para não se confundir com o [] que sinaliza "nada relevante".

    Devolve [{'label', 'chunk', 'score'}] ordenado por score decrescente, sem
    conteúdo duplicado (a sobreposição de _wiki_split_chunks pode gerar o
    mesmo texto em blocos diferentes; aqui só o de maior score de cada
    conteúdo distinto entra no resultado), ou [] se nenhum bloco atingir
    `min_score` — o chamador usa isso para pular o passo da cascata sem gastar
    chamada de LLM.
    """
    if top_n < 1:
        raise ValueError(f'top_n deve ser >= 1, recebido {top_n!r}')
    # A checagem de top_n acontece ANTES de tokenizar (erro de programação do
    # chamador não deve pagar 1,6 s de tokenização para depois estourar).
    return _wiki_rank_blocks(_wiki_build_blocks(sources), question, top_n, min_score)


def _wiki_rank_blocks(blocos, question, top_n=6, min_score=_WIKI_MIN_CHUNK_SCORE):
    """Pontua blocos já tokenizados por `_wiki_build_blocks`. Mesmo contrato de
    `_wiki_rank_chunks` (ver docstring acima), só que recebendo blocos prontos —
    é o que permite reaproveitar a tokenização memoizada do acervo."""
    if top_n < 1:
        raise ValueError(f'top_n deve ser >= 1, recebido {top_n!r}')

    termos = set(_wiki_tokens(question))
    if not termos:
        return []

    blocos = blocos or []
    if not blocos:
        return []

    total = len(blocos)
    freq = {t: sum(1 for b in blocos if t in b['tokens']) for t in termos}

    pontuados = []
    for b in blocos:
        score = 0.0
        for t in termos:
            if t in b['tokens']:
                # 1 ponto por termo casado + bônus de raridade. Os +1 evitam
                # divisão por zero e amortecem termos onipresentes.
                score += 1.0 + math.log(1 + total / (1 + freq[t]))
        if score >= min_score:
            pontuados.append({'label': b['label'], 'chunk': b['chunk'], 'score': round(score, 4)})

    pontuados.sort(key=lambda x: x['score'], reverse=True)

    # Dedup por conteúdo na seleção final, não na geração dos blocos (a
    # sobreposição continua intencional): sem isso, um documento repetitivo
    # pode devolver o mesmo trecho várias vezes e esgotar o orçamento de
    # contexto do LLM em texto duplicado — cenário provável na Task 8, onde o
    # mesmo documento pode chegar por duas fontes (instância + base WikiToca).
    selecionados = []
    vistos = set()
    for p in pontuados:
        if p['chunk'] in vistos:
            continue
        vistos.add(p['chunk'])
        selecionados.append(p)
        if len(selecionados) >= top_n:
            break
    return selecionados


# ═══════════════════════════════════════════════════════════════════════════
# CAPACITAÇÃO — instâncias com documentos próprios e chat com IA sobre eles.
# Isolado do resto: estes documentos não entram no submódulo Documentos nem na
# base do iToca.
# ═══════════════════════════════════════════════════════════════════════════

_WIKI_CAP_DEFAULT_TITLE = 'Nova capacitação'

# ───────────────────────────────────────────────────────────────────────────
# NÚCLEO PURO da cascata de resposta — sem Flask, sem banco, sem rede.
# Tudo neste bloco é entrada→saída e é testado chamando a função direto (ver
# tests/test_wikitoca.py). Motivo prático: a revisão da Task 7 mediu 23
# segundos para testar 12 variações de limpeza de título por HTTP (POST
# multipart + thread + polling), quando a função pura equivalente roda em
# milissegundos. A lógica de valor desta task (montagem de contexto, detecção
# do sinal INSUFICIENTE, formatação de histórico, texto dos prompts) mora
# aqui; o worker e o handler HTTP abaixo só orquestram.
# ───────────────────────────────────────────────────────────────────────────

_WIKI_CAP_MAX_CONTEXT_CHARS = 12000
_WIKI_CAP_HISTORY_MESSAGES = 6
# Teto do histórico inteiro (não por mensagem): nada limita o tamanho da
# pergunta do usuário nem o de uma resposta vinda da web, então seis mensagens
# sem teto conseguem estourar o contexto do modelo ANTES dos trechos — que são
# justamente a parte que responde a pergunta.
_WIKI_CAP_HISTORY_MAX_CHARS = 4000


def _wiki_cap_e_insuficiente(bruto):
    """True quando a resposta do LLM é o sinal "não achei nos trechos".

    Critério: reduzida a apenas letras (sem acento, sem caixa, sem pontuação,
    sem markdown, sem espaços), a resposta INTEIRA — ou a sua primeira linha
    não vazia — é exatamente a palavra `insuficiente`.

    Por que esse critério: o prompt pede a palavra sozinha, mas o modelo
    enfeita na prática (`**INSUFICIENTE**`, `"INSUFICIENTE"`, `Insuficiente!`,
    `INSUFICIENTE` seguido de uma justificativa na linha de baixo), e um falso
    NEGATIVO aqui é caro — joga a string literal INSUFICIENTE na tela do
    usuário como se fosse a resposta. Do outro lado, procurar a palavra em
    qualquer posição do texto daria falso POSITIVO em resposta legítima que só
    a contém ("O saldo é insuficiente para a operação"), descartando uma
    resposta boa e escalando a cascata à toa. Exigir que a palavra seja a
    TOTALIDADE do texto — ou da primeira linha, para cobrir o modelo que
    justifica embaixo — fica entre os dois extremos.
    """
    texto = str(bruto or '').strip()
    if not texto:
        return False
    candidatos = [texto]
    linhas = [l for l in texto.splitlines() if l.strip()]
    if linhas:
        candidatos.append(linhas[0])
    return any(re.sub(r'[^a-z]', '', _wiki_norm(c)) == 'insuficiente' for c in candidatos)


def _wiki_cap_monta_contexto(trechos, max_chars=_WIKI_CAP_MAX_CONTEXT_CHARS):
    """Blocos de contexto formatados para o prompt + labels de fato usados.

    Devolve ([blocos], [labels]) — os labels na ordem de aparição e sem
    repetir, porque é isso que vira `source_refs` da mensagem (o selo de origem
    da UI). Blocos que não caibam no orçamento são deixados de fora.
    """
    blocos, labels, tamanho = [], [], 0
    for t in trechos or []:
        label = (t.get('label') or 'documento')
        bloco = f'[{label}]\n{t.get("chunk") or ""}'
        if tamanho + len(bloco) > max_chars:
            if blocos:
                break
            # Primeiro bloco já acima do orçamento: TRUNCA em vez de devolver
            # contexto vazio. Contexto vazio faria o passo da cascata ser
            # pulado em silêncio — o usuário iria para a web tendo a resposta
            # no próprio documento. Hoje _WIKI_CHUNK_SIZE (1200) é uma ordem de
            # grandeza menor que o orçamento, então isto só dispara com um
            # label absurdamente longo ou um orçamento reduzido; mesmo assim,
            # "pular em silêncio" é caro o bastante para não ficar dependendo
            # de duas constantes continuarem nessa proporção.
            bloco = bloco[:max_chars]
        blocos.append(bloco)
        tamanho += len(bloco)
        if label not in labels:
            labels.append(label)
    return blocos, labels


def _wiki_cap_formata_historico(rows):
    """Prefixo de histórico para o prompt, a partir das linhas do SELECT — que
    vêm do mais NOVO para o mais antigo, e aqui são invertidas. '' quando não
    há histórico (a primeira pergunta de uma capacitação nova)."""
    rows = list(rows or [])
    if not rows:
        return ''
    linhas = [f'{"Usuário" if (r.get("role") == "user") else "Assistente"}: {r.get("content") or ""}'
              for r in reversed(rows)]
    texto = '\n'.join(linhas)
    if len(texto) > _WIKI_CAP_HISTORY_MAX_CHARS:
        # Corta pelo INÍCIO: são as mensagens mais recentes que fazem um
        # follow-up ("e isso vale para contrato de serviço?") ter sentido.
        texto = '[...]\n' + texto[-_WIKI_CAP_HISTORY_MAX_CHARS:]
    return 'Histórico recente desta conversa:\n' + texto + '\n\n'


def _wiki_cap_monta_prompt(history, blocos, question, origem_label):
    """Prompt dos passos 1 e 2: responder só a partir dos trechos, ou sinalizar
    INSUFICIENTE para a cascata escalar."""
    return (
        f'{history}'
        f'Você responde perguntas usando EXCLUSIVAMENTE os trechos abaixo, extraídos de {origem_label}.\n'
        'Se os trechos não contiverem a informação necessária para responder, '
        'responda SOMENTE a palavra INSUFICIENTE, sem mais nada.\n'
        'Caso contrário, responda em português do Brasil, de forma direta e objetiva.\n\n'
        'TRECHOS:\n' + '\n\n'.join(blocos) + f'\n\nPERGUNTA: {question}'
    )


def _wiki_cap_monta_prompt_web(history, question):
    """Prompt do passo 3: sem trechos, com busca ativa na internet."""
    return (
        f'{history}Responda em português do Brasil, de forma direta e objetiva, '
        f'usando informações atuais da internet.\n\nPERGUNTA: {question}'
    )


# ───────────────────────────────────────────────────────────────────────────
# Memoização da tokenização do acervo do WikiToca (passo 2 da cascata).
#
# Medido na Task 5: com 50 documentos de 100 KB (4.800 blocos) o ranking leva
# ~1,66 s, dos quais ~1,63 s são tokenização. O passo 1 da cascata é barato
# (poucos arquivos da instância); o passo 2 varre `wiki_entries` + TODOS os
# `wiki_documents`, e sem cache cada mensagem de chat pagaria isso antes de
# chamar o LLM.
#
# Deliberadamente NÃO segue o padrão do iToca (`_itoca_get_cached_base`,
# app.py): lá o snapshot é serializado em `app_settings` e só se atualiza numa
# ação manual de "Base Update" — pesado demais aqui e introduziria um botão
# que o spec não prevê. Aqui é dicionário de módulo + Lock, invalidado pela
# própria versão das fontes.
# ───────────────────────────────────────────────────────────────────────────

_wiki_cap_base_cache = {'version': None, 'blocks': []}
_wiki_cap_base_cache_lock = threading.Lock()


def _wiki_cap_invalida_cache_da_base():
    """Zera o cache. Em produção a invalidação acontece sozinha (pela versão
    das fontes); isto existe para os testes e para uso manual."""
    with _wiki_cap_base_cache_lock:
        _wiki_cap_base_cache['version'] = None
        _wiki_cap_base_cache['blocks'] = []


def _wiki_cap_base_version(conn):
    """Assinatura de identidade + versão de tudo que compõe a base do WikiToca.

    Inclui o caminho do banco: `DB_PATH` muda entre instâncias (TOCA_DB_PATH) e
    entre testes, e sem isso um cache montado sobre um banco serviria outro.

    Junto do timestamp de versão vai o TAMANHO de cada campo, porque
    CURRENT_TIMESTAMP do SQLite tem granularidade de segundo: duas edições da
    mesma entrada dentro do mesmo segundo gerariam `updated_at` idêntico. Com o
    tamanho, só escapa a edição que caia no mesmo segundo E preserve o
    comprimento exato de todos os campos — inalcançável pela UI, e o custo
    (uma consulta de metadados, sem ler os textos) é o que mantém o cache
    valendo a pena.
    """
    partes = [('db', str(DB_PATH))]
    for row in conn.execute(
            "SELECT id, COALESCE(updated_at, ''), LENGTH(COALESCE(title, '')), "
            "LENGTH(COALESCE(category, '')), LENGTH(COALESCE(content, '')) "
            'FROM wiki_entries ORDER BY id'):
        partes.append(('e',) + tuple(row))
    for row in conn.execute(
            "SELECT id, COALESCE(extracted_at, ''), LENGTH(COALESCE(extracted_text, '')) "
            "FROM wiki_documents WHERE extract_status='ok' ORDER BY id"):
        partes.append(('d',) + tuple(row))
    return tuple(partes)


def _wiki_cap_base_sources(conn):
    """Fontes da base do WikiToca no formato de `_wiki_build_blocks`.
    O label dos conhecimentos é prefixado ('Conhecimento: X') porque ele vai
    para `source_refs` e aparece na UI — sem o prefixo, o título de um
    conhecimento ficaria indistinguível de um nome de arquivo."""
    fontes = [{'label': f'Conhecimento: {r[0]}',
               'text': f'{r[0]}\n{r[1] or ""}\n{r[2] or ""}'}
              for r in conn.execute('SELECT title, category, content FROM wiki_entries ORDER BY id')]
    fontes += [{'label': r[0], 'text': r[1]} for r in conn.execute(
        "SELECT original_name, extracted_text FROM wiki_documents "
        "WHERE extract_status='ok' ORDER BY id")]
    return fontes


def _wiki_cap_base_blocks():
    """Blocos tokenizados da base do WikiToca, memoizados por versão das fontes.

    A lista devolvida é a MESMA do cache (sem copiar): `_wiki_rank_blocks` só
    lê os blocos e monta dicionários novos, nunca os muta. Copiar 4.800 dicts
    com set de tokens a cada mensagem desfaria parte do ganho.

    O recálculo acontece FORA do lock de propósito: são ~1,6 s de CPU no pior
    caso medido, e segurar o lock nesse intervalo travaria qualquer outra
    conversa que só quisesse LER o cache. Duas conversas simultâneas em cache
    frio podem calcular a mesma coisa em paralelo — desperdício aceitável e
    idempotente, contra um gargalo garantido.
    """
    conn = get_db()
    try:
        versao = _wiki_cap_base_version(conn)
        with _wiki_cap_base_cache_lock:
            if _wiki_cap_base_cache['version'] == versao:
                return _wiki_cap_base_cache['blocks']
        fontes = _wiki_cap_base_sources(conn)
    finally:
        conn.close()
    blocos = _wiki_build_blocks(fontes)
    with _wiki_cap_base_cache_lock:
        _wiki_cap_base_cache['version'] = versao
        _wiki_cap_base_cache['blocks'] = blocos
    logger.debug(f'[WikiToca] Tokenização da base recalculada: {len(fontes)} fonte(s), '
                 f'{len(blocos)} bloco(s).')
    return blocos


def _wiki_cap_session_row(session_id):
    """Sessão + os mesmos dois campos calculados que a listagem devolve
    (documents_count, last_message_at). Centralizado aqui para que GET, PUT
    e POST devolvam os três o mesmo shape — sem isso, um consumidor que só
    tem a resposta do PUT (ex.: renomear inline na sidebar da Task 12) não
    teria como atualizar a contagem de documentos exibida."""
    conn = get_db()
    row = dict_from_row(conn.execute('''
        SELECT s.*,
               (SELECT COUNT(*) FROM wiki_training_documents d WHERE d.session_id = s.id) AS documents_count,
               (SELECT MAX(created_at) FROM wiki_training_messages m WHERE m.session_id = s.id) AS last_message_at
        FROM wiki_training_sessions s
        WHERE s.id=?
    ''', (session_id,)).fetchone())
    conn.close()
    return row


@app.route('/api/wikitoca/capacitacao/sessions', methods=['GET'])
def list_wiki_capacitacao_sessions():
    logger.debug('[DEBUG] GET /api/wikitoca/capacitacao/sessions chamado')
    try:
        conn = get_db()
        rows = [dict_from_row(r) for r in conn.execute('''
            SELECT s.*,
                   (SELECT COUNT(*) FROM wiki_training_documents d WHERE d.session_id = s.id) AS documents_count,
                   (SELECT MAX(created_at) FROM wiki_training_messages m WHERE m.session_id = s.id) AS last_message_at
            FROM wiki_training_sessions s
            ORDER BY COALESCE(
                (SELECT MAX(created_at) FROM wiki_training_messages m WHERE m.session_id = s.id),
                s.updated_at
            ) DESC, s.id DESC
        ''').fetchall()]
        conn.close()
        return jsonify(rows)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/wikitoca/capacitacao/sessions: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_CAP_LIST_ERROR', 'Erro ao listar capacitações.', details=str(e))


@app.route('/api/wikitoca/capacitacao/sessions', methods=['POST'])
def create_wiki_capacitacao_session():
    logger.debug('[DEBUG] POST /api/wikitoca/capacitacao/sessions chamado')
    try:
        data = request.get_json(silent=True)
        # Corpo ausente vira {} (comportamento antigo); corpo presente mas de
        # tipo errado (lista, número, string solta...) também vira {} em vez
        # de estourar no .get() logo abaixo.
        if not isinstance(data, dict):
            data = {}
        titulo = data.get('title')
        # `title` pode chegar como int/dict/list num corpo JSON malformado —
        # só string tem .strip(); qualquer outro tipo é tratado como "sem
        # título" em vez de propagar AttributeError como erro 500.
        titulo = titulo.strip()[:200] if isinstance(titulo, str) else ''
        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT INTO wiki_training_sessions (title, title_source, created_at, updated_at)
                     VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                  (titulo or _WIKI_CAP_DEFAULT_TITLE, 'manual' if titulo else 'ai'))
        conn.commit()
        session_id = c.lastrowid
        conn.close()
        logger.info(f'[WikiToca] Capacitação criada id={session_id}')
        return jsonify(_wiki_cap_session_row(session_id)), 201
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/wikitoca/capacitacao/sessions: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_CAP_CREATE_ERROR', 'Erro ao criar capacitação.', details=str(e))


@app.route('/api/wikitoca/capacitacao/sessions/<int:session_id>', methods=['PUT'])
def rename_wiki_capacitacao_session(session_id):
    logger.debug(f'[DEBUG] PUT /api/wikitoca/capacitacao/sessions/{session_id} chamado')
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            data = {}
        titulo = data.get('title')
        titulo = titulo.strip()[:200] if isinstance(titulo, str) else ''
        if not titulo:
            return api_error(400, 'WIKI_CAP_TITLE_REQUIRED', 'O título é obrigatório.')
        # Sem checagem prévia de existência: o UPDATE é a própria checagem.
        # Checar antes e agir depois (check-then-act) deixa uma janela para um
        # DELETE concorrente — medido: a sessão some entre a checagem e o
        # UPDATE, o WHERE não casa nenhuma linha, e o SELECT final devolve
        # None, virando um 200 com corpo `null` (sucesso aparente para quem
        # chama). `rowcount` do próprio UPDATE é a fonte de verdade: 0 linhas
        # afetadas = a sessão não existe (mais), sem essa janela.
        conn = get_db()
        c = conn.cursor()
        c.execute('''UPDATE wiki_training_sessions
                     SET title=?, title_source='manual', updated_at=CURRENT_TIMESTAMP
                     WHERE id=?''', (titulo, session_id))
        conn.commit()
        encontrada = c.rowcount > 0
        conn.close()
        if not encontrada:
            return api_error(404, 'WIKI_CAP_NOT_FOUND', 'Capacitação não encontrada.')
        return jsonify(_wiki_cap_session_row(session_id))
    except Exception as e:
        logger.exception(f'[ERROR] PUT /api/wikitoca/capacitacao/sessions/{session_id}: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_CAP_RENAME_ERROR', 'Erro ao renomear capacitação.', details=str(e))


@app.route('/api/wikitoca/capacitacao/sessions/<int:session_id>', methods=['GET'])
def get_wiki_capacitacao_session(session_id):
    logger.debug(f'[DEBUG] GET /api/wikitoca/capacitacao/sessions/{session_id} chamado')
    try:
        sess = _wiki_cap_session_row(session_id)
        if not sess:
            return api_error(404, 'WIKI_CAP_NOT_FOUND', 'Capacitação não encontrada.')
        conn = get_db()
        docs = [dict_from_row(r) for r in conn.execute(
            '''SELECT id, session_id, file_name, original_name, file_url, file_ext,
                      file_size, extract_status, created_at
               FROM wiki_training_documents WHERE session_id=? ORDER BY id''', (session_id,)).fetchall()]
        msgs = [dict_from_row(r) for r in conn.execute(
            '''SELECT id, role, content, source_kind, source_refs, created_at
               FROM wiki_training_messages WHERE session_id=? ORDER BY created_at, id''', (session_id,)).fetchall()]
        conn.close()
        for m in msgs:
            try:
                m['source_refs'] = json.loads(m['source_refs']) if m.get('source_refs') else []
            except Exception:
                m['source_refs'] = []
        return jsonify({'session': sess, 'documents': docs, 'messages': msgs})
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/wikitoca/capacitacao/sessions/{session_id}: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_CAP_DETAIL_ERROR', 'Erro ao carregar capacitação.', details=str(e))


@app.route('/api/wikitoca/capacitacao/sessions/<int:session_id>', methods=['DELETE'])
def delete_wiki_capacitacao_session(session_id):
    logger.debug(f'[DEBUG] DELETE /api/wikitoca/capacitacao/sessions/{session_id} chamado')
    try:
        if not _wiki_cap_session_row(session_id):
            return api_error(404, 'WIKI_CAP_NOT_FOUND', 'Capacitação não encontrada.')
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM wiki_training_messages WHERE session_id=?', (session_id,))
        c.execute('DELETE FROM wiki_training_documents WHERE session_id=?', (session_id,))
        c.execute('DELETE FROM wiki_training_sessions WHERE id=?', (session_id,))
        conn.commit()
        conn.close()
        # Os arquivos ficam num diretório por instância — apagar a pasta inteira
        # evita deixar órfãos em disco. Os registros do banco já foram
        # removidos acima; se o disco falhar (arquivo com handle aberto,
        # permissão, etc.) o registro não pode ficar bloqueado por isso —
        # mas a falha também não pode ficar muda, senão o suporte fica cego
        # com órfãos em disco e o log dizendo "removida" mesmo assim.
        pasta = WIKI_TRAINING_UPLOAD_DIR / str(session_id)
        if pasta.exists():
            # As threads de indexação (Task 3 e Task 7, registradas em
            # _wiki_indexing_threads por _wiki_track_thread) mantêm o arquivo
            # aberto enquanto extraem o texto (python-docx, pdfplumber, PIL...).
            # Medido: um `rmtree` disparado enquanto uma dessas threads ainda
            # está lendo o arquivo esbarra em WinError 32 (handle aberto) — e
            # como as linhas do banco desta sessão já foram apagadas ACIMA,
            # nenhum DELETE futuro consegue mirar este session_id de novo: o
            # arquivo vira órfão permanente em disco. Dar `join` (com timeout
            # -- não travar a exclusão pra sempre se algo realmente travou,
            # ex. um OCR pendurado) dá tempo das threads fecharem os arquivos
            # antes da tentativa de remoção abaixo. A lista pode ter threads
            # de OUTRAS sessões/uploads em andamento -- join nelas também é
            # aceitável aqui (só atrasa um pouco a exclusão, não quebra nada).
            for _t in list(_wiki_indexing_threads):
                if _t.is_alive():
                    _t.join(timeout=5)
            # `rmtree` sem callback já levanta a primeira falha (PermissionError
            # com handle aberto no Windows, que é o caso real: a extração de
            # texto abre estes arquivos), e é isso que queremos logar. Nada de
            # `onexc`/`onerror`: `onexc` exige Python 3.12+ e `onerror` está
            # depreciado — o projeto não declara versão mínima em lugar nenhum,
            # e um TypeError aqui derrubaria a exclusão inteira, que é pior do
            # que o órfão em disco que estamos tentando tornar visível.
            try:
                shutil.rmtree(pasta)
            except Exception as e_disco:
                logger.warning(
                    f'[WikiToca] Capacitação id={session_id}: a pasta {pasta} não pôde ser '
                    f'removida do disco ({type(e_disco).__name__}: {e_disco}). Os registros '
                    f'do banco já foram excluídos, então há arquivos órfãos em disco.'
                )
        logger.info(f'[WikiToca] Capacitação removida id={session_id}')
        return jsonify({'success': True})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE /api/wikitoca/capacitacao/sessions/{session_id}: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_CAP_DELETE_ERROR', 'Erro ao excluir capacitação.', details=str(e))


@app.route('/api/wikitoca/capacitacao/sessions/<int:session_id>/messages', methods=['DELETE'])
def clear_wiki_capacitacao_messages(session_id):
    """Limpar conversa: apaga o histórico e mantém os documentos anexados."""
    logger.debug(f'[DEBUG] DELETE .../capacitacao/sessions/{session_id}/messages chamado')
    try:
        if not _wiki_cap_session_row(session_id):
            return api_error(404, 'WIKI_CAP_NOT_FOUND', 'Capacitação não encontrada.')
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM wiki_training_messages WHERE session_id=?', (session_id,))
        c.execute('UPDATE wiki_training_sessions SET updated_at=CURRENT_TIMESTAMP WHERE id=?', (session_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE .../capacitacao/sessions/{session_id}/messages: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_CAP_CLEAR_ERROR', 'Erro ao limpar a conversa.', details=str(e))


# `<path:filename>` (não `<filename>`) é necessário aqui porque o layout em
# disco é `<session_id>/<file_name>` — o conversor padrão do Flask não casa
# barra. Esta é a PRIMEIRA rota do projeto a usar `<path:>` (as outras quatro
# rotas de upload do WikiToca usam `<filename>`, que não aceita subdiretório).
#
# A proteção contra travessia de caminho (`../`, caminho absoluto `/etc/...`,
# drive absoluto `C:/...`) NÃO vem só do `safe_join` que o `send_from_directory`
# usa por baixo — para um `filename` começando com `/`, o `safe_join` do
# Werkzeug 2.3.7 devolve o caminho absoluto sem erro (no Python 3.13+,
# `ntpath.isabs('/x')` passou a ser False, então essa camada sozinha deixaria
# passar). Quem fecha esse buraco de verdade é o REGEX do conversor `path`
# do Werkzeug (`[^/].*?`, que exige que o primeiro caractere do segmento não
# seja `/`) combinado com o `merge_slashes` do roteamento — confirmado
# empiricamente que `//etc/passwd` nem chega a casar a rota (404 antes de
# tocar o filesystem). Ou seja: **não troque o conversor `<path:>` por algo
# "mais simples" nem faça upgrade de Werkzeug sem revalidar travessia** — é
# esse regex, não o `safe_join`, que impede o caminho absoluto de escapar.
# O teste de travessia (test_wikitoca.py) trava esse comportamento.
@app.route('/uploads/wikitoca/capacitacao/<path:filename>')
def serve_wikitoca_training_upload(filename):
    return send_from_directory(str(WIKI_TRAINING_UPLOAD_DIR), filename)


# ═══════════════════════════════════════════════════════════════════════════
# Upload de documentos + indexação em background + título gerado por IA.
# ═══════════════════════════════════════════════════════════════════════════

def _wiki_cap_clean_ai_title(bruto):
    """Limpa a resposta crua do LLM até virar um título de uma linha, ou ''
    se não sobrar nada aproveitável.

    `bruto` pode vir None (nenhum provider de LLM configurado -- `_llm_prompt`
    filtra resposta em branco no ramo padrão, mas o ramo `web=True`, usado
    pela Task 8, repassa o fallback do SAI sem filtrar, então uma resposta só
    de espaços É um caso real, não hipotético), com aspas, markdown
    (**negrito**, # cabeçalho, cercas de código ```), preâmbulo antes do
    título de verdade ('Aqui está o título:\\nX'), múltiplas linhas, ou
    centenas de caracteres. Nenhum desses formatos pode virar exceção — em
    especial `''.splitlines()` é `[]`, e pegar `[0]` direto disso é
    IndexError; monta-se a lista de linhas não vazias primeiro e só depois
    se pega a primeira, se houver alguma."""
    linhas = [l.strip() for l in (bruto or '').splitlines() if l.strip()]
    # Cerca de código (```): a linguagem/cerca em si nunca é o título.
    linhas = [l for l in linhas if not l.startswith('```')]
    if not linhas:
        return ''
    primeira = linhas[0]
    # Preâmbulo ('Aqui está o título:', 'Título sugerido:'...): quando a
    # primeira linha só introduz o que vem a seguir (termina em ':') e existe
    # uma segunda linha, o título de verdade é essa segunda linha.
    if primeira.endswith(':') and len(linhas) > 1:
        primeira = linhas[1]
    primeira = re.sub(r'^#{1,6}\s*', '', primeira).strip()  # cabeçalho markdown
    primeira = re.sub(r'^\*{1,3}(.*?)\*{1,3}$', r'\1', primeira).strip()  # **negrito**/*itálico*
    primeira = primeira.strip('"\'“”‘’').strip()
    return primeira


def _wiki_cap_generate_title(session_id):
    """Gera o título da instância a partir do primeiro documento indexado.
    Só age quando title_source ainda é 'ai' — renomear pelo usuário (PUT
    .../sessions/<id>) trava isso, e o WHERE title_source='ai' do UPDATE
    abaixo é quem garante isso mesmo se o usuário renomear NO MEIO da
    indexação (entre este SELECT e aquele UPDATE)."""
    sess = _wiki_cap_session_row(session_id)
    if not sess or (sess.get('title_source') or 'ai') != 'ai':
        return
    conn = get_db()
    row = dict_from_row(conn.execute(
        '''SELECT original_name, extracted_text FROM wiki_training_documents
           WHERE session_id=? AND extract_status='ok' ORDER BY id LIMIT 1''', (session_id,)).fetchone())
    conn.close()
    if not row or not (row.get('extracted_text') or '').strip():
        return
    trecho = (row['extracted_text'] or '')[:3000]
    bruto = _llm_prompt(
        'Você recebe o início de um documento de treinamento corporativo. '
        'Responda SOMENTE com um título curto em português do Brasil, no máximo 6 palavras, '
        'sem aspas, sem ponto final e sem nenhum texto além do título.\n\n'
        f'Arquivo: {row["original_name"]}\n\nConteúdo:\n{trecho}',
        log_tag='WikiCapacitacao'
    )
    titulo = _wiki_cap_clean_ai_title(bruto)
    if not titulo:
        logger.info(f'[WikiToca] Nenhum LLM respondeu o título da capacitação {session_id}; mantendo o padrão.')
        return
    titulo = titulo[:120]
    conn = get_db()
    c = conn.cursor()
    c.execute('''UPDATE wiki_training_sessions SET title=?, title_source='ai',
                 updated_at=CURRENT_TIMESTAMP WHERE id=? AND title_source='ai' ''', (titulo, session_id))
    conn.commit()
    conn.close()
    logger.info(f'[WikiToca] Título da capacitação {session_id} definido pela IA: {titulo}')


def _wiki_cap_index_async(task_id, session_id, doc_ids):
    """Indexa os documentos recém-enviados de uma instância e, ao final,
    tenta gerar o título pela IA a partir do primeiro documento indexado.

    Reconfere a existência da sessão antes de tocar em cada documento: se o
    usuário excluir a instância enquanto esta thread roda (`DELETE
    .../sessions/<id>` dá `rmtree` na pasta de upload e `DELETE ... CASCADE`
    nas linhas de `wiki_training_documents`), duas coisas ruins podem
    acontecer sem essa guarda — medido, não hipotético: (1) o `UPDATE` de
    `_wiki_index_document` numa linha já apagada dá `rowcount=0` em
    silêncio, sem lançar nada para o `except` genérico pegar, e a task fica
    'processing' para sempre (barra de progresso do usuário girando à toa);
    (2) se o `rmtree` da exclusão corre antes desta thread terminar de ler o
    arquivo, qualquer novo acesso à pasta a essa altura recriaria um órfão em
    disco que nenhuma exclusão futura mais alcança (o `session_id` já não
    existe para outro DELETE mirar). Parar o laço assim que a sessão some
    evita as duas coisas de uma vez: nada mais é lido/escrito na pasta, e a
    task termina de forma explícita em vez de ficar pendurada.

    'done' (não 'error') quando a sessão some no meio: a exclusão foi uma
    ação legítima do usuário, não uma falha — um status 'error' sugeriria ao
    frontend que algo quebrou e valeria a pena mostrar isso ao usuário."""
    try:
        total = len(doc_ids)
        for pos, doc_id in enumerate(doc_ids, start=1):
            if not _wiki_cap_session_row(session_id):
                logger.info(f'[WikiToca] Capacitação {session_id} excluída durante a indexação; '
                            f'encerrando a task {task_id} sem processar os documentos restantes.')
                _bg_task_set(task_id, {'status': 'done', 'step': 'Capacitação excluída.',
                                       'progress': 100, 'result': {'cancelled': True}})
                return
            conn = get_db()
            row = dict_from_row(conn.execute(
                'SELECT file_name, original_name FROM wiki_training_documents WHERE id=?',
                (doc_id,)).fetchone())
            conn.close()
            if not row:
                continue
            _bg_task_set(task_id, {
                'step': f'Lendo {pos} de {total} — {row["original_name"]}',
                'progress': int(5 + (pos - 1) * 80 / max(1, total)),
            })
            caminho = WIKI_TRAINING_UPLOAD_DIR / str(session_id) / row['file_name']
            _wiki_index_document('wiki_training_documents', doc_id, caminho)

        if not _wiki_cap_session_row(session_id):
            _bg_task_set(task_id, {'status': 'done', 'step': 'Capacitação excluída.',
                                   'progress': 100, 'result': {'cancelled': True}})
            return

        _bg_task_set(task_id, {'step': 'Definindo o título da capacitação...', 'progress': 90})
        _wiki_cap_generate_title(session_id)

        _bg_task_set(task_id, {'status': 'done', 'step': 'Concluído!', 'progress': 100,
                               'result': {'session_id': session_id}})
    except Exception as e:
        logger.exception(f'[WikiToca] _wiki_cap_index_async: {e}')
        _bg_task_set(task_id, {'status': 'error', 'error': str(e), 'progress': 100})
    finally:
        _bg_task_cleanup(task_id)


@app.route('/api/wikitoca/capacitacao/sessions/<int:session_id>/documents', methods=['POST'])
def upload_wiki_capacitacao_documents(session_id):
    logger.debug(f'[DEBUG] POST .../capacitacao/sessions/{session_id}/documents chamado')
    try:
        if not _wiki_cap_session_row(session_id):
            return api_error(404, 'WIKI_CAP_NOT_FOUND', 'Capacitação não encontrada.')
        files = request.files.getlist('files')
        if not files or all(not f.filename for f in files):
            return api_error(400, 'WIKI_CAP_NO_FILE', 'Nenhum arquivo enviado.')

        pasta = WIKI_TRAINING_UPLOAD_DIR / str(session_id)
        conn = get_db()
        c = conn.cursor()
        created = []
        arquivos_gravados = []
        try:
            for f in files:
                if not f.filename:
                    continue
                ext = Path(f.filename).suffix.lower()
                if ext not in ALLOWED_WIKI_TRAINING_EXTENSIONS:
                    logger.warning(f'[WikiToca] Extensão rejeitada na capacitação: {ext}')
                    continue
                original_name = f.filename
                # uuid no nome (não só o timestamp em segundos): dois arquivos
                # enviados no mesmo request podem cair no mesmo segundo -- caso
                # realista em upload múltiplo -- e sem isso o segundo sobrescreve
                # o primeiro em disco, deixando duas linhas no banco apontando
                # para o mesmo arquivo físico.
                safe_name = secure_filename(
                    f'cap_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}_{original_name}')
                # Trunca preservando a extensão: um nome de arquivo enviado pelo
                # usuário pode passar de 150-200 caracteres (raro, mas real --
                # tests/conftest.py documenta uma falha de suíte causada por
                # exatamente essa classe de nome estourando o limite de caminho
                # do Windows). O caminho completo já soma o diretório de uploads
                # + o id da sessão antes do nome do arquivo, então 150 aqui é
                # generoso o bastante sem se aproximar do MAX_PATH de 260.
                if len(safe_name) > 150:
                    manter = max(150 - len(ext), 1)
                    safe_name = safe_name[:manter].rstrip('_') + ext

                # A pasta só nasce quando o primeiro arquivo aceito chega -- um
                # lote 100% rejeitado (ex.: só .xlsx numa capacitação que só
                # aceita PDF/DOC/DOCX/PNG/JPG) não pode deixar uma pasta vazia
                # para trás.
                if not pasta.exists():
                    pasta.mkdir(parents=True, exist_ok=True)
                save_path = pasta / safe_name
                f.save(str(save_path))
                arquivos_gravados.append(save_path)

                try:
                    c.execute(
                        '''INSERT INTO wiki_training_documents
                           (session_id, file_name, original_name, file_url, file_ext, file_size,
                            extract_status, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP)''',
                        (session_id, safe_name, original_name,
                         f'/uploads/wikitoca/capacitacao/{session_id}/{safe_name}',
                         ext, save_path.stat().st_size)
                    )
                    conn.commit()
                except sqlite3.IntegrityError:
                    # Check-then-act: a checagem de existência no topo desta
                    # rota passou, mas um DELETE concorrente pode excluir a
                    # sessão em qualquer ponto do loop de gravação (que num
                    # lote grande dura segundos) -- mesmo raciocínio do PUT de
                    # renomear (Task 6: "o UPDATE é a própria checagem"), só
                    # que aqui o INSERT tem FK (PRAGMA foreign_keys=ON) contra
                    # um session_id que acabou de sumir. Sem isto, o
                    # IntegrityError virava 500 com a mensagem crua do SQLite
                    # e os arquivos já gravados neste request ficavam órfãos
                    # em disco (a sessão já não existe pra nenhum DELETE
                    # futuro limpar). Limpa o que este request gravou e
                    # devolve 404, como se a capacitação nunca tivesse
                    # existido — que é exatamente o que virou verdade.
                    logger.warning(
                        f'[WikiToca] Capacitação {session_id} excluída durante o upload; '
                        f'descartando {len(arquivos_gravados)} arquivo(s) já gravados neste request.'
                    )
                    for gravado in arquivos_gravados:
                        try:
                            gravado.unlink(missing_ok=True)
                        except Exception as e_limpeza:
                            logger.warning(f'[WikiToca] Falha ao limpar {gravado} após corrida de '
                                           f'exclusão: {e_limpeza}')
                    try:
                        if pasta.exists() and not any(pasta.iterdir()):
                            pasta.rmdir()
                    except Exception as e_limpeza:
                        logger.warning(f'[WikiToca] Falha ao remover pasta {pasta} vazia após corrida '
                                       f'de exclusão: {e_limpeza}')
                    return api_error(404, 'WIKI_CAP_NOT_FOUND', 'Capacitação não encontrada.')

                created.append(dict_from_row(c.execute(
                    'SELECT id, session_id, file_name, original_name, file_url, file_ext, '
                    'file_size, extract_status, created_at FROM wiki_training_documents WHERE id=?',
                    (c.lastrowid,)).fetchone()))
        finally:
            conn.close()

        if not created:
            return api_error(400, 'WIKI_CAP_INVALID_TYPE',
                             'Nenhum arquivo válido enviado. Tipos aceitos: PDF, DOC, DOCX, PNG, JPG.')

        task_id = uuid.uuid4().hex
        _bg_task_register_persistent(task_id, 'wiki_indexacao')
        _bg_task_set(task_id, {'status': 'processing', 'step': 'Enviando arquivos...', 'progress': 5})
        thread = threading.Thread(target=_wiki_cap_index_async,
                                  args=(task_id, session_id, [d['id'] for d in created]), daemon=True)
        _wiki_track_thread(thread)
        thread.start()
        return jsonify({'documents': created, 'task_id': task_id}), 202
    except Exception as e:
        logger.exception(f'[ERROR] POST .../capacitacao/sessions/{session_id}/documents: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_CAP_UPLOAD_ERROR', 'Erro ao enviar documentos.', details=str(e))


@app.route('/api/wikitoca/capacitacao/documents/<int:document_id>', methods=['DELETE'])
def delete_wiki_capacitacao_document(document_id):
    logger.debug(f'[DEBUG] DELETE .../capacitacao/documents/{document_id} chamado')
    try:
        conn = get_db()
        c = conn.cursor()
        row = dict_from_row(c.execute(
            'SELECT session_id, file_name FROM wiki_training_documents WHERE id=?', (document_id,)).fetchone())
        if not row:
            conn.close()
            return api_error(404, 'WIKI_CAP_DOC_NOT_FOUND', 'Documento não encontrado.')
        c.execute('DELETE FROM wiki_training_documents WHERE id=?', (document_id,))
        conn.commit()
        conn.close()
        caminho = WIKI_TRAINING_UPLOAD_DIR / str(row['session_id']) / row['file_name']
        # Mesmo padrão do DELETE da instância (Task 6): a linha do banco já
        # foi apagada e commitada acima -- se o disco falhar agora (handle
        # aberto por uma extração em andamento, antivírus varrendo o
        # arquivo...) o usuário não pode ver um 500 depois que a exclusão já
        # aconteceu de verdade. Loga como órfão em disco, não engole em
        # silêncio.
        try:
            if caminho.exists():
                caminho.unlink()
        except Exception as e_disco:
            logger.warning(
                f'[WikiToca] Documento id={document_id}: o arquivo {caminho} não pôde ser removido '
                f'do disco ({type(e_disco).__name__}: {e_disco}). O registro do banco já foi excluído, '
                f'então há um arquivo órfão em disco.'
            )
        return jsonify({'success': True})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE .../capacitacao/documents/{document_id}: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_CAP_DOC_DELETE_ERROR', 'Erro ao excluir documento.', details=str(e))


# ═══════════════════════════════════════════════════════════════════════════
# Chat: cascata de resposta — documentos da instância → base WikiToca → web.
# O núcleo puro (prompts, contexto, sinal de INSUFICIENTE, cache do acervo)
# está no topo deste arquivo; daqui para baixo é só orquestração.
# ═══════════════════════════════════════════════════════════════════════════

def _wiki_cap_history_rows(session_id, before_id):
    """Últimas mensagens da instância (mais nova primeiro), EXCLUINDO a
    mensagem de id >= `before_id`.

    O filtro por id não é detalhe: a rota grava a pergunta do usuário ANTES de
    disparar a thread (para a UI já poder mostrar a bolha e para a mensagem
    sobreviver a um refresh). Sem excluí-la, a pergunta atual entraria no
    prompt duas vezes — uma como `Usuário: X` no histórico e outra como
    `PERGUNTA: X` no fim —, desperdiçando contexto e confundindo o modelo.
    routes/itoca.py resolve o mesmo problema buscando o histórico antes de
    salvar; aqui a ordem é necessariamente invertida (a thread nasce depois do
    INSERT), então o equivalente é filtrar por id."""
    conn = get_db()
    rows = [dict_from_row(r) for r in conn.execute(
        '''SELECT role, content FROM wiki_training_messages
           WHERE session_id=? AND id < ?
           ORDER BY created_at DESC, id DESC LIMIT ?''',
        (session_id, before_id, _WIKI_CAP_HISTORY_MESSAGES)).fetchall()]
    conn.close()
    return rows


def _wiki_cap_ask_llm(trechos, question, history, origem_label):
    """Monta o prompt com os trechos selecionados e chama o LLM.

    Devolve (status, resposta, labels), com status em:
      'answer'       — o modelo respondeu de fato (resposta e labels preenchidos);
      'insufficient' — o modelo respondeu, mas disse que os trechos não bastam;
      'no_context'   — não havia trecho para mandar; nem chamou o LLM;
      'no_provider'  — chamou, e nenhum provider de IA respondeu (SAI e
                       OpenRouter indisponíveis).

    Separar 'insufficient' de 'no_provider' é o que permite ao worker não
    mentir na mensagem final — ver a decisão em `_wiki_cap_answer_async`.
    """
    blocos, labels = _wiki_cap_monta_contexto(trechos)
    if not blocos:
        return 'no_context', None, []
    bruto = _llm_prompt(_wiki_cap_monta_prompt(history, blocos, question, origem_label),
                        log_tag='WikiCapacitacao')
    if not bruto or not str(bruto).strip():
        return 'no_provider', None, []
    resposta = str(bruto).strip()
    if _wiki_cap_e_insuficiente(resposta):
        return 'insufficient', None, []
    return 'answer', resposta, labels


def _wiki_cap_answer_async(task_id, session_id, question, user_message_id):
    """Roda a cascata e grava a resposta com a origem que a UI mostra como selo.

    Sobre o corte por score: `_wiki_rank_chunks`/`_wiki_rank_blocks` devolvem []
    quando as fontes não têm NENHUM termo significativo em comum com a
    pergunta, e é só isso que faz um passo ser pulado sem gastar chamada de
    LLM. Quem julga relevância de verdade é o INSUFICIENTE da IA, não a
    pontuação — deliberado: um falso positivo custa uma chamada de LLM, um
    falso negativo mandaria o usuário para a web tendo a resposta nos próprios
    documentos.
    """
    try:
        history = _wiki_cap_formata_historico(_wiki_cap_history_rows(session_id, user_message_id))
        resposta, refs, origem = None, [], None
        # Um status por passo que chegou a chamar o LLM. É o que permite, na
        # decisão final, distinguir "nenhum provider respondeu" (erro de
        # integração) de "os providers responderam que não sabem" (resposta
        # legítima). O código de referência do plano usava um único
        # `houve_llm = True` marcado incondicionalmente no passo 3, o que
        # tornava o ramo "não encontrei" código morto e fazia o usuário receber
        # "verifique as chaves em Configurações" mesmo quando as chaves estavam
        # certas e o modelo só não sabia a resposta.
        status_dos_passos = []

        # ── Passo 1: documentos desta capacitação ──────────────────────────
        _bg_task_set(task_id, {'step': 'Consultando os documentos desta capacitação...', 'progress': 20})
        conn = get_db()
        docs = [dict_from_row(r) for r in conn.execute(
            '''SELECT original_name, extracted_text FROM wiki_training_documents
               WHERE session_id=? AND extract_status='ok' ORDER BY id''', (session_id,)).fetchall()]
        conn.close()
        # Sem memoização aqui, de propósito: são poucos arquivos por instância
        # (o custo medido que motivou o cache está no acervo do passo 2), e
        # cachear por instância significaria mais um mapa para invalidar a cada
        # upload/exclusão de documento da capacitação.
        trechos = _wiki_rank_chunks(
            [{'label': d['original_name'], 'text': d['extracted_text']} for d in docs], question)
        if trechos:
            status, resposta, refs = _wiki_cap_ask_llm(
                trechos, question, history, 'documentos anexados a esta capacitação')
            status_dos_passos.append(status)
            if resposta:
                origem = 'documents'

        # ── Passo 2: base do WikiToca (conhecimentos + documentos) ─────────
        if not resposta:
            _bg_task_set(task_id, {'step': 'Consultando a base do WikiToca...', 'progress': 50})
            trechos = _wiki_rank_blocks(_wiki_cap_base_blocks(), question)
            if trechos:
                status, resposta, refs = _wiki_cap_ask_llm(
                    trechos, question, history, 'a base de conhecimento do WikiToca')
                status_dos_passos.append(status)
                if resposta:
                    origem = 'wiki'

        # ── Passo 3: web ───────────────────────────────────────────────────
        if not resposta:
            _bg_task_set(task_id, {'step': 'Pesquisando na web...', 'progress': 75})
            bruto = _llm_prompt(_wiki_cap_monta_prompt_web(history, question),
                                log_tag='WikiCapacitacao', web=True)
            if bruto and str(bruto).strip():
                status_dos_passos.append('answer')
                resposta, refs, origem = str(bruto).strip(), [], 'web'
            else:
                status_dos_passos.append('no_provider')

        if not resposta:
            if not any(s in ('answer', 'insufficient') for s in status_dos_passos):
                # Nenhum provider devolveu conteúdo em NENHUM passo: isto é
                # falha de integração, e é a única situação em que faz sentido
                # mandar o usuário conferir as chaves.
                _bg_task_set(task_id, {
                    'status': 'error', 'progress': 100,
                    'error': ('Nenhuma integração de IA respondeu (SAI e OpenRouter indisponíveis). '
                              'Verifique as chaves em Configurações.')})
                return
            # Os providers responderam — só não havia a informação. Resposta
            # legítima, não erro. `source_kind='none'` em vez de 'web': marcar
            # como 'web' faria a UI acender um selo de "resposta da internet"
            # numa mensagem que diz exatamente o contrário.
            resposta = ('Não encontrei essa informação nos documentos desta capacitação, '
                        'na base do WikiToca nem na web.')
            refs, origem = [], 'none'

        # Corrida tratada: o usuário pode excluir a capacitação enquanto a
        # cascata roda (ela dura segundos, com até três chamadas de LLM). O
        # INSERT bateria na FK (PRAGMA foreign_keys=ON) e, sem tratamento, a
        # task ficaria pendurada ou terminaria em erro — a barra de progresso
        # não pode girar para sempre, e a exclusão foi uma ação legítima do
        # usuário, não uma falha (mesma decisão do `_wiki_cap_index_async`:
        # termina em 'done' com `cancelled`). O IntegrityError é a checagem, e
        # não um `if` antes dele, para não deixar janela de check-then-act
        # (lição do PUT da Task 6: "o UPDATE é a própria checagem").
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute('''INSERT INTO wiki_training_messages
                         (session_id, role, content, source_kind, source_refs, created_at)
                         VALUES (?, 'assistant', ?, ?, ?, CURRENT_TIMESTAMP)''',
                      (session_id, resposta, origem, json.dumps(refs, ensure_ascii=False)))
            c.execute('UPDATE wiki_training_sessions SET updated_at=CURRENT_TIMESTAMP WHERE id=?',
                      (session_id,))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            logger.info(f'[WikiToca] Capacitação {session_id} excluída durante a resposta; '
                        f'encerrando a task {task_id} sem gravar a mensagem.')
            _bg_task_set(task_id, {'status': 'done', 'step': 'Capacitação excluída.',
                                   'progress': 100, 'result': {'cancelled': True}})
            return
        finally:
            conn.close()

        logger.info(f'[WikiToca] Capacitação {session_id} respondeu via "{origem}" (refs={refs})')
        _bg_task_set(task_id, {'status': 'done', 'step': 'Concluído!', 'progress': 100,
                               'result': {'answer': resposta, 'source_kind': origem, 'source_refs': refs}})
    except Exception as e:
        logger.exception(f'[WikiToca] _wiki_cap_answer_async: {e}')
        _bg_task_set(task_id, {'status': 'error', 'error': str(e), 'progress': 100})
    finally:
        _bg_task_cleanup(task_id)


@app.route('/api/wikitoca/capacitacao/sessions/<int:session_id>/ask', methods=['POST'])
def ask_wiki_capacitacao(session_id):
    logger.debug(f'[DEBUG] POST .../capacitacao/sessions/{session_id}/ask chamado')
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            data = {}
        question = data.get('question')
        # Mesma defesa do POST/PUT de sessões: `question` pode chegar como
        # int/dict/list num corpo malformado, e só string tem .strip().
        question = question.strip() if isinstance(question, str) else ''
        if not question:
            return api_error(400, 'WIKI_CAP_QUESTION_REQUIRED', 'A pergunta é obrigatória.')
        if not _wiki_cap_session_row(session_id):
            return api_error(404, 'WIKI_CAP_NOT_FOUND', 'Capacitação não encontrada.')

        conn = get_db()
        try:
            c = conn.cursor()
            c.execute('''INSERT INTO wiki_training_messages (session_id, role, content, created_at)
                         VALUES (?, 'user', ?, CURRENT_TIMESTAMP)''', (session_id, question))
            conn.commit()
            user_message_id = c.lastrowid
        except sqlite3.IntegrityError:
            # DELETE concorrente entre a checagem acima e este INSERT — mesmo
            # padrão da rota de upload (Task 7).
            conn.rollback()
            return api_error(404, 'WIKI_CAP_NOT_FOUND', 'Capacitação não encontrada.')
        finally:
            conn.close()

        task_id = uuid.uuid4().hex
        _bg_task_register_persistent(task_id, 'wiki_capacitacao_ask')
        _bg_task_set(task_id, {'status': 'processing', 'step': 'Iniciando...', 'progress': 5})
        thread = threading.Thread(target=_wiki_cap_answer_async,
                                  args=(task_id, session_id, question, user_message_id), daemon=True)
        # Sem o track, uma thread ainda viva quando um teste falha sobrevive ao
        # teardown do monkeypatch de DB_PATH e grava no banco REAL do usuário
        # (ver tests/conftest.py).
        _wiki_track_thread(thread)
        thread.start()
        return jsonify({'task_id': task_id}), 202
    except Exception as e:
        logger.exception(f'[ERROR] POST .../capacitacao/sessions/{session_id}/ask: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_CAP_ASK_ERROR', 'Erro ao processar a pergunta.', details=str(e))
