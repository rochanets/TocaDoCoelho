# -*- coding: utf-8 -*-
# Rotas do domínio "itoca" (Bloco 3 — modularização).
# Este arquivo é executado no namespace de app.py por _load_route_modules():
# tem acesso a todos os helpers/globals de app.py e registra as rotas no
# mesmo objeto Flask `app`, com URLs idênticas às originais.

@app.route('/api/itoca/base-status', methods=['GET'])
def itoca_base_status():
    try:
        snapshot_items, updated_at = _itoca_get_cached_base()
        return jsonify({
            'has_base': len(snapshot_items) > 0,
            'items_count': len(snapshot_items),
            'updated_at': updated_at
        })
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/itoca/base-status: {e}')
        return jsonify({'error': f'Erro ao consultar status da base iToca: {e}'}), 500


@app.route('/api/itoca/base-update', methods=['POST'])
def itoca_base_update():
    """Inicia a atualização da base iToca de forma assíncrona (polling via /api/tasks/<task_id>).
    Aceita parâmetro JSON: { "incremental": true } para indexação incremental (só o que mudou).
    """
    req_data = request.get_json(silent=True) or {}
    incremental = bool(req_data.get('incremental', False))
    task_id = uuid.uuid4().hex
    _bg_task_set(task_id, {'status': 'processing', 'step': 'Iniciando...', 'progress': 5})
    threading.Thread(target=_itoca_base_update_async, args=(task_id, incremental), daemon=True).start()
    return jsonify({'task_id': task_id}), 202


@app.route('/api/itoca/ask', methods=['POST'])
def itoca_ask():
    """Inicia o processamento da pergunta de forma assíncrona.
    Salva a mensagem do usuário imediatamente (antes do LLM) para garantir persistência.
    Retorna {task_id} para polling via /api/tasks/<task_id>.
    """
    try:
        data = request.get_json() or {}
        question = (data.get('question') or '').strip()
        session_id = (data.get('session_id') or '').strip()
        if not question:
            return jsonify({'error': 'Pergunta obrigatória.'}), 400

        snapshot_items, updated_at = _itoca_get_cached_base()
        if not snapshot_items:
            return jsonify({
                'error': 'Base iToca ainda não foi atualizada. Clique em "Base Update" antes da primeira pergunta.',
                'base_ready': False
            }), 409

        # Busca histórico ANTES de salvar a mensagem do usuário (para não incluir a pergunta atual no contexto)
        history_rows = []
        if session_id:
            try:
                conn_h = get_db()
                c_h = conn_h.cursor()
                c_h.execute(
                    'SELECT role, content FROM itoca_chat_history WHERE session_id = ? ORDER BY created_at ASC LIMIT 12',
                    (session_id,)
                )
                history_rows = [dict_from_row(r) for r in c_h.fetchall()]
                conn_h.close()
            except Exception as he:
                logger.warning(f'[iToca] Erro ao buscar histórico: {he}')

        # Salva a pergunta do usuário IMEDIATAMENTE — garante que esteja no histórico
        # mesmo que o usuário navegue para outra tela antes da resposta chegar.
        if session_id:
            try:
                conn_h = get_db()
                c_h = conn_h.cursor()
                c_h.execute(
                    'INSERT INTO itoca_chat_history (session_id, role, content, confidence_percent, needs_refinement, refinement_hint) VALUES (?, ?, ?, NULL, 0, ?)',
                    (session_id, 'user', question, '')
                )
                conn_h.commit()
                conn_h.close()
            except Exception as he:
                logger.warning(f'[iToca] Erro ao salvar pergunta no histórico: {he}')

        # Inicia processamento LLM em background com etapas visíveis ao frontend
        task_id = uuid.uuid4().hex
        _bg_task_set(task_id, {'status': 'processing', 'step': '🔍 Iniciando busca...', 'progress': 5})
        threading.Thread(
            target=_itoca_ask_async,
            args=(task_id, question, session_id, snapshot_items, updated_at, history_rows),
            daemon=True
        ).start()
        return jsonify({'task_id': task_id, 'base_ready': True}), 202

    except Exception as e:
        logger.exception(f'[ERROR] POST /api/itoca/ask: {e}')
        return jsonify({'error': f'Erro ao consultar iToca: {e}'}), 500


@app.route('/api/itoca/execute-action', methods=['POST'])
def itoca_execute_action():
    """Executa a ação sugerida pelo detector de intenção após confirmação do usuário.

    Payload esperado:
        action_type  (str)   — tipo da ação (kanban_card, activity, new_contact, etc.)
        fields       (dict)  — campos extraídos pelo LLM

    Retorna:
        success      (bool)
        message      (str)   — mensagem de confirmação
        created_id   (int)   — ID do registro criado (quando aplicável)
        action_type  (str)
    """
    try:
        data = request.get_json() or {}
        action_type = (data.get('action_type') or '').strip().lower()
        fields = data.get('fields') or {}

        if not action_type or action_type not in _ITOCA_ACTION_LABELS:
            return jsonify({'error': f'Tipo de ação inválido: {action_type!r}'}), 400

        conn = get_db()
        c = conn.cursor()

        # ------------------------------------------------------------------ #
        # kanban_card — cria card na primeira coluna do Kanban                #
        # ------------------------------------------------------------------ #
        if action_type == 'kanban_card':
            title = (fields.get('title') or '').strip()
            description = (fields.get('description') or fields.get('title') or '').strip()
            urgency = (fields.get('urgency') or 'Média').strip()
            if urgency not in ['Baixa', 'Média', 'Alta', 'Crítica']:
                urgency = 'Média'
            account_name = (fields.get('account_name') or fields.get('company') or '').strip()
            contact_name = (fields.get('contact_name') or '').strip()

            if not title:
                conn.close()
                return jsonify({'error': 'Título do card é obrigatório.'}), 400

            # Resolve account_id e contact_id se fornecidos
            account_id = None
            if account_name:
                account_id = ensure_account_for_company(c, account_name)

            contact_id = None
            if contact_name:
                c.execute('SELECT id FROM clients WHERE LOWER(TRIM(name)) LIKE LOWER(TRIM(?)) LIMIT 1', (f'%{contact_name}%',))
                row = c.fetchone()
                if row:
                    contact_id = row[0] if not isinstance(row, sqlite3.Row) else row['id']

            tag = infer_kanban_tag(description)
            c.execute('SELECT id FROM kanban_columns ORDER BY display_order, id LIMIT 1')
            first_col = c.fetchone()
            if not first_col:
                conn.close()
                return jsonify({'error': 'Nenhuma coluna disponível no Kanban.'}), 400
            col_id = first_col[0] if not isinstance(first_col, sqlite3.Row) else first_col['id']

            c.execute('SELECT COALESCE(MAX(display_order), 0) FROM kanban_cards WHERE column_id = ?', (col_id,))
            next_order = (c.fetchone()[0] or 0) + 1
            c.execute(
                '''INSERT INTO kanban_cards (title, description, tag, account_id, contact_id, urgency, column_id, display_order)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (title, description, tag, account_id, contact_id, urgency, col_id, next_order)
            )
            conn.commit()
            created_id = c.lastrowid
            conn.close()
            return jsonify({
                'success': True,
                'message': f'Card “{title}” criado no Kanban com sucesso!',
                'created_id': created_id,
                'action_type': action_type
            }), 201

        # ------------------------------------------------------------------ #
        # activity — registra atividade vinculada a um contato               #
        # ------------------------------------------------------------------ #
        elif action_type == 'activity':
            contact_name = (fields.get('contact_name') or fields.get('name') or '').strip()
            company = (fields.get('company') or fields.get('account_name') or '').strip()
            description = (fields.get('description') or fields.get('information') or '').strip()
            contact_type = (fields.get('contact_type') or 'Outro').strip()

            if not description:
                conn.close()
                return jsonify({'error': 'Descrição da atividade é obrigatória.'}), 400

            # Tenta encontrar o contato pelo nome e/ou empresa
            client_id = None
            if contact_name:
                query = 'SELECT id FROM clients WHERE LOWER(TRIM(name)) LIKE LOWER(TRIM(?))'
                params = [f'%{contact_name}%']
                if company:
                    query += ' AND LOWER(TRIM(company)) LIKE LOWER(TRIM(?))'
                    params.append(f'%{company}%')
                query += ' LIMIT 1'
                c.execute(query, params)
                row = c.fetchone()
                if row:
                    client_id = row[0] if not isinstance(row, sqlite3.Row) else row['id']

            if not client_id:
                conn.close()
                return jsonify({
                    'error': f'Contato “{contact_name or "(não informado)"}” não encontrado. Verifique o nome e tente novamente.',
                    'needs_contact_selection': True
                }), 404

            c.execute(
                '''INSERT INTO activities (client_id, contact_type, information)
                   VALUES (?, ?, ?)''',
                (client_id, contact_type, description)
            )
            c.execute('UPDATE clients SET last_activity_date = CURRENT_TIMESTAMP WHERE id = ?', (client_id,))
            conn.commit()
            created_id = c.lastrowid
            conn.close()
            return jsonify({
                'success': True,
                'message': f'Atividade registrada para “{contact_name}” com sucesso!',
                'created_id': created_id,
                'action_type': action_type
            }), 201

        # ------------------------------------------------------------------ #
        # new_contact — adiciona novo contato/cliente                        #
        # ------------------------------------------------------------------ #
        elif action_type == 'new_contact':
            name = (fields.get('name') or fields.get('contact_name') or '').strip()
            company = (fields.get('company') or fields.get('account_name') or '').strip()
            position = (fields.get('position') or fields.get('cargo') or '').strip()
            email = (fields.get('email') or '').strip()
            phone = (fields.get('phone') or fields.get('telefone') or '').strip()

            if not name or not company or not position:
                conn.close()
                return jsonify({'error': 'Nome, empresa e cargo são obrigatórios para criar um contato.'}), 400

            # Verifica duplicidade simples
            c.execute(
                'SELECT id FROM clients WHERE LOWER(TRIM(name)) = LOWER(TRIM(?)) AND LOWER(TRIM(company)) = LOWER(TRIM(?)) LIMIT 1',
                (name, company)
            )
            if c.fetchone():
                conn.close()
                return jsonify({
                    'error': f'Contato “{name}” da empresa “{company}” já existe no sistema.',
                    'duplicate': True
                }), 409

            c.execute(
                '''INSERT INTO clients (name, company, position, email, phone, updated_at)
                   VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                (name, company, position, email or None, phone or None)
            )
            conn.commit()
            created_id = c.lastrowid
            conn.close()
            return jsonify({
                'success': True,
                'message': f'Contato “{name}” ({position} na {company}) adicionado com sucesso!',
                'created_id': created_id,
                'action_type': action_type
            }), 201

        # ------------------------------------------------------------------ #
        # wiki_entry — salva conhecimento no WikiToca                        #
        # ------------------------------------------------------------------ #
        elif action_type == 'wiki_entry':
            title = (fields.get('title') or '').strip()
            content = (fields.get('content') or fields.get('description') or '').strip()
            category = (fields.get('category') or '').strip() or None
            tags = (fields.get('tags') or '').strip() or None

            if not title or not content:
                conn.close()
                return jsonify({'error': 'Título e conteúdo são obrigatórios para criar um conhecimento.'}), 400

            c.execute(
                '''INSERT INTO wiki_entries (title, category, content, tags, created_at, updated_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                (title, category, content, tags)
            )
            conn.commit()
            created_id = c.lastrowid
            conn.close()
            return jsonify({
                'success': True,
                'message': f'Conhecimento “{title}” salvo no WikiToca com sucesso!',
                'created_id': created_id,
                'action_type': action_type
            }), 201

        # ------------------------------------------------------------------ #
        # commitment — agenda compromisso                                    #
        # ------------------------------------------------------------------ #
        elif action_type == 'commitment':
            title = (fields.get('title') or '').strip()
            due_date = (fields.get('due_date') or '').strip()
            due_time = (fields.get('due_time') or '').strip() or None
            notes = (fields.get('notes') or fields.get('description') or title or '').strip()
            contact_name = (fields.get('contact_name') or '').strip()

            if not due_date:
                conn.close()
                return jsonify({'error': 'Data do compromisso é obrigatória.'}), 400

            # Tenta encontrar o contato
            client_id = None
            if contact_name:
                c.execute('SELECT id FROM clients WHERE LOWER(TRIM(name)) LIKE LOWER(TRIM(?)) LIMIT 1', (f'%{contact_name}%',))
                row = c.fetchone()
                if row:
                    client_id = row[0] if not isinstance(row, sqlite3.Row) else row['id']

            if not client_id:
                conn.close()
                return jsonify({
                    'error': f'Contato “{contact_name or "(não informado)"}” não encontrado para vincular o compromisso.',
                    'needs_contact_selection': True
                }), 404

            c.execute(
                '''INSERT INTO commitments (client_id, title, notes, due_date, due_time, source_type)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (client_id, title or 'Compromisso via iToca', notes, due_date, due_time, 'itoca')
            )
            conn.commit()
            created_id = c.lastrowid
            conn.close()
            return jsonify({
                'success': True,
                'message': f'Compromisso “{title or due_date}” agendado com sucesso!',
                'created_id': created_id,
                'action_type': action_type
            }), 201

        # ------------------------------------------------------------------ #
        # environment_mapping — registra resposta de mapeamento de ambiente  #
        # ------------------------------------------------------------------ #
        elif action_type == 'environment_mapping':
            company = (fields.get('company') or fields.get('account_name') or '').strip()
            card_title = (fields.get('card_title') or fields.get('question') or '').strip()
            response_text = (fields.get('response') or fields.get('answer') or fields.get('content') or '').strip()

            if not company or not response_text:
                conn.close()
                return jsonify({'error': 'Empresa e resposta são obrigatórios para o mapeamento.'}), 400

            # Encontra ou cria a conta
            account_id = ensure_account_for_company(c, company)

            # Encontra o card de mapeamento pelo título (ou cria um genérico)
            card_id = None
            if card_title:
                c.execute(
                    'SELECT id FROM environment_cards WHERE LOWER(TRIM(title)) LIKE LOWER(TRIM(?)) LIMIT 1',
                    (f'%{card_title}%',)
                )
                row = c.fetchone()
                if row:
                    card_id = row[0] if not isinstance(row, sqlite3.Row) else row['id']

            if not card_id:
                # Cria um card genérico para a resposta
                c.execute(
                    '''INSERT INTO environment_cards (title, description, created_at, updated_at)
                       VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                    (card_title or 'Informação via iToca', '')
                )
                conn.commit()
                card_id = c.lastrowid

            c.execute(
                '''INSERT INTO environment_responses (card_id, account_id, response, created_at, updated_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                (card_id, account_id, response_text)
            )
            conn.commit()
            created_id = c.lastrowid
            conn.close()
            return jsonify({
                'success': True,
                'message': f'Mapeamento de “{company}” registrado com sucesso!',
                'created_id': created_id,
                'action_type': action_type
            }), 201

        conn.close()
        return jsonify({'error': f'Ação “{action_type}” não implementada.'}), 501

    except Exception as e:
        logger.exception(f'[ERROR] POST /api/itoca/execute-action: {e}')
        return jsonify({'error': f'Erro ao executar ação: {e}'}), 500


@app.route('/api/itoca/history', methods=['GET'])
def itoca_history_list():
    """Lista sessões de histórico do iToca dos últimos 30 dias."""
    try:
        conn = get_db()
        c = conn.cursor()
        # Purga registros com mais de 30 dias
        c.execute("DELETE FROM itoca_chat_history WHERE created_at < datetime('now', '-30 days')")
        conn.commit()
        # Retorna sessões distintas com data e primeira pergunta
        c.execute('''
            SELECT session_id,
                   MIN(created_at) AS started_at,
                   MAX(created_at) AS last_at,
                   COUNT(*) AS msg_count,
                   (SELECT content FROM itoca_chat_history h2
                    WHERE h2.session_id = h.session_id AND h2.role = 'user'
                    ORDER BY h2.created_at ASC LIMIT 1) AS first_question
            FROM itoca_chat_history h
            GROUP BY session_id
            ORDER BY last_at DESC
            LIMIT 60
        ''')
        sessions = [dict_from_row(r) for r in c.fetchall()]
        conn.close()
        return jsonify(sessions)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/itoca/history: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/itoca/history/<session_id>', methods=['GET'])
def itoca_history_session(session_id):
    """Retorna todas as mensagens de uma sessão específica."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            'SELECT id, role, content, confidence_percent, needs_refinement, refinement_hint, created_at FROM itoca_chat_history WHERE session_id = ? ORDER BY created_at ASC',
            (session_id,)
        )
        messages = [dict_from_row(r) for r in c.fetchall()]
        conn.close()
        return jsonify(messages)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/itoca/history/{session_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/itoca/history/<session_id>', methods=['DELETE'])
def itoca_history_delete(session_id):
    """Deleta uma sessão específica do histórico."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM itoca_chat_history WHERE session_id = ?', (session_id,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Sessão removida do histórico.'})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE /api/itoca/history/{session_id}: {e}')
        return jsonify({'error': str(e)}), 500
