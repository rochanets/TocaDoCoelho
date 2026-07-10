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
        c.execute('''SELECT a.*, c.name, c.company, c.position FROM activities a
                     JOIN clients c ON a.client_id = c.id
                     ORDER BY a.activity_date DESC''')
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
        
        # Verificar se cliente existe
        c.execute('SELECT id FROM clients WHERE id = ?', (client_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Cliente nao encontrado'}), 404
        
        # Salvar com campos separados
        c.execute('''INSERT INTO activities (client_id, contact_type, information)
                     VALUES (?, ?, ?)''',
                  (client_id, contact_type, information))
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
        
        # Verificar se cliente existe
        c.execute('SELECT id FROM clients WHERE id = ?', (client_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Cliente nao encontrado'}), 404
        
        c.execute('''INSERT INTO activities (client_id, information)
                     VALUES (?, ?)''',
                  (client_id, description))
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

        query = '''SELECT CAST(cm.id AS TEXT) as id, cm.client_id, cm.activity_id, cm.title, cm.notes, cm.due_date, cm.due_time, cm.source_type,
                          cl.name as client_name, cl.company as client_company, cl.position as client_position, cl.email as client_email, cl.photo_url as client_photo
                   FROM commitments cm
                   JOIN clients cl ON cm.client_id = cl.id'''
        params = []

        if start_date and end_date:
            query += ' WHERE DATE(cm.due_date) >= ? AND DATE(cm.due_date) <= ?'
            params.extend([start_date, end_date])

        query += ''' UNION ALL SELECT "acc-" || CAST(ev.id AS TEXT) as id, NULL as client_id, NULL as activity_id, ev.title, ev.title as notes, ev.due_date, ev.due_time, "account_presence" as source_type,
                          ac.name as client_name, ac.name as client_company, "Conta" as client_position, NULL as client_email, ac.logo_url as client_photo
                   FROM account_renewal_events ev
                   JOIN accounts ac ON ev.account_id = ac.id'''
        if start_date and end_date:
            query += ' WHERE DATE(ev.due_date) >= ? AND DATE(ev.due_date) <= ?'
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
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Cliente não encontrado'}), 404

        c.execute('''INSERT INTO commitments (client_id, title, notes, due_date, due_time, source_type)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (client_id, title or 'Agenda manual', notes or title or 'Agenda manual', due_date, due_time, 'manual'))
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
        c.execute('''SELECT COUNT(*) as total FROM commitments
                     WHERE DATE(due_date) >= ? AND DATE(due_date) <= ?''',
                  (start_week.isoformat(), end_week.isoformat()))
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
        
        if start_date and end_date:
            c.execute('''SELECT a.id, c.name, c.company, c.position, a.description, a.created_at 
                        FROM activities a
                        JOIN clients c ON a.client_id = c.id
                        WHERE DATE(a.created_at) >= ? AND DATE(a.created_at) <= ?
                        ORDER BY a.created_at DESC''',
                     (start_date, end_date))
        else:
            c.execute('''SELECT a.id, c.name, c.company, c.position, a.description, a.created_at 
                        FROM activities a
                        JOIN clients c ON a.client_id = c.id
                        ORDER BY a.created_at DESC''')
        
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
        c.execute("""
            SELECT co.id, co.title, co.due_date, co.due_time, cl.name, cl.company,
                   CASE WHEN co.due_date < ? THEN 'overdue' ELSE 'today' END AS kind
            FROM commitments co
            JOIN clients cl ON cl.id = co.client_id
            WHERE COALESCE(cl.is_archived, 0) = 0
              AND co.due_date <= ?
              AND NOT EXISTS (SELECT 1 FROM activities a
                              WHERE a.client_id = co.client_id
                                AND date(a.activity_date) >= co.due_date)
            ORDER BY co.due_date ASC, co.due_time ASC
        """, (today, today))
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return jsonify({
            'today': [r for r in rows if r['kind'] == 'today'],
            'overdue': [r for r in rows if r['kind'] == 'overdue'],
        })
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/commitments/alerts: {e}')
        return jsonify({'error': str(e)}), 500
