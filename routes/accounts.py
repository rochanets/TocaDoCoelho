# -*- coding: utf-8 -*-
# Rotas do domínio "accounts" (Bloco 3 — modularização).
# Este arquivo é executado no namespace de app.py por _load_route_modules():
# tem acesso a todos os helpers/globals de app.py e registra as rotas no
# mesmo objeto Flask `app`, com URLs idênticas às originais.

@app.route('/api/accounts/support-data', methods=['GET'])
def get_accounts_support_data():
    try:
        sync_accounts_from_clients()
        conn = get_db(); c = conn.cursor()
        c.execute('''SELECT name, COALESCE(is_target, 0) as is_target FROM accounts
                     WHERE name IS NOT NULL AND TRIM(name) != ''
                     ORDER BY COALESCE(is_target, 0) DESC, name COLLATE NOCASE''')
        companies = [row['name'] for row in c.fetchall()]
        c.execute('SELECT name FROM account_sectors ORDER BY name COLLATE NOCASE')
        sectors = [row['name'] for row in c.fetchall()]
        conn.close()
        return jsonify({'companies': companies, 'sectors': sectors})
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/accounts/support-data: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts', methods=['GET'])
def list_accounts():
    try:
        sync_accounts_from_clients()
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT * FROM accounts ORDER BY name COLLATE NOCASE')
        accounts = [dict_from_row(r) for r in c.fetchall()]
        for acc in accounts:
            c.execute('''SELECT p.* FROM account_presences p WHERE p.account_id = ? ORDER BY p.delivery_name COLLATE NOCASE''', (acc['id'],))
            acc['presences'] = [dict_from_row(r) for r in c.fetchall()]
        conn.close()
        return jsonify(accounts)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/accounts: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/<int:account_id>', methods=['GET'])
def get_account(account_id):
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT * FROM accounts WHERE id = ?', (account_id,))
        account = dict_from_row(c.fetchone())
        if not account:
            conn.close(); return jsonify({'error': 'Conta não encontrada'}), 404
        c.execute('''SELECT c.id, c.name, c.position, c.photo_url, c.email
                     FROM clients c
                     WHERE LOWER(TRIM(c.company)) = LOWER(TRIM(?))
                     ORDER BY c.name''', (account['name'],))
        account['contacts'] = [dict_from_row(r) for r in c.fetchall()]
        c.execute('''SELECT client_id FROM account_main_contacts WHERE account_id = ? ORDER BY id''', (account_id,))
        account['main_contact_ids'] = [row['client_id'] for row in c.fetchall()]
        c.execute('SELECT * FROM account_presences WHERE account_id = ? ORDER BY delivery_name COLLATE NOCASE', (account_id,))
        account['presences'] = [dict_from_row(r) for r in c.fetchall()]
        conn.close(); return jsonify(account)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/accounts/{account_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/autofill', methods=['POST'])
def account_autofill():
    """Preenche automaticamente campos de uma conta com dados da empresa via SAI LLM e busca de imagem."""
    try:
        data = request.get_json() or {}
        account_name = (data.get('account_name') or '').strip()
        if not account_name:
            return jsonify({'error': 'Nome da conta não informado.'}), 400
        task_id = uuid.uuid4().hex
        _bg_task_set(task_id, {'status': 'processing', 'step': 'Iniciando...', 'progress': 5})
        threading.Thread(target=_autofill_process_async, args=(task_id, account_name), daemon=True).start()
        return jsonify({'task_id': task_id}), 202
    except Exception as e:
        logger.exception(f'[AccountAutoFill] Erro: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts', methods=['POST'])
def create_account():
    try:
        name = request.form.get('name', '').strip()
        sector = request.form.get('sector', '').strip() or None
        is_target = 1 if request.form.get('is_target') in ('1', 'true', 'True') else 0
        average_revenue_cents = parse_currency_to_cents(request.form.get('average_revenue'))
        professionals_count = request.form.get('professionals_count', '').strip()
        professionals_count = int(professionals_count) if professionals_count.isdigit() else None
        global_presence = request.form.get('global_presence', '').strip() or None
        main_contact_ids = request.form.get('main_contact_ids', '').strip()
        autofill_logo_url = (request.form.get('autofill_logo_url') or '').strip()
        if not name:
            return jsonify({'error': 'Nome da conta é obrigatório'}), 400
        conn = get_db(); c = conn.cursor()
        logo_url = autofill_logo_url or None
        if 'logo' in request.files:
            f = request.files['logo']
            if f and f.filename:
                filename = secure_filename(f"acc_{int(datetime.now().timestamp())}_{f.filename}")
                f.save(str(ACCOUNT_UPLOAD_DIR / filename))
                logo_url = f'/uploads/accounts/{filename}'
        c.execute('''INSERT INTO accounts (name, logo_url, is_target, sector, average_revenue_cents, professionals_count, global_presence, updated_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                  (name, logo_url, is_target, sector, average_revenue_cents, professionals_count, global_presence))
        account_id = c.lastrowid
        if sector:
            c.execute('INSERT OR IGNORE INTO account_sectors (name) VALUES (?)', (sector,))
        ids = [int(x) for x in main_contact_ids.split(',') if x.strip().isdigit()]
        for cid in ids:
            c.execute('INSERT OR IGNORE INTO account_main_contacts (account_id, client_id) VALUES (?, ?)', (account_id, cid))
        conn.commit(); conn.close()
        return jsonify({'id': account_id, 'message': 'Conta criada'}), 201
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/accounts: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/<int:account_id>', methods=['PUT'])
def update_account(account_id):
    try:
        name = request.form.get('name', '').strip()
        sector = request.form.get('sector', '').strip() or None
        is_target = 1 if request.form.get('is_target') in ('1', 'true', 'True') else 0
        average_revenue_cents = parse_currency_to_cents(request.form.get('average_revenue'))
        professionals_count = request.form.get('professionals_count', '').strip()
        professionals_count = int(professionals_count) if professionals_count.isdigit() else None
        global_presence = request.form.get('global_presence', '').strip() or None
        main_contact_ids = request.form.get('main_contact_ids', '').strip()
        remove_logo = request.form.get('remove_logo', '0') in ('1', 'true', 'True')
        autofill_logo_url = (request.form.get('autofill_logo_url') or '').strip()
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT * FROM accounts WHERE id = ?', (account_id,))
        row = dict_from_row(c.fetchone())
        if not row:
            conn.close(); return jsonify({'error': 'Conta não encontrada'}), 404
        old_name = row['name']
        new_name = name or old_name
        # Renomear conta: propagar para os contatos (clients.company) e mesclar conta duplicada,
        # evitando que sync_accounts_from_clients() recrie a conta com o nome antigo.
        if new_name.strip().lower() != (old_name or '').strip().lower():
            c.execute('SELECT id FROM accounts WHERE LOWER(TRIM(name)) = LOWER(TRIM(?)) AND id != ?', (new_name, account_id))
            conflict = c.fetchone()
            if conflict:
                conflict_id = conflict['id'] if isinstance(conflict, sqlite3.Row) else conflict[0]
                # Move os dados da conta conflitante para esta conta e remove a duplicata
                c.execute('UPDATE account_presences SET account_id=? WHERE account_id=?', (account_id, conflict_id))
                c.execute('UPDATE account_renewal_events SET account_id=? WHERE account_id=?', (account_id, conflict_id))
                c.execute('UPDATE account_activities SET account_id=? WHERE account_id=?', (account_id, conflict_id))
                c.execute('UPDATE kanban_cards SET account_id=? WHERE account_id=?', (account_id, conflict_id))
                c.execute('DELETE FROM account_main_contacts WHERE account_id=?', (conflict_id,))
                c.execute('DELETE FROM accounts WHERE id=?', (conflict_id,))
            # Atualiza a referência do nome em todos os contatos vinculados
            c.execute('UPDATE clients SET company=?, updated_at=CURRENT_TIMESTAMP WHERE LOWER(TRIM(company)) = LOWER(TRIM(?))', (new_name, old_name))
        logo_url = None if remove_logo else (autofill_logo_url or row.get('logo_url'))
        if 'logo' in request.files:
            f = request.files['logo']
            if f and f.filename:
                filename = secure_filename(f"acc_{int(datetime.now().timestamp())}_{f.filename}")
                f.save(str(ACCOUNT_UPLOAD_DIR / filename))
                logo_url = f'/uploads/accounts/{filename}'
        c.execute('''UPDATE accounts SET name=?, logo_url=?, is_target=?, sector=?, average_revenue_cents=?, professionals_count=?, global_presence=?, updated_at=CURRENT_TIMESTAMP WHERE id=?''',
                  (name or row['name'], logo_url, is_target, sector, average_revenue_cents, professionals_count, global_presence, account_id))
        if sector:
            c.execute('INSERT OR IGNORE INTO account_sectors (name) VALUES (?)', (sector,))
        c.execute('DELETE FROM account_main_contacts WHERE account_id = ?', (account_id,))
        ids = [int(x) for x in main_contact_ids.split(',') if x.strip().isdigit()]
        for cid in ids:
            c.execute('INSERT OR IGNORE INTO account_main_contacts (account_id, client_id) VALUES (?, ?)', (account_id, cid))
        conn.commit(); conn.close()
        return jsonify({'message': 'Conta atualizada'})
    except Exception as e:
        logger.exception(f'[ERROR] PUT /api/accounts/{account_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/<int:account_id>', methods=['DELETE'])
def delete_account(account_id):
    """Arquiva (snapshot completo em JSON) e exclui a conta, seus contatos e todo o histórico."""
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT * FROM accounts WHERE id = ?', (account_id,))
        account = dict_from_row(c.fetchone())
        if not account:
            conn.close(); return jsonify({'error': 'Conta não encontrada'}), 404
        name = account['name']

        # Contatos (clients) vinculados à conta pelo nome da empresa
        c.execute('SELECT * FROM clients WHERE LOWER(TRIM(company)) = LOWER(TRIM(?))', (name,))
        clients = [dict_from_row(r) for r in c.fetchall()]
        client_ids = [cl['id'] for cl in clients]

        def _fetch_for_clients(query):
            if not client_ids:
                return []
            ph = ','.join('?' * len(client_ids))
            c.execute(query.format(ph=ph), client_ids)
            return [dict_from_row(r) for r in c.fetchall()]

        client_activities = _fetch_for_clients('SELECT * FROM activities WHERE client_id IN ({ph})')
        client_commitments = _fetch_for_clients('SELECT * FROM commitments WHERE client_id IN ({ph})')
        client_env_responses = _fetch_for_clients('SELECT * FROM environment_responses WHERE client_id IN ({ph})')

        c.execute('SELECT * FROM account_main_contacts WHERE account_id = ?', (account_id,))
        main_contacts = [dict_from_row(r) for r in c.fetchall()]
        c.execute('SELECT * FROM account_presences WHERE account_id = ?', (account_id,))
        presences = [dict_from_row(r) for r in c.fetchall()]
        c.execute('SELECT * FROM account_renewal_events WHERE account_id = ?', (account_id,))
        renewal_events = [dict_from_row(r) for r in c.fetchall()]
        c.execute('SELECT * FROM account_activities WHERE account_id = ?', (account_id,))
        account_activities = [dict_from_row(r) for r in c.fetchall()]

        snapshot = {
            'version': 1,
            'account': account,
            'clients': clients,
            'client_activities': client_activities,
            'client_commitments': client_commitments,
            'client_env_responses': client_env_responses,
            'main_contacts': main_contacts,
            'presences': presences,
            'renewal_events': renewal_events,
            'account_activities': account_activities,
        }
        c.execute('''INSERT INTO account_archives (account_name, snapshot_json, contacts_count, activities_count)
                     VALUES (?, ?, ?, ?)''',
                  (name, json.dumps(snapshot, default=str, ensure_ascii=False),
                   len(clients), len(client_activities) + len(account_activities)))

        # Remove dados específicos da conta
        c.execute('DELETE FROM account_renewal_events WHERE account_id = ?', (account_id,))
        c.execute('DELETE FROM account_presences WHERE account_id = ?', (account_id,))
        c.execute('DELETE FROM account_activities WHERE account_id = ?', (account_id,))
        c.execute('DELETE FROM account_main_contacts WHERE account_id = ?', (account_id,))

        # Remove contatos e seus dados relacionados (FKs não são forçadas no SQLite)
        if client_ids:
            ph = ','.join('?' * len(client_ids))
            c.execute(f'DELETE FROM activities WHERE client_id IN ({ph})', client_ids)
            c.execute(f'DELETE FROM commitments WHERE client_id IN ({ph})', client_ids)
            c.execute(f'DELETE FROM environment_responses WHERE client_id IN ({ph})', client_ids)
            c.execute(f'DELETE FROM whatsapp_sync_log WHERE client_id IN ({ph})', client_ids)
            c.execute(f'UPDATE kanban_cards SET contact_id = NULL WHERE contact_id IN ({ph})', client_ids)
            c.execute(f'DELETE FROM clients WHERE id IN ({ph})', client_ids)

        c.execute('UPDATE kanban_cards SET account_id = NULL WHERE account_id = ?', (account_id,))
        c.execute('DELETE FROM accounts WHERE id = ?', (account_id,))
        conn.commit(); conn.close()
        return jsonify({'message': 'Conta arquivada e excluída', 'archived_contacts': len(clients)})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE /api/accounts/{account_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/archives', methods=['GET'])
def list_account_archives():
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('''SELECT id, account_name, contacts_count, activities_count, archived_at
                     FROM account_archives ORDER BY archived_at DESC, id DESC''')
        rows = [dict_from_row(r) for r in c.fetchall()]
        conn.close(); return jsonify(rows)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/accounts/archives: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/archives/<int:archive_id>/restore', methods=['POST'])
def restore_account_archive(archive_id):
    """Recria a conta arquivada, seus contatos e todo o histórico a partir do snapshot."""
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT * FROM account_archives WHERE id = ?', (archive_id,))
        arch = dict_from_row(c.fetchone())
        if not arch:
            conn.close(); return jsonify({'error': 'Arquivo não encontrado'}), 404
        snap = json.loads(arch['snapshot_json'])
        account = snap.get('account') or {}
        name = account.get('name') or arch['account_name']

        c.execute('SELECT id FROM accounts WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))', (name,))
        if c.fetchone():
            conn.close()
            return jsonify({'error': f'Já existe uma conta com o nome "{name}". Renomeie ou exclua a conta atual antes de restaurar.'}), 409

        c.execute('''INSERT INTO accounts (name, logo_url, is_target, sector, average_revenue_cents, professionals_count, global_presence, created_at, updated_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), CURRENT_TIMESTAMP)''',
                  (name, account.get('logo_url'), account.get('is_target', 0), account.get('sector'),
                   account.get('average_revenue_cents'), account.get('professionals_count'),
                   account.get('global_presence'), account.get('created_at')))
        new_account_id = c.lastrowid

        # Recria os contatos (clients), mapeando id antigo -> novo
        client_id_map = {}
        for cl in snap.get('clients', []):
            c.execute('''INSERT INTO clients (name, company, position, area_of_activity, email, phone, linkedin, photo_url, is_target, is_cold_contact, is_archived, created_at, updated_at)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), CURRENT_TIMESTAMP)''',
                      (cl.get('name'), name, cl.get('position'), cl.get('area_of_activity'), cl.get('email'),
                       cl.get('phone'), cl.get('linkedin'), cl.get('photo_url'), cl.get('is_target', 0),
                       cl.get('is_cold_contact', 0), cl.get('is_archived', 0), cl.get('created_at')))
            client_id_map[cl.get('id')] = c.lastrowid

        # Atividades dos contatos
        activity_id_map = {}
        for a in snap.get('client_activities', []):
            new_cid = client_id_map.get(a.get('client_id'))
            if not new_cid:
                continue
            c.execute('''INSERT INTO activities (client_id, contact_type, information, description, activity_date, created_at)
                         VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))''',
                      (new_cid, a.get('contact_type', 'Outro'), a.get('information'), a.get('description'),
                       a.get('activity_date'), a.get('created_at')))
            activity_id_map[a.get('id')] = c.lastrowid

        # Compromissos (agenda)
        for cm in snap.get('client_commitments', []):
            new_cid = client_id_map.get(cm.get('client_id'))
            if not new_cid:
                continue
            new_aid = activity_id_map.get(cm.get('activity_id')) if cm.get('activity_id') else None
            c.execute('''INSERT INTO commitments (client_id, activity_id, title, notes, due_date, due_time, source_type, created_at)
                         VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))''',
                      (new_cid, new_aid, cm.get('title'), cm.get('notes'), cm.get('due_date'),
                       cm.get('due_time'), cm.get('source_type', 'activity'), cm.get('created_at')))

        # Respostas de mapeamento de ambiente
        for er in snap.get('client_env_responses', []):
            new_cid = client_id_map.get(er.get('client_id'))
            if not new_cid:
                continue
            c.execute('INSERT OR IGNORE INTO environment_responses (card_id, client_id, response, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)',
                      (er.get('card_id'), new_cid, er.get('response')))

        # Pontos focais principais
        for mc in snap.get('main_contacts', []):
            new_cid = client_id_map.get(mc.get('client_id'))
            if not new_cid:
                continue
            c.execute('INSERT OR IGNORE INTO account_main_contacts (account_id, client_id) VALUES (?, ?)', (new_account_id, new_cid))

        # Presenças (serviços Stefanini)
        presence_id_map = {}
        for p in snap.get('presences', []):
            focal = client_id_map.get(p.get('focal_client_id')) if p.get('focal_client_id') else None
            c.execute('''INSERT INTO account_presences (account_id, delivery_name, stf_owner, delivery_cell, service_id, billing_type, validity_month, contract_duration_months, contract_end_date, early_terminated, current_revenue_cents, focal_client_id, created_at, updated_at)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), CURRENT_TIMESTAMP)''',
                      (new_account_id, p.get('delivery_name'), p.get('stf_owner'), p.get('delivery_cell'),
                       p.get('service_id'), p.get('billing_type', 'Mensal'), p.get('validity_month'),
                       p.get('contract_duration_months'), p.get('contract_end_date'), p.get('early_terminated', 0),
                       p.get('current_revenue_cents'), focal, p.get('created_at')))
            presence_id_map[p.get('id')] = c.lastrowid

        # Eventos de renovação
        for ev in snap.get('renewal_events', []):
            new_pid = presence_id_map.get(ev.get('presence_id'))
            if not new_pid:
                continue
            c.execute('INSERT OR IGNORE INTO account_renewal_events (account_id, presence_id, title, due_date, due_time, created_at) VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))',
                      (new_account_id, new_pid, ev.get('title'), ev.get('due_date'), ev.get('due_time', '09:00'), ev.get('created_at')))

        # Atividades genéricas da conta
        for aa in snap.get('account_activities', []):
            c.execute('INSERT INTO account_activities (account_id, description, activity_date, created_at) VALUES (?, ?, COALESCE(?, CURRENT_TIMESTAMP), COALESCE(?, CURRENT_TIMESTAMP))',
                      (new_account_id, aa.get('description'), aa.get('activity_date'), aa.get('created_at')))

        c.execute('DELETE FROM account_archives WHERE id = ?', (archive_id,))
        conn.commit(); conn.close()
        return jsonify({'message': 'Conta restaurada', 'account_id': new_account_id})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/accounts/archives/{archive_id}/restore: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/archives/<int:archive_id>', methods=['DELETE'])
def delete_account_archive(archive_id):
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('DELETE FROM account_archives WHERE id = ?', (archive_id,))
        conn.commit(); conn.close()
        return jsonify({'message': 'Arquivo excluído'})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE /api/accounts/archives/{archive_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/<int:account_id>/presences', methods=['POST'])
def create_account_presence(account_id):
    try:
        data = request.get_json() or {}
        delivery_name = (data.get('delivery_name') or '').strip()
        if not delivery_name:
            return jsonify({'error': 'Nome da Entrega é obrigatório'}), 400
        stf_owner = (data.get('stf_owner') or '').strip() or None
        delivery_cell = (data.get('delivery_cell') or '').strip() or None
        service_id = (data.get('service_id') or '').strip() or None
        billing_type = (data.get('billing_type') or 'Mensal').strip()
        validity_month = (data.get('validity_month') or '').strip() or None  # agora = início do contrato
        contract_duration_months_raw = data.get('contract_duration_months')
        try:
            contract_duration_months = int(contract_duration_months_raw) if contract_duration_months_raw not in (None, '') else None
        except (ValueError, TypeError):
            contract_duration_months = None
        early_terminated = 1 if str(data.get('early_terminated', '0')) in ('1', 'true', 'sim', 'Sim') else 0
        # Calcula data de encerramento automaticamente
        contract_end_date = None
        if validity_month and contract_duration_months:
            try:
                from dateutil.relativedelta import relativedelta
                start_dt = datetime.strptime(validity_month + '-01', '%Y-%m-%d')
                end_dt = start_dt + relativedelta(months=contract_duration_months)
                contract_end_date = end_dt.strftime('%Y-%m')
            except Exception:
                try:
                    import calendar
                    y, m = int(validity_month[:4]), int(validity_month[5:7])
                    total = (y * 12 + m - 1) + contract_duration_months
                    contract_end_date = f"{total // 12:04d}-{total % 12 + 1:02d}"
                except Exception:
                    contract_end_date = None
        current_revenue_cents = parse_currency_to_cents(data.get('current_revenue'))
        focal_client_id = data.get('focal_client_id')
        focal_client_id = int(focal_client_id) if str(focal_client_id).isdigit() else None
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT name FROM accounts WHERE id = ?', (account_id,))
        account = c.fetchone()
        if not account:
            conn.close(); return jsonify({'error': 'Conta não encontrada'}), 404
        c.execute('''INSERT INTO account_presences (account_id, delivery_name, stf_owner, delivery_cell, service_id, billing_type, validity_month, contract_duration_months, contract_end_date, early_terminated, current_revenue_cents, focal_client_id, updated_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                  (account_id, delivery_name, stf_owner, delivery_cell, service_id, billing_type, validity_month, contract_duration_months, contract_end_date, early_terminated, current_revenue_cents, focal_client_id))
        presence_id = c.lastrowid
        c.execute('SELECT * FROM account_presences WHERE id = ?', (presence_id,))
        presence = dict_from_row(c.fetchone())
        _create_or_update_presence_event(c, account['name'], account_id, presence)
        conn.commit(); conn.close()
        return jsonify(presence), 201
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/accounts/{account_id}/presences: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/<int:account_id>/presences/<int:presence_id>', methods=['PUT'])
def update_account_presence(account_id, presence_id):
    try:
        data = request.get_json() or {}
        delivery_name = (data.get('delivery_name') or '').strip()
        if not delivery_name:
            return jsonify({'error': 'Nome da Entrega é obrigatório'}), 400
        stf_owner = (data.get('stf_owner') or '').strip() or None
        delivery_cell = (data.get('delivery_cell') or '').strip() or None
        service_id = (data.get('service_id') or '').strip() or None
        billing_type = (data.get('billing_type') or 'Mensal').strip()
        validity_month = (data.get('validity_month') or '').strip() or None
        contract_duration_months_raw = data.get('contract_duration_months')
        try:
            contract_duration_months = int(contract_duration_months_raw) if contract_duration_months_raw not in (None, '') else None
        except (ValueError, TypeError):
            contract_duration_months = None
        early_terminated = 1 if str(data.get('early_terminated', '0')) in ('1', 'true', 'sim', 'Sim') else 0
        contract_end_date = None
        if validity_month and contract_duration_months:
            try:
                from dateutil.relativedelta import relativedelta
                start_dt = datetime.strptime(validity_month + '-01', '%Y-%m-%d')
                end_dt = start_dt + relativedelta(months=contract_duration_months)
                contract_end_date = end_dt.strftime('%Y-%m')
            except Exception:
                try:
                    y, m = int(validity_month[:4]), int(validity_month[5:7])
                    total = (y * 12 + m - 1) + contract_duration_months
                    contract_end_date = f"{total // 12:04d}-{total % 12 + 1:02d}"
                except Exception:
                    contract_end_date = None
        current_revenue_cents = parse_currency_to_cents(data.get('current_revenue'))
        focal_client_id = data.get('focal_client_id')
        focal_client_id = int(focal_client_id) if str(focal_client_id).isdigit() else None
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT name FROM accounts WHERE id = ?', (account_id,))
        account = c.fetchone()
        if not account:
            conn.close(); return jsonify({'error': 'Conta não encontrada'}), 404
        c.execute('''UPDATE account_presences
                     SET delivery_name=?, stf_owner=?, delivery_cell=?, service_id=?, billing_type=?, validity_month=?, contract_duration_months=?, contract_end_date=?, early_terminated=?, current_revenue_cents=?, focal_client_id=?, updated_at=CURRENT_TIMESTAMP
                     WHERE id=? AND account_id=?''',
                  (delivery_name, stf_owner, delivery_cell, service_id, billing_type, validity_month, contract_duration_months, contract_end_date, early_terminated, current_revenue_cents, focal_client_id, presence_id, account_id))
        c.execute('SELECT * FROM account_presences WHERE id = ? AND account_id = ?', (presence_id, account_id))
        presence = dict_from_row(c.fetchone())
        if presence:
            _create_or_update_presence_event(c, account['name'], account_id, presence)
        conn.commit(); conn.close()
        return jsonify(presence or {'message': 'Atualizada'})
    except Exception as e:
        logger.exception(f'[ERROR] PUT /api/accounts/{account_id}/presences/{presence_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/<int:account_id>/presences/<int:presence_id>', methods=['DELETE'])
def delete_account_presence(account_id, presence_id):
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('DELETE FROM account_renewal_events WHERE presence_id = ?', (presence_id,))
        c.execute('DELETE FROM account_presences WHERE id = ? AND account_id = ?', (presence_id, account_id))
        conn.commit(); conn.close()
        return jsonify({'message': 'Presença removida'})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE /api/accounts/{account_id}/presences/{presence_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/<int:account_id>/activities', methods=['GET'])
def get_account_activities(account_id):
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT id FROM accounts WHERE id = ?', (account_id,))
        if not c.fetchone():
            conn.close(); return jsonify({'error': 'Conta não encontrada'}), 404
        c.execute('''SELECT id, account_id, description, activity_date, created_at
                     FROM account_activities
                     WHERE account_id = ?
                     ORDER BY activity_date DESC, created_at DESC
                     LIMIT 100''', (account_id,))
        rows = [dict_from_row(r) for r in c.fetchall()]
        conn.close(); return jsonify(rows)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/accounts/{account_id}/activities: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/<int:account_id>/activities', methods=['POST'])
def create_account_activity(account_id):
    try:
        data = request.get_json() or {}
        description = (data.get('description') or '').strip()
        activity_date = (data.get('activity_date') or '').strip() or None
        if not description:
            return jsonify({'error': 'Descrição é obrigatória'}), 400
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT id FROM accounts WHERE id = ?', (account_id,))
        if not c.fetchone():
            conn.close(); return jsonify({'error': 'Conta não encontrada'}), 404
        if activity_date:
            c.execute('''INSERT INTO account_activities (account_id, description, activity_date)
                         VALUES (?, ?, ?)''', (account_id, description, activity_date))
        else:
            c.execute('''INSERT INTO account_activities (account_id, description)
                         VALUES (?, ?)''', (account_id, description))
        conn.commit()
        activity_id = c.lastrowid
        conn.close()
        return jsonify({'id': activity_id, 'message': 'Atividade registrada'}), 201
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/accounts/{account_id}/activities: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/<int:account_id>/activities/<int:activity_id>', methods=['DELETE'])
def delete_account_activity(account_id, activity_id):
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('DELETE FROM account_activities WHERE id = ? AND account_id = ?', (activity_id, account_id))
        conn.commit(); conn.close()
        return jsonify({'message': 'Atividade removida'})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE /api/accounts/{account_id}/activities/{activity_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/uploads/accounts/<filename>')
def serve_account_upload(filename):
    return send_from_directory(str(ACCOUNT_UPLOAD_DIR), filename)


# ===========================================================================
# Account Planning — mapeamento de decisores com IA (Bloco 4)
# Busca via Tavily (site:linkedin.com/in), sem scraping do LinkedIn.
# ===========================================================================

_ACCOUNT_PLANNING_TARGETS = [
    # (rótulo do cargo, termo de busca, máx. de candidatos)
    ('CEO', 'CEO', 3),
    ('CIO', 'CIO', 3),
    ('CMO', 'CMO', 3),
    ('COO', 'COO', 3),
    ('CISO', 'CISO', 3),
    ('CHRO (Diretor de RH)', 'Diretor de RH', 3),
    ('Diretor de TI', 'Diretor de TI', 5),
    ('Gerente de TI', 'Gerente de TI', 5),
    ('Profissional de Compras', 'Compras', 5),
]


def _ap_normalize_linkedin_url(url):
    u = (url or '').strip().lower()
    u = re.sub(r'^https?://', '', u)
    u = re.sub(r'^www\.', '', u)
    u = u.split('?')[0].split('#')[0].rstrip('/')
    return u


def _ap_parse_linkedin_title(title):
    """Extrai (nome, cargo) do título indexado do LinkedIn:
    padrão comum "Nome - Cargo - Empresa | LinkedIn"."""
    t = (title or '').strip()
    t = re.sub(r'\s*[|–]\s*LinkedIn\s*$', '', t, flags=re.I)
    t = re.sub(r'\s*\|\s*Professional Profile\s*$', '', t, flags=re.I)
    parts = [p.strip() for p in re.split(r'\s[-–—]\s', t) if p.strip()]
    if not parts:
        return None, None
    name = parts[0]
    position = parts[1] if len(parts) > 1 else None
    # Nome plausível: 2+ palavras, sem dígitos
    if not name or len(name.split()) < 2 or re.search(r'\d', name):
        return None, position
    return name, position


def _ap_normalize_with_llm(title, snippet, company):
    """Usa LLM só para normalizar nome/cargo a partir do texto do resultado —
    nunca como fonte da URL."""
    raw = _llm_openrouter_first(
        'A partir do título e trecho abaixo, vindos de um resultado de busca de um '
        'perfil público do LinkedIn, extraia o nome da pessoa e o cargo dela na '
        f'empresa "{company}". Retorne SOMENTE JSON válido no formato '
        '{"nome": "...", "cargo": "..."}. Use null se não conseguir identificar.\n\n'
        f'Título: {title}\nTrecho: {snippet}',
        log_tag='AccountPlanning'
    )
    if not raw:
        return None, None
    try:
        obj = _extract_json_object_from_text(raw) or json.loads(raw)
        return (obj.get('nome') or None), (obj.get('cargo') or None)
    except Exception as e:
        logger.debug(f'[AccountPlanning] LLM normalizador sem JSON válido: {e}')
        return None, None


def _account_planning_search_async(task_id, company, segment):
    try:
        api_key = _resolve_setting('tavily_api_key', 'TAVILY_API_KEY')
        _bg_task_set(task_id, {'step': 'Preparando busca de decisores...', 'progress': 5})

        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id, name, linkedin FROM clients WHERE linkedin IS NOT NULL AND TRIM(linkedin) != ''")
        existing = {_ap_normalize_linkedin_url(r['linkedin']): r['id'] for r in c.fetchall()}

        results = []
        seen_urls = set()
        total = len(_ACCOUNT_PLANNING_TARGETS)
        for i, (label, term, max_cands) in enumerate(_ACCOUNT_PLANNING_TARGETS):
            _bg_task_set(task_id, {
                'step': f'🔎 Buscando {label}... ({i + 1}/{total})',
                'progress': 5 + int((i / total) * 70)
            })
            query = f'site:linkedin.com/in "{term}" "{company}"'
            try:
                raw_results = _run_tavily_request(api_key, query, max_results=max_cands + 3)
            except Exception as e:
                logger.warning(f'[AccountPlanning] Tavily falhou para "{label}": {e}')
                continue
            added = 0
            for item in raw_results:
                if added >= max_cands:
                    break
                url = (item.get('url') or '').strip()
                if 'linkedin.com/in/' not in url.lower():
                    continue
                norm = _ap_normalize_linkedin_url(url)
                if norm in seen_urls:
                    continue  # mesma pessoa já apareceu em outro cargo
                title = item.get('title') or ''
                snippet = item.get('content') or ''
                name, position = _ap_parse_linkedin_title(title)
                if not name:
                    name, llm_position = _ap_normalize_with_llm(title, snippet, company)
                    position = position or llm_position
                if not name:
                    continue
                seen_urls.add(norm)
                client_id = existing.get(norm)
                results.append({
                    'target': label,
                    'name': name,
                    'position': position or label,
                    'linkedin': url,
                    'snippet': snippet[:280],
                    'already_registered': bool(client_id),
                    'client_id': client_id,
                    'photo_url': None,
                })
                added += 1

        # Foto (melhor esforço, com aviso de aproximação na UI)
        for j, cand in enumerate(results):
            if cand['already_registered']:
                continue
            _bg_task_set(task_id, {
                'step': f'🖼️ Buscando foto de {cand["name"]}... ({j + 1}/{len(results)})',
                'progress': 75 + int((j / max(len(results), 1)) * 20)
            })
            try:
                photos = _find_image_candidates_on_web(f'{cand["name"]} {company}', limit=1)
                cand['photo_url'] = photos[0] if photos else None
            except Exception as e:
                logger.debug(f'[AccountPlanning] foto indisponível para {cand["name"]}: {e}')

        payload = {
            'company': company,
            'segment': segment,
            'candidates': results,
        }
        c.execute('INSERT INTO account_planning_runs (company, segment, result_json) VALUES (?, ?, ?)',
                  (company, segment, json.dumps(payload, ensure_ascii=False)))
        conn.commit()
        run_id = c.lastrowid
        conn.close()
        payload['run_id'] = run_id

        _bg_task_set(task_id, {'status': 'done', 'step': 'Concluído!', 'progress': 100, 'result': payload})
        _bg_task_cleanup(task_id)
    except Exception as e:
        logger.exception(f'[AccountPlanning] Falha na busca: {e}')
        _bg_task_set(task_id, {'status': 'error', 'error': str(e), 'progress': 0})
        _bg_task_cleanup(task_id)


@app.route('/api/account-planning/search', methods=['POST'])
def account_planning_search():
    data = request.get_json(force=True) or {}
    company = (data.get('company') or '').strip()
    segment = (data.get('segment') or '').strip()
    if not company:
        return jsonify({'error': 'Informe o nome da empresa.'}), 400
    api_key = _resolve_setting('tavily_api_key', 'TAVILY_API_KEY')
    if not api_key:
        return jsonify({'error': 'A chave da Tavily não está configurada. Configure em Configurações > Integrações ou defina TAVILY_API_KEY no ambiente.'}), 400
    task_id = uuid.uuid4().hex
    _bg_task_register_persistent(task_id, 'account_planning')
    _bg_task_set(task_id, {'status': 'processing', 'step': 'Iniciando...', 'progress': 3})
    threading.Thread(target=_account_planning_search_async, args=(task_id, company, segment), daemon=True).start()
    return jsonify({'task_id': task_id}), 202


@app.route('/api/account-planning/tasks/<task_id>', methods=['GET'])
def account_planning_task_poll(task_id):
    task = _bg_task_get(task_id)
    if not task:
        return jsonify({'status': 'not_found'}), 404
    return jsonify(task)


@app.route('/api/account-planning/runs', methods=['GET'])
def account_planning_runs():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, company, segment, created_at FROM account_planning_runs ORDER BY id DESC LIMIT 20')
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route('/api/account-planning/runs/<int:run_id>', methods=['GET'])
def account_planning_run_detail(run_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, company, segment, result_json, created_at FROM account_planning_runs WHERE id = ?', (run_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Busca não encontrada'}), 404
    payload = json.loads(row['result_json'])
    payload['run_id'] = row['id']
    payload['created_at'] = row['created_at']
    return jsonify(payload)


@app.route('/api/account-planning/segments', methods=['GET'])
def account_planning_segments():
    """Sugestões de segmento a partir das áreas de atuação já cadastradas."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""SELECT DISTINCT TRIM(area_of_activity) AS seg FROM clients
                 WHERE area_of_activity IS NOT NULL AND TRIM(area_of_activity) != ''
                 ORDER BY seg""")
    rows = [r['seg'] for r in c.fetchall()]
    conn.close()
    return jsonify(rows)
