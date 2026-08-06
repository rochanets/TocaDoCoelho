# -*- coding: utf-8 -*-
# Rotas do iAta dentro do AutoToca.
# Este arquivo é executado no namespace de app.py por _load_route_modules():
# tem acesso a get_db, logger, json, dict_from_row e afins.

from integrations import iata as iata_lib


def _iata_save_record(header, managers, extras, raw_text, previous_record_id,
                      body_markdown=None):
    """Grava a ata e a hierarquia. Devolve o id do registro.

    Uma única conexão/transação cobre o INSERT em iata_records e a escrita
    da hierarquia: se `_iata_write_hierarchy` levantar no meio, nada foi
    commitado ainda, e fechar a conexão sem commit descarta o INSERT também
    — não sobra um registro órfão sem hierarquia.
    """
    header = header or {}
    body = body_markdown or iata_lib.render_markdown(header, managers, extras)
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            '''INSERT INTO iata_records
               (title, meeting_date, meeting_time, topic, participants, ata_json,
                insights_json, raw_text, previous_record_id, body_markdown,
                body_edited, reparse_failed, format_version)
               VALUES (?,?,?,?,?,?,?,?,?,?,0,0,2)''',
            (header.get('title') or 'Ata sem título',
             header.get('meeting_date'), header.get('meeting_time'),
             header.get('topic') or '',
             json.dumps(header.get('participants') or [], ensure_ascii=False),
             json.dumps({'header': header, 'managers': managers, 'extras': extras or {}},
                        ensure_ascii=False),
             json.dumps((extras or {}).get('insights') or [], ensure_ascii=False),
             raw_text or '', previous_record_id, body))
        record_id = c.lastrowid
        _iata_write_hierarchy(c, record_id, managers)
        conn.commit()
        return record_id
    finally:
        conn.close()


def _iata_write_hierarchy(c, record_id, managers):
    """(Re)escreve as tabelas da hierarquia para uma ata."""
    c.execute('DELETE FROM iata_opportunities WHERE record_id = ?', (record_id,))
    c.execute('DELETE FROM iata_accounts WHERE record_id = ?', (record_id,))
    c.execute('DELETE FROM iata_managers WHERE record_id = ?', (record_id,))
    for m_ordem, manager in enumerate(managers or []):
        c.execute('INSERT INTO iata_managers (record_id, name, display_order) VALUES (?,?,?)',
                  (record_id, manager.get('name') or iata_lib.GERENTE_NAO_IDENTIFICADO, m_ordem))
        manager_id = c.lastrowid
        for a_ordem, account in enumerate(manager.get('accounts') or []):
            nome_conta = account.get('name') or ''
            c.execute(
                '''INSERT INTO iata_accounts
                   (record_id, manager_id, account_id, name, name_norm,
                    match_confidence, match_confirmed, display_order)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (record_id, manager_id, account.get('account_id'), nome_conta,
                 iata_lib.normalize_name(nome_conta), account.get('match_confidence'),
                 1 if account.get('match_confirmed') else 0, a_ordem))
            conta_id = c.lastrowid
            for o_ordem, opp in enumerate(account.get('opportunities') or []):
                nome_opp = opp.get('name') or ''
                c.execute(
                    '''INSERT INTO iata_opportunities
                       (record_id, iata_account_id, name, name_norm, previous_status,
                        update_text, responsible, carried_over, prev_opportunity_id,
                        match_confidence, display_order)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                    (record_id, conta_id, nome_opp, iata_lib.normalize_name(nome_opp),
                     opp.get('previous_status'), opp.get('update_text'),
                     opp.get('responsible'), 1 if opp.get('carried_over') else 0,
                     opp.get('prev_opportunity_id'), opp.get('match_confidence'), o_ordem))


def _iata_read_hierarchy(c, record_id):
    """Lê a hierarquia no formato canônico, com os ids do banco.

    O resultado precisa servir como `previous_managers` para
    `iata_lib.reconcile` na próxima ata: cada oportunidade carrega `id`,
    `name`, `update_text` e `responsible` (usados pelo reconcile), além dos
    demais campos persistidos. `carried_over` e `match_confirmed` voltam
    como bool — como foram gravados (True/False) na hierarquia de entrada,
    não como 0/1 do SQLite.
    """
    c.execute('SELECT * FROM iata_managers WHERE record_id = ? ORDER BY display_order, id',
              (record_id,))
    managers = [dict_from_row(r) for r in c.fetchall()]
    for manager in managers:
        c.execute('''SELECT * FROM iata_accounts WHERE manager_id = ?
                     ORDER BY display_order, id''', (manager['id'],))
        contas = [dict_from_row(r) for r in c.fetchall()]
        for conta in contas:
            conta['match_confirmed'] = bool(conta.get('match_confirmed'))
            c.execute('''SELECT * FROM iata_opportunities WHERE iata_account_id = ?
                         ORDER BY display_order, id''', (conta['id'],))
            conta['opportunities'] = [dict_from_row(r) for r in c.fetchall()]
            for opp in conta['opportunities']:
                opp['carried_over'] = bool(opp.get('carried_over'))
        manager['accounts'] = contas
    return managers


def _iata_load_record(record_id):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT * FROM iata_records WHERE id = ?', (record_id,))
        row = c.fetchone()
        if not row:
            return None
        registro = dict_from_row(row)
        try:
            registro['participants'] = json.loads(registro.get('participants') or '[]')
        except Exception:
            registro['participants'] = []
        ata_json = {}
        try:
            ata_json = json.loads(registro.get('ata_json') or '{}')
        except Exception:
            ata_json = {}
        if not isinstance(ata_json, dict):
            ata_json = {}
        try:
            registro['insights_json'] = json.loads(registro.get('insights_json') or '[]')
        except Exception:
            registro['insights_json'] = []
        registro['ata_json'] = ata_json
        registro['extras'] = ata_json.get('extras') or {}
        registro['header'] = ata_json.get('header') or {}
        registro['managers'] = _iata_read_hierarchy(c, record_id)
        return registro
    finally:
        conn.close()


def _iata_sugerir_contas(managers):
    """Sugere o vínculo de cada conta citada na ata com uma conta cadastrada
    em `accounts`, por nome (reaproveita `iata_lib.match_account_name`: nome
    exato -> sem sufixo de forma jurídica -> similaridade — a mesma lógica
    já usada para casar com a ata anterior, em vez de duplicar aqui um
    matching mais fraco de só exato + fuzzy 0.85, que não casaria "Ambev"
    com "Ambev S.A.", o caso mais comum).

    Isto é só SUGESTÃO — nunca marca `match_confirmed`; quem confirma o
    vínculo é o usuário, pela rota `/link`. Uma conta que já veio com
    `match_confirmed=True` (por exemplo herdada da ata anterior via
    `reconcile`) é preservada como está: uma nova sugestão não pode
    desfazer uma confirmação humana.
    """
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT id, name FROM accounts')
        catalogo = {}
        for r in c.fetchall():
            norm = iata_lib.normalize_name(r['name'])
            if norm:
                # Primeira conta cadastrada com este nome normalizado vence
                # em caso de duas contas que colapsem para o mesmo nome —
                # cenário raro demais para merecer mais mecanismo aqui.
                catalogo.setdefault(norm, r['id'])
    finally:
        conn.close()

    for manager in (managers or []):
        for account in (manager.get('accounts') or []):
            if account.get('match_confirmed'):
                continue
            account_id, confidence = iata_lib.match_account_name(account.get('name'), catalogo)
            if account_id is not None:
                account['account_id'] = account_id
                account['match_confidence'] = confidence
    return managers


def _iata_insights_ofertas(header, managers):
    """Cruza as oportunidades da ata com as ofertas do portfólio STF via IA."""
    conn = get_db()
    try:
        c = conn.cursor()
        # portfolio_offers não tem coluna `description` — as colunas reais
        # são title/summary (ver CREATE TABLE em app.py). Um SELECT com o
        # nome errado derrubaria a geração inteira da ata com uma exceção.
        c.execute('SELECT title, summary FROM portfolio_offers ORDER BY title')
        ofertas = [dict_from_row(r) for r in c.fetchall()]
    finally:
        conn.close()
    if not ofertas:
        return []

    resumo = [
        {'conta': a.get('name'), 'oportunidade': o.get('name'), 'update': o.get('update_text')}
        for m in (managers or []) for a in (m.get('accounts') or [])
        for o in (a.get('opportunities') or [])
    ]
    if not resumo:
        return []

    prompt = (
        "Você é consultor de negócios. Para as oportunidades abaixo, identifique dores "
        "e cruze com as soluções do portfólio.\n"
        "Retorne EXCLUSIVAMENTE JSON: "
        '{"insights":[{"pain":"dor","matched_offer":"título da oferta ou null",'
        '"confidence":"alta/media/baixa","observation":"observação breve"}]}\n\n'
        f"OPORTUNIDADES:\n{json.dumps(resumo, ensure_ascii=False)[:12000]}\n\n"
        f"SOLUÇÕES STF:\n{json.dumps(ofertas, ensure_ascii=False)[:12000]}"
    )
    raw = _llm_prompt(prompt, log_tag='iAta/Insights')
    parsed = iata_lib._loads_tolerante(raw) if raw else None
    if not isinstance(parsed, dict):
        logger.warning('[iAta] Insights sem resposta utilizável da IA.')
        return []

    insights = parsed.get('insights')
    if isinstance(insights, dict):
        # A IA às vezes devolve um objeto solto em vez de uma lista com um
        # item — trata como lista de um elemento em vez de descartar.
        insights = [insights]
    if not isinstance(insights, list):
        logger.warning('[iAta] Campo "insights" da IA não é lista nem objeto utilizável.')
        return []
    # Item fora do formato (string solta em vez de dict) entra como texto
    # cru, mesmo princípio de `_linhas_de_passos`/`_linhas_de_insights` em
    # integrations/iata/render.py: melhor exibir algo imperfeito do que
    # descartar em silêncio.
    return insights


def _iata_resolver_ambiguidade(pares):
    """Desempata oportunidades parecidas em UMA chamada de IA, em lote."""
    if not pares:
        return {}
    prompt = (
        "Você recebe pares de oportunidades comerciais. Para cada par, diga se a "
        "oportunidade nova é a MESMA da lista de candidatas anteriores.\n"
        "Retorne EXCLUSIVAMENTE JSON: "
        '{"decisoes":[{"index":0,"id_anterior":123}]}. '
        "Use id_anterior null quando for uma oportunidade diferente.\n\n"
        + json.dumps(pares, ensure_ascii=False)
    )
    raw = _llm_prompt(prompt, log_tag='iAta/Ambiguidade')
    parsed = iata_lib._loads_tolerante(raw) if raw else None
    if not isinstance(parsed, dict):
        return {}
    saida = {}
    for d in (parsed.get('decisoes') or []):
        if isinstance(d, dict) and d.get('index') is not None:
            try:
                saida[int(d['index'])] = d.get('id_anterior')
            except Exception:
                continue
    return saida


def _iata_previous_managers(previous_record_id):
    """Carrega os gerentes da ata anterior indicada para servir de base à
    reconciliação. Devolve `(managers, aviso)`.

    Um `previous_record_id` que não existe mais no banco (apagado entre a
    escolha do usuário e o fim da geração, ou um id inválido vindo do form)
    NÃO derruba a tarefa inteira — a extração da IA já rodou e não deve ser
    descartada por isso — mas também não pode passar em silêncio: o usuário
    pediu continuidade com uma ata específica e ela não aconteceu. Isso vira
    um aviso explícito no resultado da task e a ata é salva sem referenciar
    um id fantasma.
    """
    if not previous_record_id:
        return [], None
    anterior = _iata_load_record(previous_record_id)
    if not anterior:
        aviso = (f'A ata anterior selecionada (id {previous_record_id}) não foi '
                 'encontrada; esta ata foi gerada sem continuidade com ela.')
        logger.warning(f'[iAta] {aviso}')
        return [], aviso
    return (anterior.get('managers') or []), None


def _iata_process_async(task_id, file_bytes, filename, raw_text_input,
                        previous_record_id=None, with_insights=True):
    try:
        raw_text = (raw_text_input or '').strip()
        if file_bytes:
            _iata_task_set(task_id, {'step': 'Extraindo texto do arquivo...', 'progress': 15})
            texto_arquivo = _iata_extract_bytes(file_bytes, filename)
            raw_text = (texto_arquivo + '\n\n' + raw_text).strip() if raw_text else texto_arquivo
        if not raw_text:
            _iata_task_set(task_id, {'status': 'error',
                                     'error': 'Não foi possível extrair texto da reunião.'})
            return

        # build_extraction_prompt() só embute os primeiros MAX_TRANSCRICAO_CHARS
        # caracteres no prompt enviado à IA — raw_text (persistido abaixo em
        # _iata_save_record) continua sendo o texto INTEIRO. Truncar o que vai
        # para o banco seria perda de dado real, não só uma limitação de prompt.
        if len(raw_text) > iata_lib.MAX_TRANSCRICAO_CHARS:
            logger.warning(
                f'[iAta][Task:{task_id}] Transcrição com {len(raw_text)} caracteres; '
                f'o prompt de extração usa só os primeiros {iata_lib.MAX_TRANSCRICAO_CHARS} '
                '(o texto completo continua sendo salvo em raw_text).')

        _iata_task_set(task_id, {'step': 'Extraindo contas e oportunidades...', 'progress': 35})
        raw = _llm_prompt(iata_lib.build_extraction_prompt(raw_text), log_tag='iAta/Extração')
        parsed = iata_lib.parse_hierarchy(raw) if raw else None
        if not parsed:
            _iata_task_set(task_id, {
                'status': 'error',
                'error': 'A IA não retornou uma ata utilizável. Tente novamente.'})
            return

        _iata_task_set(task_id, {'step': 'Comparando com a ata anterior...', 'progress': 55})
        previous_managers, aviso_continuidade = _iata_previous_managers(previous_record_id)
        managers = iata_lib.reconcile(
            parsed['managers'], previous_managers, resolver=_iata_resolver_ambiguidade)
        # Se a ata anterior pedida não existe mais, não grava uma referência
        # fantasma em previous_record_id — o aviso acima já cobre o usuário.
        effective_previous_id = None if aviso_continuidade else previous_record_id

        # Sugestão DEPOIS do reconcile, sobre os managers já reconciliados —
        # não sobre parsed['managers'] (fresco da extração da IA, que nunca
        # tem match_confirmed). É só na saída do reconcile que uma conta
        # carrega match_confirmed=True herdado da ata anterior, e é esse
        # campo que o guard de _iata_sugerir_contas usa para não sobrescrever
        # um vínculo que o usuário já confirmou.
        _iata_task_set(task_id, {'step': 'Cruzando contas com o CRM...', 'progress': 70})
        _iata_sugerir_contas(managers)

        extras = {}
        if with_insights:
            _iata_task_set(task_id, {'step': 'Gerando insights de negócio...', 'progress': 85})
            extras['insights'] = _iata_insights_ofertas(parsed['header'], managers)

        _iata_task_set(task_id, {'step': 'Salvando ata...', 'progress': 95})
        record_id = _iata_save_record(parsed['header'], managers, extras, raw_text,
                                      effective_previous_id)
        registro = _iata_load_record(record_id)
        updates = {'step': 'Concluído!', 'progress': 100, 'status': 'done', 'result': registro}
        if aviso_continuidade:
            updates['warning'] = aviso_continuidade
        _iata_task_set(task_id, updates)
    except Exception as e:
        logger.exception(f'[iAta][Task:{task_id}] Erro: {e}')
        _iata_task_set(task_id, {'status': 'error', 'error': str(e)})
    finally:
        _iata_task_cleanup(task_id)


@app.route('/api/autotoca/iata', methods=['POST'])
def create_iata_record():
    try:
        file_obj = request.files.get('meeting_file')
        raw_text_input = (request.form.get('raw_text') or '').strip()
        if not file_obj and not raw_text_input:
            return jsonify({'error': 'Envie um arquivo de reunião ou cole o texto.'}), 400

        file_bytes, filename = None, None
        if file_obj and file_obj.filename:
            file_bytes = file_obj.read()
            filename = file_obj.filename
        # Arquivo presente porém vazio: falhar aqui é mais barato (e mais claro
        # pro usuário) do que abrir uma task que só vai morrer no meio.
        if not raw_text_input and not file_bytes:
            return jsonify({'error': 'O arquivo enviado está vazio. '
                                     'Envie a transcrição da reunião ou cole o texto.'}), 400

        previous_record_id = request.form.get('previous_record_id') or None
        if previous_record_id:
            try:
                previous_record_id = int(previous_record_id)
            except ValueError:
                previous_record_id = None
        # Comparação por lista de valores verdadeiros, não por "diferente de
        # '0'": um formulário mandando 'false'/'no' significa desligado, e a
        # partir da Task 8 os insights são uma chamada de LLM paga — ligar
        # isso contra a vontade do usuário custa dinheiro e tempo dele.
        with_insights = (request.form.get('with_insights') or '1').strip().lower() \
            in ('1', 'true', 'yes', 'on', 'sim')

        task_id = uuid.uuid4().hex
        _iata_task_set(task_id, {'status': 'processing', 'step': 'Iniciando...', 'progress': 5})
        try:
            threading.Thread(
                target=_iata_process_async,
                args=(task_id, file_bytes, filename, raw_text_input),
                kwargs={'previous_record_id': previous_record_id, 'with_insights': with_insights},
                daemon=True).start()
        except Exception:
            # Sem worker rodando, a task ficaria 'processing' para sempre e o
            # frontend giraria sem fim — marcar o erro é o que encerra o polling.
            _iata_task_set(task_id, {'status': 'error',
                                     'error': 'Não foi possível iniciar o processamento.'})
            raise
        return jsonify({'task_id': task_id}), 202
    except Exception as e:
        logger.exception(f'[iAta] Erro ao iniciar tarefa: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/iata/tasks/<task_id>', methods=['GET'])
def get_iata_task_status(task_id):
    task = _iata_task_get(task_id)
    if not task:
        return jsonify({'status': 'error', 'error': 'Tarefa não encontrada ou expirada.'}), 404
    return jsonify(task)


@app.route('/api/autotoca/iata', methods=['GET'])
def list_iata_records():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''SELECT id, title, meeting_date, meeting_time, topic, participants,
                            format_version, body_edited, reparse_failed, created_at
                     FROM iata_records ORDER BY datetime(created_at) DESC, id DESC''')
        registros = []
        for row in c.fetchall():
            r = dict_from_row(row)
            try:
                r['participants'] = json.loads(r.get('participants') or '[]')
            except Exception:
                r['participants'] = []
            registros.append(r)
        conn.close()
        return jsonify(registros)
    except Exception as e:
        logger.exception(f'[iAta] Erro ao listar registros: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/iata/<int:record_id>', methods=['GET'])
def get_iata_record(record_id):
    try:
        registro = _iata_load_record(record_id)
        if not registro:
            return jsonify({'error': 'Ata não encontrada.'}), 404
        return jsonify(registro)
    except Exception as e:
        logger.exception(f'[iAta] Erro ao buscar registro {record_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/iata/<int:record_id>', methods=['DELETE'])
def delete_iata_record(record_id):
    try:
        conn = get_db()
        c = conn.cursor()
        # get_db() já liga PRAGMA foreign_keys=ON (o ON DELETE CASCADE do
        # schema cobriria isto sozinho), mas apagamos as filhas explicitamente
        # mesmo assim: não depender de um PRAGMA por conexão para uma
        # exclusão que não pode deixar hierarquia órfã para trás.
        c.execute('DELETE FROM iata_opportunities WHERE record_id = ?', (record_id,))
        c.execute('DELETE FROM iata_accounts WHERE record_id = ?', (record_id,))
        c.execute('DELETE FROM iata_managers WHERE record_id = ?', (record_id,))
        c.execute('DELETE FROM iata_records WHERE id = ?', (record_id,))
        removidos = c.rowcount
        conn.commit()
        conn.close()
        if not removidos:
            return jsonify({'error': 'Ata não encontrada.'}), 404
        return jsonify({'message': 'Ata removida com sucesso.'})
    except Exception as e:
        logger.exception(f'[iAta] Erro ao remover registro {record_id}: {e}')
        return jsonify({'error': str(e)}), 500


def _iata_match_previous(old_items, new_items, name_of):
    """Casa cada item de `new_items` com o item correspondente de
    `old_items`, para carregar adiante campos que só existem no lado antigo
    (`account_id`/`match_confirmed` de uma conta, `prev_opportunity_id` de
    uma oportunidade) através de um re-parse.

    Estratégia igual à do robô de formulário (`integrations/forms_robot.py`):
    nome normalizado primeiro (resiliente a reordenação), posição como
    fallback (resiliente a um typo corrigido ou nome levemente reescrito —
    mas arriscado se o item realmente virou outra coisa). O fallback só
    entra quando as duas listas têm o mesmo tamanho: é o sinal mais barato
    de "provavelmente o mesmo conjunto, só com nomes ajustados" sem tentar
    adivinhar mais que isso.

    Devolve uma lista paralela a `new_items`: cada posição é `None` (sem
    candidato) ou uma tupla `(item_antigo, via)`, `via` sendo `'name'` ou
    `'position'` — o chamador usa `via` para decidir o que é seguro herdar
    do item antigo (ver `_iata_carregar_campos_anteriores`: uma
    confirmação humana NUNCA pode vir de um casamento `'position'`, só
    `'name'`, porque `'position'` é um palpite, não uma identidade
    confirmada)."""
    usados = set()
    old_by_norm = {}
    for old in old_items:
        norm = iata_lib.normalize_name(name_of(old))
        old_by_norm.setdefault(norm, old)

    resultado = [None] * len(new_items)
    for i, novo in enumerate(new_items):
        norm = iata_lib.normalize_name(name_of(novo))
        candidato = old_by_norm.get(norm)
        if candidato is not None and id(candidato) not in usados:
            resultado[i] = (candidato, 'name')
            usados.add(id(candidato))

    if len(old_items) == len(new_items):
        for i in range(len(new_items)):
            if resultado[i] is None and id(old_items[i]) not in usados:
                resultado[i] = (old_items[i], 'position')
                usados.add(id(old_items[i]))

    return resultado


def _iata_carregar_campos_anteriores(managers_antigos, managers_novos):
    """Depois de um re-parse bem-sucedido, preenche em `managers_novos` (in
    place) os campos que a IA não devolve porque não fazem parte do texto:
    `account_id`/`match_confirmed`/`match_confidence` de cada conta, e
    `previous_status`/`prev_opportunity_id`/`carried_over` de cada
    oportunidade — usando `_iata_match_previous` em cada nível da
    hierarquia (gerente -> conta -> oportunidade).

    Achado da revisão de qualidade da Task 9: quando o casamento de uma
    CONTA veio por posição (o nome mudou e não há como confirmar que é a
    mesma conta), `match_confirmed` NUNCA é herdado como True — mesmo que a
    conta antiga estivesse confirmada via `/link`. Herdar cegamente
    trocaria vínculos de CRM quando o usuário renomeia duas contas do mesmo
    gerente e inverte a ordem em que digita (reproduzido na revisão:
    "Ambev"/"Heineken" confirmadas, usuário reescreve como "Heineken
    NV"/"Ambev Brasil" na ordem trocada — sem esta guarda, cada uma herdaria
    o account_id CONFIRMADO da outra). `account_id`/`match_confidence`
    continuam vindo como SUGESTÃO (o usuário pode reconfirmar em um clique
    em vez de procurar a conta de novo), só `match_confirmed` é zerado.

    Cada oportunidade recebe também uma chave temporária `_old_own_id` (o
    id de banco da oportunidade ANTIGA desta mesma ata que foi casada, não
    o `prev_opportunity_id` que ela carrega) — usada pelo chamador para
    remapear referências de OUTRAS atas depois do DELETE+INSERT de
    `_iata_write_hierarchy` (ver rota `update_iata_body`). Precisa ser
    removida do dict antes de persistir em `ata_json`.

    Devolve um dict `{'accounts': [...], 'opportunities': [...]}` com um
    item por casamento feito por posição, para a rota reportar ao usuário
    (nunca silencioso — mesmo princípio do campo `positional` no robô de
    formulário: "uma resposta na pergunta errada é pior que uma pergunta em
    branco")."""
    positional = {'accounts': [], 'opportunities': []}
    gerente_map = _iata_match_previous(
        managers_antigos, managers_novos, lambda m: m.get('name'))
    for manager, gm in zip(managers_novos, gerente_map):
        antigo_manager = gm[0] if gm else {}
        contas_antigas = (antigo_manager or {}).get('accounts') or []
        conta_map = _iata_match_previous(
            contas_antigas, manager.get('accounts') or [], lambda a: a.get('name'))
        for account, cm in zip(manager.get('accounts') or [], conta_map):
            antiga_conta = (cm[0] if cm else None) or {}
            via_conta = cm[1] if cm else None
            account['account_id'] = antiga_conta.get('account_id')
            account['match_confidence'] = antiga_conta.get('match_confidence')
            if via_conta == 'position':
                account['match_confirmed'] = False
                positional['accounts'].append({
                    'manager': manager.get('name'), 'name': account.get('name'),
                    'previous_name': antiga_conta.get('name')})
            else:
                account['match_confirmed'] = bool(antiga_conta.get('match_confirmed'))

            opps_antigas = antiga_conta.get('opportunities') or []
            opp_map = _iata_match_previous(
                opps_antigas, account.get('opportunities') or [], lambda o: o.get('name'))
            for opp, om in zip(account.get('opportunities') or [], opp_map):
                antiga_opp = (om[0] if om else None) or {}
                via_opp = om[1] if om else None
                opp['previous_status'] = antiga_opp.get('previous_status')
                opp['prev_opportunity_id'] = antiga_opp.get('prev_opportunity_id')
                opp['carried_over'] = bool(antiga_opp.get('carried_over'))
                opp['responsible'] = opp.get('responsible') or manager.get('name')
                opp['_old_own_id'] = antiga_opp.get('id')
                if via_opp == 'position':
                    positional['opportunities'].append({
                        'manager': manager.get('name'), 'account': account.get('name'),
                        'name': opp.get('name'), 'previous_name': antiga_opp.get('name')})
    return positional


def _iata_flatten_opportunities(managers):
    """Achata `managers` na mesma ordem gerente -> conta -> oportunidade em
    que `_iata_write_hierarchy` insere (e `_iata_read_hierarchy` lê de
    volta, por `display_order`) — usado para alinhar índice a índice a
    oportunidade antiga com a nova linha física que a substitui."""
    saida = []
    for m in managers or []:
        for a in m.get('accounts') or []:
            for o in a.get('opportunities') or []:
                saida.append(o)
    return saida


def _iata_titulo_apos_edicao(titulo_anterior, titulo_novo_ia, body_editado):
    """Decide o título depois de um re-parse bem-sucedido.

    Achado da revisão: a IA reformula o título mesmo quando o usuário só
    corrigiu um typo no corpo ("Reunião Ambev - Q3" -> "Reunião comercial
    Ambev" sem nenhuma intenção do usuário de renomear a ata). Mantém o
    título anterior se ele (comparado por `normalize_name`, tolerante a
    acento/caixa/pontuação) ainda aparece em algum lugar do texto editado —
    só aceita o título novo da IA quando o antigo sumiu do corpo, sinal de
    que a mudança foi uma decisão deliberada do usuário ao reescrever o
    cabeçalho."""
    antigo_norm = iata_lib.normalize_name(titulo_anterior or '')
    corpo_norm = iata_lib.normalize_name(body_editado or '')
    if antigo_norm and antigo_norm in corpo_norm:
        return titulo_anterior
    return (titulo_novo_ia or '').strip() or titulo_anterior


# Um lock por ata em memória — este é um app local de processo único (sem
# múltiplos workers), então não precisa de lock distribuído: só impedir que
# dois PUTs concorrentes na MESMA ata entrelacem suas transações (achado da
# revisão: PUT A com IA lenta + PUT B rápida terminavam com body_markdown do
# B e hierarquia do A, uma mistura de duas edições diferentes). O dict é
# protegido por um lock global só para a operação de criar/buscar o lock de
# uma ata — não para o corpo da edição em si, que fica só sob o lock daquela
# ata específica (duas atas diferentes continuam podendo editar em paralelo).
_iata_body_locks = {}
_iata_body_locks_guard = threading.Lock()


def _iata_body_lock(record_id):
    with _iata_body_locks_guard:
        lock = _iata_body_locks.get(record_id)
        if lock is None:
            lock = threading.Lock()
            _iata_body_locks[record_id] = lock
        return lock


@app.route('/api/autotoca/iata/<int:record_id>/body', methods=['PUT'])
def update_iata_body(record_id):
    """Edição do texto da ata (Task 9). A regra de produto: o texto que o
    usuário escreveu é gravado ANTES de qualquer tentativa de re-parse, e
    nunca se perde — se a IA não conseguir reestruturar o texto editado de
    volta para a hierarquia, o texto fica, a estrutura antiga é mantida, e a
    falha vira aviso visível (`reparse_failed`), nunca silêncio.

    `reparse_failed` é gravado como 1 já no primeiro UPDATE (assume falho
    até prova em contrário) e só volta a 0 depois que a hierarquia nova é
    escrita com sucesso — se o processo cair no meio (entre gravar o texto e
    terminar o re-parse), o registro fica com o sinal de alerta LIGADO, não
    apagado: um `reparse_failed=0` indevido seria pior que um falso alarme,
    porque esconderia do usuário que a estrutura pode estar desatualizada.

    Toda a operação roda sob um lock em memória por `record_id` (achado da
    revisão: dois PUTs concorrentes na mesma ata, um com IA lenta e outro
    rápido, terminavam entrelaçados — texto de uma edição com hierarquia da
    outra). Isso serializa PUTs concorrentes na MESMA ata; atas diferentes
    continuam livres para editar em paralelo."""
    try:
        payload = request.get_json(silent=True) or {}
        body = (payload.get('body_markdown') or '').strip()
        if not body:
            return jsonify({'error': 'O corpo da ata não pode ficar vazio.'}), 400

        with _iata_body_lock(record_id):
            # `atual` é lido DENTRO do lock: um PUT que esperou a vez herda o
            # resultado do PUT anterior (não uma foto de antes dele), senão a
            # serialização não resolveria o entrelaçamento — só adiaria.
            atual = _iata_load_record(record_id)
            if not atual:
                return jsonify({'error': 'Ata não encontrada.'}), 404

            # 1) grava o texto ANTES de qualquer coisa: o que o usuário
            # escreveu não se perde. reparse_failed=1 por padrão (docstring).
            conn = get_db()
            conn.execute(
                'UPDATE iata_records SET body_markdown = ?, body_edited = 1, reparse_failed = 1 '
                'WHERE id = ?', (body, record_id))
            conn.commit()
            conn.close()

            # 2) tenta trazer o texto de volta para a hierarquia.
            raw = _llm_prompt(iata_lib.build_reparse_prompt(body), log_tag='iAta/Reparse')
            parsed = iata_lib.parse_hierarchy(raw) if raw else None
            if not parsed:
                logger.warning(f'[iAta] Re-parse falhou para a ata {record_id}; '
                               'texto preservado, estrutura mantida.')
                return jsonify({'message': 'Texto salvo, mas não foi possível reestruturar a '
                                            'ata automaticamente. A hierarquia exibida ainda é '
                                            'a anterior.',
                                'reparse_failed': True})

            # 3) preserva vínculo com o CRM (account_id/match_confirmed) e
            # encadeamento com a ata anterior (prev_opportunity_id) do que
            # continua casando por nome — com fallback posicional sinalizado
            # em `positional_matches` (ver `_iata_carregar_campos_anteriores`
            # para a regra de não confirmar vínculo por posição).
            positional_matches = _iata_carregar_campos_anteriores(
                atual['managers'], parsed['managers'])

            # Título: mantém o anterior se ainda aparece no corpo editado —
            # ver `_iata_titulo_apos_edicao`.
            titulo_final = _iata_titulo_apos_edicao(
                atual.get('title'), parsed['header'].get('title'), body)
            parsed['header']['title'] = titulo_final

            # ids antigos das oportunidades desta ata, na mesma ordem de
            # travessia usada por `_iata_write_hierarchy`/`_iata_read_hierarchy`
            # — junto com os ids físicos que outras atas referenciam agora
            # (capturado ANTES do DELETE de `_iata_write_hierarchy`, que
            # dispara ON DELETE SET NULL em cascata sobre quem aponta para
            # essas linhas).
            old_ids = [o['id'] for o in _iata_flatten_opportunities(atual['managers'])]
            conn = get_db()
            c = conn.cursor()
            referencing = []
            if old_ids:
                placeholders = ','.join('?' * len(old_ids))
                c.execute(
                    f'SELECT id, prev_opportunity_id FROM iata_opportunities '
                    f'WHERE record_id != ? AND prev_opportunity_id IN ({placeholders})',
                    (record_id, *old_ids))
                referencing = c.fetchall()

            new_flat = _iata_flatten_opportunities(parsed['managers'])
            # `_old_own_id` é temporário (ver `_iata_carregar_campos_anteriores`)
            # — extraído aqui na mesma ordem de travessia, e removido do dict
            # antes de ir para `ata_json` (não é dado de negócio real).
            old_own_ids_in_order = [o.pop('_old_own_id', None) for o in new_flat]

            # extras (insights) não são reextraídos do texto editado — o
            # re-parse só reestrutura Gerente/Conta/Oportunidade, então tanto
            # `extras` quanto `insights_json` continuam sendo os da geração
            # original. Se o usuário apagou uma seção de insight no texto,
            # isso não se reflete aqui: é uma limitação aceita, não um bug —
            # não há como o re-parse saber que a ausência foi intencional.
            _iata_write_hierarchy(c, record_id, parsed['managers'])

            # Remapeia prev_opportunity_id de OUTRAS atas que apontavam para
            # ids antigos desta ata: o DELETE+INSERT acima dá identidade
            # física nova à mesma oportunidade lógica, e sem este remapeamento
            # o ON DELETE SET NULL derrubaria silenciosamente o encadeamento
            # de uma ata FUTURA mesmo que a oportunidade continue existindo
            # (só com id novo). Onde a oportunidade antiga não tem
            # correspondente nova (sumiu do texto editado), NULL — já
            # aplicado pelo cascade — é o resultado honesto.
            if referencing:
                novos_flat = _iata_flatten_opportunities(_iata_read_hierarchy(c, record_id))
                id_map = {}
                for old_own_id, novo_row in zip(old_own_ids_in_order, novos_flat):
                    if old_own_id is not None:
                        id_map[old_own_id] = novo_row['id']
                for other_opp_id, old_prev_id in referencing:
                    novo_id = id_map.get(old_prev_id)
                    if novo_id is not None:
                        c.execute(
                            'UPDATE iata_opportunities SET prev_opportunity_id = ? WHERE id = ?',
                            (novo_id, other_opp_id))

            c.execute('''UPDATE iata_records SET reparse_failed = 0, title = ?, ata_json = ?
                         WHERE id = ?''',
                      (titulo_final or atual['title'],
                       json.dumps({'header': parsed['header'], 'managers': parsed['managers'],
                                   'extras': atual.get('extras') or {}}, ensure_ascii=False),
                       record_id))
            conn.commit()
            conn.close()
            return jsonify({'message': 'Ata atualizada.', 'reparse_failed': False,
                            'positional_matches': positional_matches})
    except Exception as e:
        logger.exception(f'[iAta] Erro ao salvar corpo da ata {record_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/iata/<int:record_id>/accounts/<int:iata_account_id>/link',
           methods=['POST'])
def link_iata_account(record_id, iata_account_id):
    """Confirma (ou desfaz, com `account_id: null`) o vínculo de uma conta
    da ata com uma conta cadastrada em `accounts`. A sugestão automática
    (`_iata_sugerir_contas`) nunca confirma sozinha — esta rota é o único
    lugar que marca `match_confirmed`, por decisão explícita do usuário."""
    try:
        payload = request.get_json(silent=True) or {}
        account_id = payload.get('account_id')
        conn = get_db()
        c = conn.cursor()
        try:
            if account_id is not None:
                try:
                    account_id = int(account_id)
                except (TypeError, ValueError):
                    return jsonify({'error': 'account_id inválido.'}), 400
                c.execute('SELECT 1 FROM accounts WHERE id = ?', (account_id,))
                if not c.fetchone():
                    return jsonify({'error': 'Conta do CRM não encontrada.'}), 404

            c.execute('''UPDATE iata_accounts SET account_id = ?, match_confirmed = ?
                         WHERE id = ? AND record_id = ?''',
                      (account_id, 1 if account_id is not None else 0,
                       iata_account_id, record_id))
            alterados = c.rowcount
            conn.commit()
        finally:
            conn.close()
        if not alterados:
            return jsonify({'error': 'Conta da ata não encontrada.'}), 404
        return jsonify({'message': 'Vínculo atualizado.'})
    except Exception as e:
        logger.exception(f'[iAta] Erro ao vincular conta {iata_account_id}: {e}')
        return jsonify({'error': str(e)}), 500
