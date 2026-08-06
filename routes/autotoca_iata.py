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
    mas arriscado se o item realmente virou outra coisa). Sem o fallback,
    renomear uma conta no texto editado faria a confirmação humana feita via
    `/link` evaporar em silêncio — o mesmo tipo de bug já visto na Task 8.

    O fallback só entra quando as duas listas têm o mesmo tamanho: é o sinal
    mais barato de "provavelmente o mesmo conjunto, só com nomes ajustados"
    sem tentar adivinhar mais que isso.

    Devolve uma lista paralela a `new_items`, com o item antigo casado (ou
    `None` quando não há candidato)."""
    usados = set()
    old_by_norm = {}
    for old in old_items:
        norm = iata_lib.normalize_name(name_of(old))
        old_by_norm.setdefault(norm, old)

    mapping = [None] * len(new_items)
    for i, novo in enumerate(new_items):
        norm = iata_lib.normalize_name(name_of(novo))
        candidato = old_by_norm.get(norm)
        if candidato is not None and id(candidato) not in usados:
            mapping[i] = candidato
            usados.add(id(candidato))

    if len(old_items) == len(new_items):
        for i in range(len(new_items)):
            if mapping[i] is None and id(old_items[i]) not in usados:
                mapping[i] = old_items[i]
                usados.add(id(old_items[i]))

    return mapping


def _iata_carregar_campos_anteriores(managers_antigos, managers_novos):
    """Depois de um re-parse bem-sucedido, preenche em `managers_novos` (in
    place) os campos que a IA não devolve porque não fazem parte do texto:
    `account_id`/`match_confirmed`/`match_confidence` de cada conta, e
    `previous_status`/`prev_opportunity_id`/`carried_over` de cada
    oportunidade — usando `_iata_match_previous` em cada nível da
    hierarquia (gerente -> conta -> oportunidade)."""
    gerente_map = _iata_match_previous(
        managers_antigos, managers_novos, lambda m: m.get('name'))
    for manager, antigo_manager in zip(managers_novos, gerente_map):
        contas_antigas = (antigo_manager or {}).get('accounts') or []
        conta_map = _iata_match_previous(
            contas_antigas, manager.get('accounts') or [], lambda a: a.get('name'))
        for account, antiga_conta in zip(manager.get('accounts') or [], conta_map):
            antiga_conta = antiga_conta or {}
            account['account_id'] = antiga_conta.get('account_id')
            account['match_confirmed'] = bool(antiga_conta.get('match_confirmed'))
            account['match_confidence'] = antiga_conta.get('match_confidence')
            opps_antigas = antiga_conta.get('opportunities') or []
            opp_map = _iata_match_previous(
                opps_antigas, account.get('opportunities') or [], lambda o: o.get('name'))
            for opp, antiga_opp in zip(account.get('opportunities') or [], opp_map):
                antiga_opp = antiga_opp or {}
                opp['previous_status'] = antiga_opp.get('previous_status')
                opp['prev_opportunity_id'] = antiga_opp.get('prev_opportunity_id')
                opp['carried_over'] = bool(antiga_opp.get('carried_over'))
                opp['responsible'] = opp.get('responsible') or manager.get('name')


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
    porque esconderia do usuário que a estrutura pode estar desatualizada."""
    try:
        payload = request.get_json(silent=True) or {}
        body = (payload.get('body_markdown') or '').strip()
        if not body:
            return jsonify({'error': 'O corpo da ata não pode ficar vazio.'}), 400

        atual = _iata_load_record(record_id)
        if not atual:
            return jsonify({'error': 'Ata não encontrada.'}), 404

        # 1) grava o texto ANTES de qualquer coisa: o que o usuário escreveu
        # não se perde. reparse_failed=1 por padrão (ver docstring).
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
        # continua casando por nome — com fallback posicional, ver
        # `_iata_match_previous`.
        _iata_carregar_campos_anteriores(atual['managers'], parsed['managers'])

        # extras (insights) não são reextraídos do texto editado — o
        # re-parse só reestrutura Gerente/Conta/Oportunidade, então tanto
        # `extras` quanto `insights_json` continuam sendo os da geração
        # original. Se o usuário apagou uma seção de insight no texto, isso
        # não se reflete aqui: é uma limitação aceita, não um bug — não há
        # como o re-parse saber que a ausência foi intencional.
        conn = get_db()
        c = conn.cursor()
        _iata_write_hierarchy(c, record_id, parsed['managers'])
        c.execute('''UPDATE iata_records SET reparse_failed = 0, title = ?, ata_json = ?
                     WHERE id = ?''',
                  (parsed['header'].get('title') or atual['title'],
                   json.dumps({'header': parsed['header'], 'managers': parsed['managers'],
                               'extras': atual.get('extras') or {}}, ensure_ascii=False),
                   record_id))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Ata atualizada.', 'reparse_failed': False})
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
