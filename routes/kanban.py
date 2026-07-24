# -*- coding: utf-8 -*-
# Rotas do domínio "kanban" (Bloco 3 — modularização).
# Este arquivo é executado no namespace de app.py por _load_route_modules():
# tem acesso a todos os helpers/globals de app.py e registra as rotas no
# mesmo objeto Flask `app`, com URLs idênticas às originais.


def _normalize_kanban_column_order(c):
    """Mantém Backlog sempre em primeiro e Done sempre em último (no quadro do
    usuário atual — a ordenação é por-dono)."""
    _ow, _op = owned_where('kanban_columns')
    c.execute(f'SELECT id, title, display_order FROM kanban_columns WHERE {_ow} ORDER BY display_order, id', _op)
    rows = [dict_from_row(row) for row in c.fetchall()]
    if not rows:
        return []

    def is_backlog(row):
        return str(row.get('title') or '').strip().lower() == 'backlog'

    def is_done(row):
        return str(row.get('title') or '').strip().lower() == 'done'

    backlog = [row for row in rows if is_backlog(row)]
    done = [row for row in rows if is_done(row)]
    middle = [row for row in rows if not is_backlog(row) and not is_done(row)]
    ordered = backlog[:1] + middle + done[:1]
    ordered_ids = {row['id'] for row in ordered}
    ordered.extend(row for row in rows if row['id'] not in ordered_ids)

    for display_order, row in enumerate(ordered, start=1):
        if int(row.get('display_order') or 0) != display_order:
            c.execute('UPDATE kanban_columns SET display_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                      (display_order, row['id']))
            row['display_order'] = display_order
    return ordered


def _kanban_fixed_column_kind(title):
    normalized = str(title or '').strip().lower()
    if normalized == 'backlog':
        return 'backlog'
    if normalized == 'done':
        return 'done'
    return ''


# Quadro Kanban é PESSOAL (por-usuário): cada dono tem seu próprio conjunto de
# colunas de sistema; os cards herdam a visibilidade da coluna. Por isso o
# escopo aqui é `owned_where`/`owns` (estritamente do dono), não visible_where.
_KANBAN_DEFAULT_COLUMNS = [
    ('Backlog', 1, 1, 0),
    ('Em Andamento', 2, 1, 0),
    ('Hold', 3, 1, 0),
    ('Descartado', 4, 1, 1),
    ('Done', 5, 1, 1),
]


def _ensure_kanban_board(c):
    """Garante que o usuário atual tenha o quadro padrão (colunas de sistema),
    semeando-o no 1º acesso. No-op se já tiver colunas próprias ou sem usuário
    resolvido. Login off: o fundador já tem as colunas do init → no-op."""
    owner = _acl_owner_for_insert()
    if owner is None:
        return
    _ow, _op = owned_where('kanban_columns')
    c.execute(f'SELECT 1 FROM kanban_columns WHERE {_ow} LIMIT 1', _op)
    if c.fetchone():
        return
    for title, order, is_system, is_locked in _KANBAN_DEFAULT_COLUMNS:
        c.execute('INSERT INTO kanban_columns (title, display_order, is_system, is_locked, owner_id) '
                  'VALUES (?, ?, ?, ?, ?)', (title, order, is_system, is_locked, owner))

@app.route('/api/kanban/columns', methods=['GET'])
def list_kanban_columns():
    try:
        conn = get_db()
        c = conn.cursor()
        _ensure_kanban_board(c)
        _normalize_kanban_column_order(c)
        conn.commit()
        _ow, _op = owned_where('kanban_columns', 'kc')
        c.execute(f"""SELECT kc.*, COUNT(kb.id) AS cards_count
                     FROM kanban_columns kc
                     LEFT JOIN kanban_cards kb ON kb.column_id = kc.id
                     WHERE {_ow}
                     GROUP BY kc.id
                     ORDER BY kc.display_order, kc.id""", _op)
        rows = [dict_from_row(row) for row in c.fetchall()]
        conn.close()
        return jsonify(rows)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/kanban/columns: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/columns', methods=['POST'])
def create_kanban_column():
    try:
        title = (request.json.get('title') or '').strip()
        if not title:
            return jsonify({'error': 'Título é obrigatório'}), 400

        conn = get_db()
        c = conn.cursor()
        _ensure_kanban_board(c)
        _normalize_kanban_column_order(c)
        _ow, _op = owned_where('kanban_columns')
        c.execute(f"SELECT display_order FROM kanban_columns WHERE lower(title) = 'done' AND {_ow} ORDER BY display_order, id LIMIT 1", _op)
        done = c.fetchone()
        next_order = done['display_order'] if done else 2
        c.execute(f'UPDATE kanban_columns SET display_order = display_order + 1 WHERE display_order >= ? AND {_ow}', [next_order] + _op)
        c.execute('INSERT INTO kanban_columns (title, display_order, owner_id) VALUES (?, ?, ?)', (title, next_order, _acl_owner_for_insert()))
        _normalize_kanban_column_order(c)
        conn.commit()
        new_id = c.lastrowid
        conn.close()
        return jsonify({'id': new_id, 'message': 'Sessão criada com sucesso'}), 201
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/kanban/columns: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/columns/<int:column_id>', methods=['PUT'])
def update_kanban_column(column_id):
    try:
        title = (request.json.get('title') or '').strip()
        if not title:
            return jsonify({'error': 'Título é obrigatório'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM kanban_columns WHERE id = ?', (column_id,))
        current = c.fetchone()
        if not current or not owns('kanban_columns', column_id, c):
            conn.close()
            return jsonify({'error': 'Sessão não encontrada'}), 404
        current = dict_from_row(current)
        if int(current.get('is_locked') or 0) == 1:
            conn.close()
            return jsonify({'error': 'Sessão bloqueada não pode ser editada'}), 403

        c.execute('UPDATE kanban_columns SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (title, column_id))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Sessão atualizada com sucesso'})
    except Exception as e:
        logger.exception(f'[ERROR] PUT /api/kanban/columns/{column_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/columns/<int:column_id>', methods=['DELETE'])
def delete_kanban_column(column_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM kanban_columns WHERE id = ?', (column_id,))
        current = c.fetchone()
        if not current or not owns('kanban_columns', column_id, c):
            conn.close()
            return jsonify({'error': 'Sessão não encontrada'}), 404
        current = dict_from_row(current)
        if int(current.get('is_locked') or 0) == 1:
            conn.close()
            return jsonify({'error': 'Sessão bloqueada não pode ser apagada'}), 403

        _ow, _op = owned_where('kanban_columns')
        c.execute(f'SELECT id FROM kanban_columns WHERE {_ow} ORDER BY display_order, id LIMIT 1', _op)
        first_column = c.fetchone()
        first_column_id = first_column['id'] if first_column else None

        if first_column_id and first_column_id != column_id:
            c.execute('UPDATE kanban_cards SET column_id = ?, updated_at = CURRENT_TIMESTAMP WHERE column_id = ?', (first_column_id, column_id))

        c.execute('DELETE FROM kanban_columns WHERE id = ?', (column_id,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Sessão removida com sucesso'})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE /api/kanban/columns/{column_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/columns/<int:column_id>/move', methods=['PATCH'])
def move_kanban_column(column_id):
    try:
        data = request.json or {}
        position = int(data.get('position') or 0)

        conn = get_db()
        c = conn.cursor()
        _normalize_kanban_column_order(c)
        c.execute('SELECT id, title FROM kanban_columns WHERE id = ?', (column_id,))
        current = c.fetchone()
        if not current or not owns('kanban_columns', column_id, c):
            conn.close()
            return jsonify({'error': 'Sessão não encontrada'}), 404
        current = dict_from_row(current)
        if _kanban_fixed_column_kind(current.get('title')):
            conn.close()
            return jsonify({'error': 'Backlog e Done são sessões fixas e não podem ser movidas'}), 403

        _ow, _op = owned_where('kanban_columns')
        c.execute(f"""SELECT id, title FROM kanban_columns
                     WHERE lower(title) NOT IN ('backlog', 'done') AND id != ? AND {_ow}
                     ORDER BY display_order, id""", [column_id] + _op)
        ids = [row['id'] for row in c.fetchall()]
        if position < 0:
            position = 0
        if position > len(ids):
            position = len(ids)
        ids.insert(position, column_id)

        c.execute(f"SELECT id FROM kanban_columns WHERE lower(title) = 'backlog' AND {_ow} ORDER BY display_order, id LIMIT 1", _op)
        backlog = c.fetchone()
        order = 1
        if backlog:
            c.execute('UPDATE kanban_columns SET display_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (order, backlog['id']))
            order += 1
        for cid in ids:
            c.execute('UPDATE kanban_columns SET display_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (order, cid))
            order += 1
        c.execute(f"SELECT id FROM kanban_columns WHERE lower(title) = 'done' AND {_ow} ORDER BY display_order, id LIMIT 1", _op)
        done = c.fetchone()
        if done:
            c.execute('UPDATE kanban_columns SET display_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (order, done['id']))
        _normalize_kanban_column_order(c)
        conn.commit()
        conn.close()
        return jsonify({'message': 'Sessão movida com sucesso'})
    except Exception as e:
        logger.exception(f'[ERROR] PATCH /api/kanban/columns/{column_id}/move: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/cards', methods=['GET'])
def list_kanban_cards():
    try:
        conn = get_db()
        c = conn.cursor()
        _ow, _op = owned_where('kanban_cards', 'kb')
        c.execute(f"""SELECT kb.*,
                            acc.name AS account_name,
                            acc.logo_url AS account_logo_url,
                            cl.name AS contact_name,
                            cl.photo_url AS contact_photo_url,
                            (SELECT MAX(kca.created_at) FROM kanban_card_activities kca WHERE kca.card_id = kb.id) AS last_activity_at
                     FROM kanban_cards kb
                     LEFT JOIN accounts acc ON acc.id = kb.account_id
                     LEFT JOIN clients cl ON cl.id = kb.contact_id
                     WHERE {_ow}
                     ORDER BY kb.column_id, kb.display_order, kb.id""", _op)
        rows = [dict_from_row(row) for row in c.fetchall()]
        conn.close()
        return jsonify(rows)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/kanban/cards: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/cards', methods=['POST'])
def create_kanban_card():
    try:
        data = request.json or {}
        title = (data.get('title') or '').strip()
        description = (data.get('description') or '').strip()
        tag = (data.get('tag') or '').strip() or infer_kanban_tag(description)
        account_id = data.get('account_id')
        contact_id = data.get('contact_id')
        urgency = (data.get('urgency') or 'Média').strip() or 'Média'
        if urgency not in ['Baixa', 'Média', 'Alta', 'Crítica']:
            urgency = 'Média'
        if not title or not description:
            return jsonify({'error': 'Título e descrição são obrigatórios'}), 400

        conn = get_db()
        c = conn.cursor()
        _ensure_kanban_board(c)
        _ow, _op = owned_where('kanban_columns')
        c.execute(f'SELECT id FROM kanban_columns WHERE {_ow} ORDER BY display_order, id LIMIT 1', _op)
        first = c.fetchone()
        if not first:
            conn.close()
            return jsonify({'error': 'Nenhuma sessão disponível no Kanban'}), 400
        first_column_id = first['id']

        c.execute('SELECT COALESCE(MAX(display_order), 0) AS n FROM kanban_cards WHERE column_id = ?', (first_column_id,))
        next_order = (c.fetchone()['n'] or 0) + 1

        c.execute('''INSERT INTO kanban_cards (title, description, tag, account_id, contact_id, urgency, column_id, display_order)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                  (title, description, tag, account_id, contact_id, urgency, first_column_id, next_order))
        conn.commit()
        new_id = c.lastrowid
        conn.close()
        return jsonify({'id': new_id, 'message': 'Card criado com sucesso'}), 201
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/kanban/cards: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/cards/<int:card_id>', methods=['PUT'])
def update_kanban_card(card_id):
    try:
        data = request.json or {}
        title = (data.get('title') or '').strip()
        description = (data.get('description') or '').strip()
        tag = (data.get('tag') or '').strip() or infer_kanban_tag(description)
        account_id = data.get('account_id')
        contact_id = data.get('contact_id')
        urgency = (data.get('urgency') or 'Média').strip() or 'Média'
        if urgency not in ['Baixa', 'Média', 'Alta', 'Crítica']:
            urgency = 'Média'
        if not title or not description:
            return jsonify({'error': 'Título e descrição são obrigatórios'}), 400

        conn = get_db()
        c = conn.cursor()
        if not owns('kanban_cards', card_id, c):
            conn.close()
            return jsonify({'error': 'Card não encontrado'}), 404
        c.execute('''UPDATE kanban_cards
                     SET title = ?, description = ?, tag = ?, account_id = ?, contact_id = ?, urgency = ?, updated_at = CURRENT_TIMESTAMP
                     WHERE id = ?''',
                  (title, description, tag, account_id, contact_id, urgency, card_id))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Card atualizado com sucesso'})
    except Exception as e:
        logger.exception(f'[ERROR] PUT /api/kanban/cards/{card_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/cards/<int:card_id>', methods=['GET'])
def get_kanban_card(card_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''SELECT kb.*, kc.title as column_title,
                            acc.name AS account_name, acc.logo_url AS account_logo_url,
                            cl.name AS contact_name, cl.photo_url AS contact_photo_url, cl.position AS contact_position,
                            (SELECT MAX(kca.created_at) FROM kanban_card_activities kca WHERE kca.card_id = kb.id) AS last_activity_at
                     FROM kanban_cards kb
                     JOIN kanban_columns kc ON kc.id = kb.column_id
                     LEFT JOIN accounts acc ON acc.id = kb.account_id
                     LEFT JOIN clients cl ON cl.id = kb.contact_id
                     WHERE kb.id = ?''', (card_id,))
        row = c.fetchone()
        if not row or not owns('kanban_cards', card_id, c):
            conn.close()
            return jsonify({'error': 'Card não encontrado'}), 404
        card = dict_from_row(row)
        c.execute('SELECT id, content, created_at FROM kanban_card_activities WHERE card_id = ? ORDER BY created_at DESC, id DESC', (card_id,))
        card['activities'] = [dict_from_row(r) for r in c.fetchall()]
        conn.close()
        return jsonify(card)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/kanban/cards/{card_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/cards/<int:card_id>/activities', methods=['POST'])
def add_kanban_card_activity(card_id):
    try:
        content = (request.json.get('content') or '').strip()
        if not content:
            return jsonify({'error': 'Atividade é obrigatória'}), 400
        conn = get_db()
        c = conn.cursor()
        if not owns('kanban_cards', card_id, c):
            conn.close()
            return jsonify({'error': 'Card não encontrado'}), 404
        c.execute('INSERT INTO kanban_card_activities (card_id, content) VALUES (?, ?)', (card_id, content))
        conn.commit()
        new_id = c.lastrowid
        c.execute('SELECT id, content, created_at FROM kanban_card_activities WHERE id = ?', (new_id,))
        created = dict_from_row(c.fetchone())
        conn.close()
        return jsonify({'message': 'Atividade adicionada', 'activity': created}), 201
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/kanban/cards/{card_id}/activities: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/cards/<int:card_id>', methods=['DELETE'])
def delete_kanban_card(card_id):
    try:
        conn = get_db()
        c = conn.cursor()
        if not owns('kanban_cards', card_id, c):
            conn.close()
            return jsonify({'error': 'Card não encontrado'}), 404
        c.execute('DELETE FROM kanban_cards WHERE id = ?', (card_id,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Card removido com sucesso'})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE /api/kanban/cards/{card_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/cards/<int:card_id>/urgency', methods=['PATCH'])
def update_kanban_card_urgency(card_id):
    try:
        urgency = (request.json.get('urgency') or '').strip() or 'Média'
        if urgency not in ['Baixa', 'Média', 'Alta', 'Crítica']:
            return jsonify({'error': 'Urgência inválida'}), 400

        conn = get_db()
        c = conn.cursor()
        if not owns('kanban_cards', card_id, c):
            conn.close()
            return jsonify({'error': 'Card não encontrado'}), 404

        c.execute('UPDATE kanban_cards SET urgency = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (urgency, card_id))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Urgência atualizada com sucesso'})
    except Exception as e:
        logger.exception(f'[ERROR] PATCH /api/kanban/cards/{card_id}/urgency: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/cards/<int:card_id>/move', methods=['PATCH'])
def move_kanban_card(card_id):
    try:
        data = request.json or {}
        column_id = data.get('column_id')
        position = int(data.get('position') or 0)
        if not column_id:
            return jsonify({'error': 'Sessão de destino é obrigatória'}), 400

        conn = get_db()
        c = conn.cursor()
        if not owns('kanban_cards', card_id, c):
            conn.close()
            return jsonify({'error': 'Card não encontrado'}), 404

        if not owns('kanban_columns', column_id, c):
            conn.close()
            return jsonify({'error': 'Sessão de destino não encontrada'}), 404

        c.execute('''SELECT id FROM kanban_cards
                     WHERE column_id = ? AND id != ?
                     ORDER BY display_order, id''', (column_id, card_id))
        ids = [row['id'] for row in c.fetchall()]
        if position < 0:
            position = 0
        if position > len(ids):
            position = len(ids)
        ids.insert(position, card_id)

        for order, cid in enumerate(ids, start=1):
            c.execute('UPDATE kanban_cards SET column_id = ?, display_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                      (column_id, order, cid))

        conn.commit()
        conn.close()
        return jsonify({'message': 'Card movido com sucesso'})
    except Exception as e:
        logger.exception(f'[ERROR] PATCH /api/kanban/cards/{card_id}/move: {e}')
        return jsonify({'error': str(e)}), 500
