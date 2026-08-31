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

    termos = set(_wiki_tokens(question))
    if not termos:
        return []

    blocos = []
    for src in sources or []:
        label = (src.get('label') or 'documento')
        for chunk in _wiki_split_chunks(src.get('text')):
            blocos.append({'label': label, 'chunk': chunk, 'tokens': set(_wiki_tokens(chunk))})
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
            falhas = []

            # `onexc` (Python 3.12+; este ambiente roda 3.14) recebe a exceção
            # já instanciada — mais direto de logar do que o `onerror` legado,
            # que recebe exc_info como tupla (function, path, excinfo).
            def _wiki_cap_rmtree_onexc(func, caminho, exc):
                falhas.append((caminho, exc))

            shutil.rmtree(pasta, onexc=_wiki_cap_rmtree_onexc)
            if falhas:
                primeiro_caminho, primeiro_erro = falhas[0]
                logger.warning(
                    f'[WikiToca] Capacitação id={session_id}: {len(falhas)} item(ns) da '
                    f'pasta {pasta} não puderam ser removidos do disco (os registros do '
                    f'banco já foram excluídos) — primeiro: {primeiro_caminho} ({primeiro_erro})'
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
