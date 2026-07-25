# -*- coding: utf-8 -*-
# Rotas do domínio "activities_agenda" (Bloco 3 — modularização).
# Este arquivo é executado no namespace de app.py por _load_route_modules():
# tem acesso a todos os helpers/globals de app.py e registra as rotas no
# mesmo objeto Flask `app`, com URLs idênticas às originais.

@app.route('/api/atividades', methods=['GET'])
def get_atividades():
    return get_activities()


@app.route('/api/activities', methods=['GET'])
def get_activities():
    try:
        conn = get_db()
        c = conn.cursor()
        _vw, _vp = visible_where('activities', alias='a')
        c.execute(f'''SELECT a.*, c.name, c.company, c.position FROM activities a
                     JOIN clients c ON a.client_id = c.id
                     WHERE {_vw}
                     ORDER BY a.activity_date DESC''', _vp)
        activities = [dict_from_row(row) for row in c.fetchall()]
        conn.close()
        return jsonify(activities)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/activities: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/atividades', methods=['POST'])
def create_atividade():
    try:
        logger.debug('[DEBUG] POST /api/atividades')
        # Aceitar tanto JSON quanto FormData
        if request.is_json:
            data = request.get_json()
            client_id = data.get('client_id')
            contact_type = data.get('contact_type', 'Outro')
            information = data.get('information', '').strip()
        else:
            client_id = request.form.get('client_id')
            contact_type = request.form.get('contact_type', 'Outro')
            information = request.form.get('information', '').strip()
        
        logger.debug(f'[DEBUG] client_id: {client_id}, contact_type: {contact_type}, information: {information}')
        
        if not client_id or not information:
            return jsonify({'error': 'Cliente e informacoes sao obrigatorios'}), 400
        
        conn = get_db()
        c = conn.cursor()
        
        # Verificar se cliente existe e é visível ao usuário
        c.execute('SELECT id FROM clients WHERE id = ?', (client_id,))
        if not c.fetchone() or not can_read('clients', client_id, c):
            conn.close()
            return jsonify({'error': 'Cliente nao encontrado'}), 404

        # Salvar com campos separados
        c.execute('''INSERT INTO activities (client_id, contact_type, information, owner_id)
                     VALUES (?, ?, ?, ?)''',
                  (client_id, contact_type, information, _acl_owner_for_insert()))
        conn.commit()
        activity_id = c.lastrowid

        # Detectar compromissos futuros no texto da atividade e registrar na agenda
        created_commitments = create_commitments_from_activity(c, client_id, activity_id, information)
        created_commitments = enrich_commitments_with_client_data(c, created_commitments, client_id)
        conn.commit()
        
        # Atualizar last_activity_date do cliente
        c.execute('''UPDATE clients SET last_activity_date = CURRENT_TIMESTAMP WHERE id = ?''',
                  (client_id,))
        conn.commit()
        conn.close()
        
        logger.debug(f'[DEBUG] Atividade criada com ID: {activity_id}')
        return jsonify({'id': activity_id, 'message': 'Atividade registrada', 'commitments_created': created_commitments}), 201
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/atividades: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/activities', methods=['POST'])
def create_activity():
    try:
        logger.debug('[DEBUG] POST /api/activities')
        data = request.get_json()
        logger.debug(f'[DEBUG] Data: {data}')
        
        client_id = data.get('client_id')
        description = data.get('description', '').strip()
        
        if not client_id or not description:
            return jsonify({'error': 'Cliente e descricao sao obrigatorios'}), 400
        
        conn = get_db()
        c = conn.cursor()
        
        # Verificar se cliente existe e é visível ao usuário
        c.execute('SELECT id FROM clients WHERE id = ?', (client_id,))
        if not c.fetchone() or not can_read('clients', client_id, c):
            conn.close()
            return jsonify({'error': 'Cliente nao encontrado'}), 404

        c.execute('''INSERT INTO activities (client_id, information, owner_id)
                     VALUES (?, ?, ?)''',
                  (client_id, description, _acl_owner_for_insert()))
        conn.commit()
        activity_id = c.lastrowid

        # Detectar compromissos futuros no texto da atividade e registrar na agenda
        created_commitments = create_commitments_from_activity(c, client_id, activity_id, description)
        created_commitments = enrich_commitments_with_client_data(c, created_commitments, client_id)
        conn.commit()
        
        # Atualizar last_activity_date do cliente
        c.execute('''UPDATE clients SET last_activity_date = CURRENT_TIMESTAMP WHERE id = ?''',
                  (client_id,))
        conn.commit()
        conn.close()
        
        logger.debug(f'[DEBUG] Atividade criada com ID: {activity_id}')
        return jsonify({'id': activity_id, 'message': 'Atividade registrada', 'commitments_created': created_commitments}), 201
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/activities: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/atividades/<int:activity_id>', methods=['PUT'])
def update_atividade(activity_id):
    try:
        logger.debug(f'[DEBUG] PUT /api/atividades/{activity_id}')
        # Aceitar tanto JSON quanto FormData
        if request.is_json:
            data = request.get_json()
            contact_type = data.get('contact_type', 'Outro')
            information = data.get('information', '').strip()
        else:
            contact_type = request.form.get('contact_type', 'Outro')
            information = request.form.get('information', '').strip()
        
        if not information:
            return jsonify({'error': 'Informacoes sao obrigatorias'}), 400
        
        conn = get_db()
        c = conn.cursor()
        if not can_read('activities', activity_id, c):
            conn.close()
            return jsonify({'error': 'Atividade não encontrada'}), 404
        if not can_write('activities', activity_id, c):
            conn.close()
            return jsonify({'error': 'Sem permissão para editar esta atividade.', 'error_type': 'forbidden'}), 403
        c.execute('''UPDATE activities SET contact_type = ?, information = ? WHERE id = ?''',
                  (contact_type, information, activity_id))
        conn.commit()
        conn.close()
        
        logger.debug(f'[DEBUG] Atividade {activity_id} atualizada')
        return jsonify({'message': 'Atividade atualizada'})
    except Exception as e:
        logger.exception(f'[ERROR] PUT /api/atividades/{activity_id}: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/atividades/<int:activity_id>', methods=['DELETE'])
def delete_atividade(activity_id):
    return delete_activity(activity_id)


@app.route('/api/activities/<int:activity_id>', methods=['DELETE'])
def delete_activity(activity_id):
    try:
        conn = get_db()
        c = conn.cursor()
        if not can_read('activities', activity_id, c):
            conn.close()
            return jsonify({'error': 'Atividade não encontrada'}), 404
        if not can_write('activities', activity_id, c):
            conn.close()
            return jsonify({'error': 'Sem permissão para excluir esta atividade.', 'error_type': 'forbidden'}), 403
        c.execute('DELETE FROM activities WHERE id = ?', (activity_id,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Atividade deletada'})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE /api/activities/{activity_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/agenda', methods=['GET'])
def get_agenda():
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        conn = get_db()
        c = conn.cursor()

        _vcm, _pcm = visible_where('commitments', alias='cm')
        _vev, _pev = visible_where('account_renewal_events', alias='ev')
        query = f'''SELECT CAST(cm.id AS TEXT) as id, cm.client_id, cm.activity_id, cm.title, cm.notes, cm.due_date, cm.due_time, cm.source_type,
                          cl.name as client_name, cl.company as client_company, cl.position as client_position, cl.email as client_email, cl.photo_url as client_photo
                   FROM commitments cm
                   JOIN clients cl ON cm.client_id = cl.id
                   WHERE {_vcm}'''
        params = list(_pcm)

        if start_date and end_date:
            query += ' AND DATE(cm.due_date) >= ? AND DATE(cm.due_date) <= ?'
            params.extend([start_date, end_date])

        query += f''' UNION ALL SELECT 'acc-' || CAST(ev.id AS TEXT) as id, NULL as client_id, NULL as activity_id, ev.title, ev.title as notes, ev.due_date, ev.due_time, 'account_presence' as source_type,
                          ac.name as client_name, ac.name as client_company, 'Conta' as client_position, NULL as client_email, ac.logo_url as client_photo
                   FROM account_renewal_events ev
                   JOIN accounts ac ON ev.account_id = ac.id
                   WHERE {_vev}'''
        params.extend(_pev)
        if start_date and end_date:
            query += ' AND DATE(ev.due_date) >= ? AND DATE(ev.due_date) <= ?'
            params.extend([start_date, end_date])

        query += ' ORDER BY due_date ASC, id ASC'
        c.execute(query, params)
        items = [dict_from_row(row) for row in c.fetchall()]
        conn.close()
        return jsonify(items)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/agenda: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/agenda', methods=['POST'])
def create_agenda_item():
    try:
        data = request.get_json() or {}
        client_id = data.get('client_id')
        due_date = (data.get('due_date') or '').strip()
        due_time = (data.get('due_time') or '').strip() or None
        title = (data.get('title') or '').strip()
        notes = (data.get('notes') or '').strip()

        if not client_id or not due_date:
            return jsonify({'error': 'Cliente e data são obrigatórios'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM clients WHERE id = ?', (client_id,))
        if not c.fetchone() or not can_read('clients', client_id, c):
            conn.close()
            return jsonify({'error': 'Cliente não encontrado'}), 404

        c.execute('''INSERT INTO commitments (client_id, title, notes, due_date, due_time, source_type, owner_id)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (client_id, title or 'Agenda manual', notes or title or 'Agenda manual', due_date, due_time, 'manual', _acl_owner_for_insert()))
        commitment_id = c.lastrowid
        conn.commit()

        c.execute('''SELECT cm.*, cl.name as client_name, cl.company as client_company, cl.position as client_position, cl.email as client_email, cl.photo_url as client_photo
                     FROM commitments cm JOIN clients cl ON cm.client_id = cl.id WHERE cm.id = ?''', (commitment_id,))
        item = dict_from_row(c.fetchone())
        conn.close()
        return jsonify({'message': 'Compromisso criado', 'item': item}), 201
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/agenda: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/agenda/<int:commitment_id>/time', methods=['PUT'])
def update_agenda_time(commitment_id):
    try:
        data = request.get_json() or {}
        due_time = (data.get('due_time') or '').strip()
        if not due_time:
            return jsonify({'error': 'Horário obrigatório'}), 400

        conn = get_db()
        c = conn.cursor()
        if not can_read('commitments', commitment_id, c):
            conn.close()
            return jsonify({'error': 'Compromisso não encontrado'}), 404
        if not can_write('commitments', commitment_id, c):
            conn.close()
            return jsonify({'error': 'Sem permissão para editar este compromisso.', 'error_type': 'forbidden'}), 403
        c.execute('UPDATE commitments SET due_time = ? WHERE id = ?', (due_time, commitment_id))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Horário atualizado'})
    except Exception as e:
        logger.exception(f'[ERROR] PUT /api/agenda/{commitment_id}/time: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/agenda/<int:commitment_id>', methods=['DELETE'])
def delete_agenda_item(commitment_id):
    try:
        conn = get_db()
        c = conn.cursor()
        if not can_read('commitments', commitment_id, c):
            conn.close()
            return jsonify({'error': 'Compromisso não encontrado'}), 404
        if not can_write('commitments', commitment_id, c):
            conn.close()
            return jsonify({'error': 'Sem permissão para excluir este compromisso.', 'error_type': 'forbidden'}), 403
        c.execute('DELETE FROM commitments WHERE id = ?', (commitment_id,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Compromisso removido'})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE /api/agenda/{commitment_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/agenda/<int:commitment_id>/ics', methods=['GET'])
def download_agenda_ics(commitment_id):
    try:
        attendee = (request.args.get('attendee') or '').strip()
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT cm.*, cl.name as client_name, cl.company as client_company, cl.email as client_email FROM commitments cm JOIN clients cl ON cm.client_id = cl.id WHERE cm.id = ?', (commitment_id,))
        item = dict_from_row(c.fetchone())
        if item and not can_read('commitments', commitment_id, c):
            item = None  # existe, mas não é visível → 404
        conn.close()

        if not item:
            return jsonify({'error': 'Compromisso não encontrado'}), 404

        due_date = item.get('due_date')
        due_time = item.get('due_time') or '09:00'
        dtstart = datetime.fromisoformat(f"{due_date}T{due_time}:00")
        dtend = dtstart + timedelta(hours=1)

        uid = f"toca-{commitment_id}@local"
        stamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
        start = dtstart.strftime('%Y%m%dT%H%M%S')
        end = dtend.strftime('%Y%m%dT%H%M%S')
        summary = (item.get('title') or 'Compromisso').replace('\n', ' ')
        description = (item.get('notes') or '').replace('\n', '\\n')

        attendee_lines = ''
        if attendee:
            attendee_lines = f"ATTENDEE;CN={attendee}:mailto:{attendee}\r\n"

        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Toca do Coelho//Agenda//PT-BR\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            f"DTSTAMP:{stamp}\r\n"
            f"DTSTART:{start}\r\n"
            f"DTEND:{end}\r\n"
            f"SUMMARY:{summary}\r\n"
            f"DESCRIPTION:{description}\r\n"
            f"LOCATION:{item.get('client_company') or ''}\r\n"
            f"{attendee_lines}"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )

        from flask import Response
        response = Response(ics, mimetype='text/calendar')
        response.headers['Content-Disposition'] = f'attachment; filename=agenda-{commitment_id}.ics'
        return response
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/agenda/{commitment_id}/ics: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/agenda/semana-atual-count', methods=['GET'])
def get_week_commitments_count():
    try:
        today = datetime.now().date()
        start_week = today - timedelta(days=today.weekday())
        end_week = start_week + timedelta(days=6)

        conn = get_db()
        c = conn.cursor()
        _vw, _vp = visible_where('commitments')
        c.execute(f'''SELECT COUNT(*) as total FROM commitments
                     WHERE DATE(due_date) >= ? AND DATE(due_date) <= ? AND {_vw}''',
                  [start_week.isoformat(), end_week.isoformat()] + _vp)
        total = c.fetchone()['total']
        conn.close()

        return jsonify({
            'total': total,
            'start_week': start_week.isoformat(),
            'end_week': end_week.isoformat()
        })
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/agenda/semana-atual-count: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/export/atividades', methods=['GET'])
def export_atividades():
    try:
        import csv
        from io import StringIO
        
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        conn = get_db()
        c = conn.cursor()
        
        _vw, _vp = visible_where('activities', alias='a')
        if start_date and end_date:
            c.execute(f'''SELECT a.id, c.name, c.company, c.position, a.description, a.created_at
                        FROM activities a
                        JOIN clients c ON a.client_id = c.id
                        WHERE DATE(a.created_at) >= ? AND DATE(a.created_at) <= ? AND {_vw}
                        ORDER BY a.created_at DESC''',
                     [start_date, end_date] + _vp)
        else:
            c.execute(f'''SELECT a.id, c.name, c.company, c.position, a.description, a.created_at
                        FROM activities a
                        JOIN clients c ON a.client_id = c.id
                        WHERE {_vw}
                        ORDER BY a.created_at DESC''', _vp)
        
        rows = c.fetchall()
        conn.close()
        
        # Criar CSV em memoria
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'Cliente', 'Empresa', 'Cargo', 'Informacoes', 'Data'])
        
        for row in rows:
            writer.writerow([
                row['id'],
                row['name'],
                row['company'],
                row['position'],
                row['description'],
                row['created_at']
            ])
        
        # Retornar como arquivo
        from flask import Response
        response = Response(output.getvalue(), mimetype='text/csv')
        response.headers['Content-Disposition'] = 'attachment; filename=atividades.csv'
        return response
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/export/atividades: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/commitments/alerts', methods=['GET'])
def commitments_alerts():
    """Follow-ups do dia e vencidos (Bloco 7) — usados no banner da Home
    e na notificação nativa do Windows via launcher/tray."""
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        conn = get_db()
        c = conn.cursor()
        _vw, _vp = visible_where('commitments', alias='co')
        c.execute(f"""
            SELECT co.id, co.title, co.due_date, co.due_time, cl.name, cl.company,
                   CASE WHEN co.due_date < ? THEN 'overdue' ELSE 'today' END AS kind
            FROM commitments co
            JOIN clients cl ON cl.id = co.client_id
            WHERE COALESCE(cl.is_archived, 0) = 0
              AND co.due_date <= ?
              AND {_vw}
              AND NOT EXISTS (SELECT 1 FROM activities a
                              WHERE a.client_id = co.client_id
                                AND date(a.activity_date) >= co.due_date)
            ORDER BY co.due_date ASC, co.due_time ASC
        """, [today, today] + _vp)
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return jsonify({
            'today': [r for r in rows if r['kind'] == 'today'],
            'overdue': [r for r in rows if r['kind'] == 'overdue'],
        })
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/commitments/alerts: {e}')
        return jsonify({'error': str(e)}), 500


# ===========================================================================
# Briefing pré-reunião automático + envio matinal por e-mail (Bloco 13)
# ===========================================================================

def _briefing_header_info(c, commitment):
    """Contato (nome/foto) e conta (nome/logo) para o cabeçalho do briefing."""
    c.execute('SELECT id, name, position, company, photo_url FROM clients WHERE id = ?',
              (commitment['client_id'],))
    cl = dict_from_row(c.fetchone()) or {}
    account = None
    if cl.get('company'):
        c.execute('SELECT id, name, logo_url FROM accounts WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))',
                  (cl['company'],))
        account = dict_from_row(c.fetchone())
    return {
        'client': {'id': cl.get('id'), 'name': cl.get('name'), 'position': cl.get('position'),
                   'company': cl.get('company'), 'photo_url': cl.get('photo_url')},
        'account': account,
    }


def _briefing_gather_context(c, commitment, acl_user=None):
    """Agrega todo o contexto conhecido do contato/conta para o briefing. Os
    dados por-dono (atividades, cards de Kanban) são escopados ao `acl_user`
    autorizado — o briefing nunca resume dado privado de outro usuário."""
    client_id = commitment['client_id']
    c.execute('SELECT * FROM clients WHERE id = ?', (client_id,))
    client = dict_from_row(c.fetchone()) or {}
    parts = [
        f"Reunião: {commitment['title']} em {commitment['due_date']}"
        + (f" às {commitment['due_time']}" if commitment.get('due_time') else ''),
        f"Contato: {client.get('name')} — {client.get('position') or ''} na {client.get('company') or ''}",
    ]
    _avw, _avp = visible_where('activities', user=acl_user)
    c.execute(f"""SELECT contact_type, information, activity_date FROM activities
                 WHERE client_id = ? AND {_avw} ORDER BY activity_date DESC LIMIT 5""",
              [client_id] + _avp)
    acts = c.fetchall()
    if acts:
        parts.append('Últimas atividades:\n' + '\n'.join(
            f"- {(a['activity_date'] or '')[:10]} ({a['contact_type']}): {(a['information'] or '')[:250]}"
            for a in acts))
    c.execute(f"""SELECT information FROM activities
                 WHERE client_id = ? AND contact_type = 'WhatsApp' AND {_avw}
                 ORDER BY activity_date DESC LIMIT 1""", [client_id] + _avp)
    wa = c.fetchone()
    if wa:
        parts.append(f"Último resumo de WhatsApp:\n{(wa['information'] or '')[:400]}")
    _kow, _kop = owned_where('kanban_cards', alias='k', user=acl_user)
    c.execute(f"""SELECT k.title, k.description, k.urgency FROM kanban_cards k
                 LEFT JOIN kanban_columns col ON col.id = k.column_id
                 WHERE (k.contact_id = ? OR k.account_id IN (
                        SELECT id FROM accounts WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))))
                   AND LOWER(COALESCE(col.title, '')) NOT LIKE '%conclu%'
                   AND {_kow}
                 LIMIT 5""", [client_id, client.get('company') or ''] + _kop)
    cards = c.fetchall()
    if cards:
        parts.append('Cards de Kanban abertos:\n' + '\n'.join(
            f"- [{k['urgency']}] {k['title']}: {(k['description'] or '')[:150]}" for k in cards))
    c.execute("""SELECT ec.title, er.response FROM environment_responses er
                 JOIN environment_cards ec ON ec.id = er.card_id
                 WHERE er.client_id = ? AND er.response IS NOT NULL AND TRIM(er.response) != ''
                 LIMIT 8""", (client_id,))
    env = c.fetchall()
    if env:
        parts.append('Mapeamento de ambiente:\n' + '\n'.join(
            f"- {e['title']}: {(e['response'] or '')[:150]}" for e in env))
    c.execute('SELECT id FROM accounts WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))',
              (client.get('company') or '',))
    acc = c.fetchone()
    if acc:
        try:
            ws = _account_whitespace(c, acc['id'])
            if ws['present'] or ws['missing']:
                parts.append(
                    f"Ofertas na conta: {', '.join(o['title'] for o in ws['present']) or 'nenhuma'} | "
                    f"Whitespace (nunca exploradas): {', '.join(o['title'] for o in ws['missing'][:4]) or '-'}")
            ts = _account_thread_score(c, acc['id'], client.get('company'), 1)
            parts.append(f"Multithreading: {ts['active_contacts']} contato(s) ativo(s) na conta"
                         + (' — risco de concentração' if ts['single_threaded'] else ''))
        except Exception as e:
            logger.debug(f'[Briefing] contexto de conta indisponível: {e}')
    return '\n\n'.join(parts), client


def _generate_briefing(c, commitment, force=False, acl_user=None):
    """Gera (ou retorna do cache) o briefing estruturado de um compromisso."""
    if not force:
        c.execute('SELECT content_md, generated_at FROM meeting_briefings WHERE commitment_id = ?',
                  (commitment['id'],))
        cached = c.fetchone()
        if cached:
            return {'content': cached['content_md'], 'generated_at': cached['generated_at'], 'cached': True}
    context, client = _briefing_gather_context(c, commitment, acl_user=acl_user)
    raw = _llm_prompt(
        'Você é um assistente de vendas B2B. Com base no contexto abaixo, escreva um briefing '
        'pré-reunião em português do Brasil, em markdown, com EXATAMENTE estas seções '
        '(use "## " antes de cada título): Contexto, Últimos assuntos, Pendências suas, '
        'Pendências dele, Oportunidades em aberto, Sugestão de pauta. '
        'Seja conciso (2 a 4 bullets por seção). Se não houver dado para uma seção, escreva '
        'uma linha útil mesmo assim (ex.: sugerir levantar a informação na reunião).\n\n'
        f'CONTEXTO:\n{context}',
        log_tag='Briefing'
    )
    if not raw:
        raise RuntimeError('Nenhum provedor de LLM configurado ou disponível para gerar o briefing.')
    content = raw.strip()
    c.execute("""INSERT INTO meeting_briefings (commitment_id, content_md, generated_at)
                 VALUES (?, ?, CURRENT_TIMESTAMP)
                 ON CONFLICT(commitment_id) DO UPDATE SET content_md = excluded.content_md,
                 generated_at = CURRENT_TIMESTAMP""", (commitment['id'], content))
    return {'content': content, 'generated_at': datetime.now().isoformat(timespec='seconds'), 'cached': False}


@app.route('/api/commitments/<int:commitment_id>/briefing', methods=['GET'])
def commitment_briefing_get(commitment_id):
    """Retorna o briefing do cache (rápido); 404 se ainda não gerado."""
    conn = get_db()
    c = conn.cursor()
    if not can_read('commitments', commitment_id, c):
        conn.close()
        return jsonify({'error': 'Briefing ainda não gerado'}), 404
    c.execute('SELECT content_md, generated_at FROM meeting_briefings WHERE commitment_id = ?', (commitment_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Briefing ainda não gerado'}), 404
    c.execute('SELECT * FROM commitments WHERE id = ?', (commitment_id,))
    commitment = dict_from_row(c.fetchone())
    header = _briefing_header_info(c, commitment) if commitment else {}
    conn.close()
    return jsonify({'content': row['content_md'], 'generated_at': row['generated_at'],
                    'cached': True, **header})


def _briefing_task_async(task_id, commitment_id, force, acl_user=None):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM commitments WHERE id = ?', (commitment_id,))
        commitment = dict_from_row(c.fetchone())
        if not commitment:
            raise RuntimeError('Compromisso não encontrado.')
        _bg_task_set(task_id, {'step': '🧠 Reunindo contexto e gerando briefing...', 'progress': 30})
        result = _generate_briefing(c, commitment, force=force, acl_user=acl_user)
        result.update(_briefing_header_info(c, commitment))
        conn.commit()
        conn.close()
        _bg_task_set(task_id, {'status': 'done', 'progress': 100, 'step': 'Concluído!', 'result': result})
        _bg_task_cleanup(task_id)
    except Exception as e:
        logger.exception(f'[Briefing] Falha: {e}')
        _bg_task_set(task_id, {'status': 'error', 'error': str(e)})
        _bg_task_cleanup(task_id)


@app.route('/api/commitments/<int:commitment_id>/briefing', methods=['POST'])
def commitment_briefing_generate(commitment_id):
    """Gera o briefing (task assíncrona). ?refresh=1 força regeração."""
    if not can_read('commitments', commitment_id):
        return jsonify({'error': 'Compromisso não encontrado'}), 404
    force = request.args.get('refresh') == '1' or (request.get_json(silent=True) or {}).get('refresh')
    task_id = uuid.uuid4().hex
    acl_user = current_user()  # capturado no request p/ a thread aplicar visibilidade
    _bg_task_register_persistent(task_id, 'briefing')
    _bg_task_set(task_id, {'status': 'processing', 'step': 'Iniciando...', 'progress': 5})
    threading.Thread(target=_briefing_task_async, args=(task_id, commitment_id, bool(force), acl_user), daemon=True).start()
    return jsonify({'task_id': task_id}), 202


def _briefings_to_pdf(title, sections):
    """Compila seções markdown em um PDF simples. sections: [(subtitulo, texto_md)].
    Retorna bytes do PDF, ou None se o reportlab não estiver disponível."""
    try:
        from io import BytesIO
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    except Exception as e:
        logger.warning(f'[Briefing] reportlab indisponível para PDF: {e}')
        return None
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    styles = getSampleStyleSheet()
    story = [Paragraph(html.escape(title), styles['Title']), Spacer(1, 8)]
    for subtitle, text in sections:
        story.append(Paragraph(html.escape(subtitle), styles['Heading2']))
        for line in (text or '').split('\n'):
            line = line.strip()
            if not line:
                continue
            esc = html.escape(line)
            if line.startswith('## '):
                story.append(Paragraph(f'<b>{html.escape(line[3:])}</b>', styles['Heading4']))
            elif line.startswith(('- ', '* ')):
                story.append(Paragraph('• ' + esc[2:], styles['Normal']))
            else:
                story.append(Paragraph(esc.replace('**', ''), styles['Normal']))
        story.append(Spacer(1, 10))
    doc.build(story)
    return buf.getvalue()


def _morning_briefing_job():
    """Job diário matinal (hora configurável, default 7h): compila os briefings
    de todas as reuniões do dia em um PDF e envia ao próprio usuário por e-mail."""
    try:
        hour = int(_resolve_setting('briefing_email_hour', 'BRIEFING_EMAIL_HOUR') or 7)
    except Exception:
        hour = 7
    if datetime.now().hour < hour:
        return 'skip'
    today = datetime.now().strftime('%Y-%m-%d')
    conn = get_db()
    c = conn.cursor()
    # No disparo manual (rota) roda em request → escopa aos compromissos visíveis
    # do solicitante. No job agendado (sem request, login on) não há usuário →
    # '1=0' e nenhum e-mail cross-user; login off (desktop) → '1=1' como sempre.
    acl_user = current_user()
    _vw, _vp = visible_where('commitments', alias='co', user=acl_user)
    c.execute(f"""SELECT co.*, cl.name AS client_name, cl.company
                 FROM commitments co JOIN clients cl ON cl.id = co.client_id
                 WHERE co.due_date = ? AND COALESCE(cl.is_archived, 0) = 0 AND {_vw}
                 ORDER BY co.due_time ASC""", [today] + _vp)
    meetings = [dict_from_row(r) for r in c.fetchall()]
    if not meetings:
        conn.close()
        logger.info('[Briefing] Sem reuniões hoje — e-mail matinal não enviado')
        return
    sections = []
    for m in meetings:
        try:
            result = _generate_briefing(c, m, acl_user=acl_user)  # usa cache se já existir
            conn.commit()
            head = f'{m["client_name"]} ({m["company"]})' + (f' — {m["due_time"]}' if m.get('due_time') else '')
            sections.append((head, result['content']))
        except Exception as e:
            logger.warning(f'[Briefing] Falha ao gerar briefing do compromisso {m["id"]}: {e}')
    conn.close()
    if not sections:
        return
    date_label = datetime.now().strftime('%d/%m/%Y')
    pdf_bytes = _briefings_to_pdf(f'Briefings de reuniões — {date_label}', sections)
    attachments = []
    if pdf_bytes:
        attachments.append({'name': f'briefings-{today}.pdf',
                            'content_bytes': base64.b64encode(pdf_bytes).decode('ascii'),
                            'content_type': 'application/pdf'})
    body = ('<p>Bom dia! 🐇 Seguem os briefings das reuniões de hoje'
            + (' (PDF em anexo)' if attachments else '') + ':</p>'
            + ''.join(f'<h3>{html.escape(s[0])}</h3><pre style="white-space:pre-wrap; font-family:inherit;">{html.escape(s[1])}</pre>'
                      for s in sections))
    _outlook_send_mail(None, f'🐇 Briefings do dia — {date_label}', body, attachments)


_register_scheduled_job('morning_briefing_last_run', 1, _morning_briefing_job)


@app.route('/api/briefings/send-morning-email', methods=['POST'])
def briefing_send_morning_email_now():
    """Dispara manualmente a compilação e envio do e-mail matinal."""
    try:
        result = _morning_briefing_job()
        if result == 'skip':
            return jsonify({'ok': False, 'error': 'Ainda não chegou a hora configurada.'}), 400
        return jsonify({'ok': True})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/briefings/send-morning-email: {e}')
        return jsonify({'error': str(e)}), 500
