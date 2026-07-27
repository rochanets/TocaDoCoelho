# -*- coding: utf-8 -*-
"""Backend de compartilhamentos seletivos (Fase 5).

Somente o proprietário do registro ou um administrador da mesma organização
pode listar e gerenciar seus shares. Ter recebido permission='write' permite
editar o registro, mas não redistribuí-lo.
"""


def _share_error(message, status, error_type):
    return jsonify({'error': message, 'error_type': error_type}), status


def _share_record_type(raw):
    value = (raw or '').strip().lower() if isinstance(raw, str) else ''
    return value if value in _SHAREABLE_RECORD_TYPES else None


def _share_positive_id(raw):
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, str) and raw.strip().isdigit():
        value = int(raw.strip())
        return value if value > 0 else None
    return None


def _share_permission(raw):
    value = (raw or '').strip().lower() if isinstance(raw, str) else ''
    return value if value in {'read', 'write'} else None


def _share_record_owner_context(cur, record_type, record_id):
    owner_expr = _acl_effective_owner_expr('r')
    cur.execute(
        f'SELECT {owner_expr} AS owner_id FROM {record_type} r WHERE r.id = ? LIMIT 1',
        (record_id,),
    )
    row = dict_from_row(cur.fetchone())
    if not row:
        return None
    owner_id = row.get('owner_id')
    owner_org_id = None
    if owner_id is not None:
        cur.execute('SELECT org_id FROM users WHERE id = ? LIMIT 1', (owner_id,))
        owner = dict_from_row(cur.fetchone())
        owner_org_id = owner.get('org_id') if owner else None
    return {'owner_id': owner_id, 'owner_org_id': owner_org_id}


def _can_manage_record_shares(cur, record_type, record_id):
    context = _share_record_owner_context(cur, record_type, record_id)
    if not context:
        return False, None
    if not _auth_enabled():
        return True, context
    user = current_user()
    if not user:
        return False, context
    if user.get('id') == context['owner_id']:
        return True, context
    is_admin = (user.get('role') or '').strip().lower() == 'admin'
    same_org = (
        user.get('org_id') is not None
        and user.get('org_id') == context['owner_org_id']
    )
    return bool(is_admin and same_org), context


def _load_manageable_share(cur, share_id):
    cur.execute(
        '''SELECT id, record_type, record_id, shared_with_user_id, permission,
                  created_by, created_at
           FROM shares WHERE id = ? LIMIT 1''',
        (share_id,),
    )
    share = dict_from_row(cur.fetchone())
    if not share or share.get('record_type') not in _SHAREABLE_RECORD_TYPES:
        return None
    allowed, _ = _can_manage_record_shares(
        cur, share['record_type'], share['record_id']
    )
    return share if allowed else None


def _share_public_dict(row):
    item = dict_from_row(row)
    return {
        'id': item['id'],
        'record_type': item['record_type'],
        'record_id': item['record_id'],
        'shared_with_user_id': item['shared_with_user_id'],
        'shared_with_email': item.get('shared_with_email'),
        'shared_with_name': item.get('shared_with_name'),
        'permission': item['permission'],
        'created_by': item.get('created_by'),
        'created_at': item.get('created_at'),
    }


@app.route('/api/shares/users', methods=['GET'])
def list_share_recipients():
    """Diretório mínimo para o seletor de compartilhamento.

    Não expõe papéis, vínculos Entra ou dados de outra organização.
    """
    user = current_user()
    if not user or user.get('org_id') is None:
        return jsonify({'users': []})
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            '''SELECT id, email, full_name, photo_url
               FROM users
               WHERE org_id = ? AND id <> ? AND COALESCE(is_active, 1) = 1
               ORDER BY LOWER(COALESCE(full_name, '')),
                        LOWER(COALESCE(email, '')), id''',
            (user['org_id'], user['id']),
        )
        users = []
        for row in cur.fetchall():
            item = dict_from_row(row)
            users.append({
                'id': item['id'],
                'email': item.get('email'),
                'full_name': item.get('full_name'),
                'photo_url': item.get('photo_url'),
            })
        return jsonify({'users': users})
    finally:
        conn.close()


def _list_record_shares(record_type, record_id):
    conn = get_db()
    try:
        cur = conn.cursor()
        allowed, _ = _can_manage_record_shares(cur, record_type, record_id)
        if not allowed:
            return _share_error('Registro não encontrado.', 404, 'not_found')
        cur.execute(
            '''SELECT s.id, s.record_type, s.record_id, s.shared_with_user_id,
                      s.permission, s.created_by, s.created_at,
                      u.email AS shared_with_email,
                      u.full_name AS shared_with_name
               FROM shares s
               JOIN users u ON u.id = s.shared_with_user_id
               WHERE s.record_type = ? AND s.record_id = ?
               ORDER BY LOWER(COALESCE(u.full_name, '')),
                        LOWER(COALESCE(u.email, '')), s.id''',
            (record_type, record_id),
        )
        return jsonify({'shares': [_share_public_dict(row) for row in cur.fetchall()]})
    finally:
        conn.close()


@app.route('/api/shares', methods=['GET'])
def list_shares():
    record_type = _share_record_type(request.args.get('record_type'))
    record_id = _share_positive_id(request.args.get('record_id'))
    if not record_type or not record_id:
        return _share_error(
            'record_type e record_id válidos são obrigatórios.',
            400,
            'validation',
        )
    return _list_record_shares(record_type, record_id)


@app.route('/api/shares/<record_type>/<int:record_id>', methods=['GET'])
def list_shares_for_record(record_type, record_id):
    canonical_type = _share_record_type(record_type)
    if not canonical_type or record_id <= 0:
        return _share_error('Registro inválido.', 400, 'validation')
    return _list_record_shares(canonical_type, record_id)


@app.route('/api/shares', methods=['POST'])
def create_share():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    record_type = _share_record_type(data.get('record_type'))
    record_id = _share_positive_id(data.get('record_id'))
    recipient_id = _share_positive_id(data.get('shared_with_user_id'))
    permission = _share_permission(data.get('permission', 'read'))
    if not record_type or not record_id or not recipient_id or not permission:
        return _share_error(
            'record_type, record_id, shared_with_user_id e permission são inválidos.',
            400,
            'validation',
        )

    conn = get_db()
    try:
        cur = conn.cursor()
        allowed, record = _can_manage_record_shares(cur, record_type, record_id)
        if not allowed:
            return _share_error('Registro não encontrado.', 404, 'not_found')

        cur.execute(
            'SELECT id, org_id FROM users WHERE id = ? LIMIT 1',
            (recipient_id,),
        )
        recipient = dict_from_row(cur.fetchone())
        owner_org_id = record.get('owner_org_id')
        if (
            not recipient
            or recipient.get('org_id') != owner_org_id
            or (_auth_enabled() and owner_org_id is None)
        ):
            return _share_error(
                'Usuário destinatário inválido.',
                400,
                'validation',
            )
        if recipient_id == record.get('owner_id'):
            return _share_error(
                'O proprietário já possui acesso ao registro.',
                400,
                'validation',
            )

        cur.execute(
            '''SELECT id FROM shares
               WHERE record_type = ? AND record_id = ?
                 AND shared_with_user_id = ? LIMIT 1''',
            (record_type, record_id, recipient_id),
        )
        existed = cur.fetchone() is not None
        cur.execute(
            '''INSERT INTO shares
                  (record_type, record_id, shared_with_user_id, permission, created_by)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(record_type, record_id, shared_with_user_id)
               DO UPDATE SET
                  permission = excluded.permission,
                  created_by = COALESCE(shares.created_by, excluded.created_by)''',
            (
                record_type,
                record_id,
                recipient_id,
                permission,
                current_user_id(),
            ),
        )
        conn.commit()
        cur.execute(
            '''SELECT s.id, s.record_type, s.record_id, s.shared_with_user_id,
                      s.permission, s.created_by, s.created_at,
                      u.email AS shared_with_email,
                      u.full_name AS shared_with_name
               FROM shares s
               JOIN users u ON u.id = s.shared_with_user_id
               WHERE s.record_type = ? AND s.record_id = ?
                 AND s.shared_with_user_id = ? LIMIT 1''',
            (record_type, record_id, recipient_id),
        )
        payload = _share_public_dict(cur.fetchone())
        payload['created'] = not existed
        return jsonify(payload), 200 if existed else 201
    finally:
        conn.close()


@app.route('/api/shares/<int:share_id>', methods=['PUT', 'PATCH'])
def update_share(share_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    permission = _share_permission(data.get('permission'))
    if not permission:
        return _share_error("permission deve ser 'read' ou 'write'.", 400, 'validation')

    conn = get_db()
    try:
        cur = conn.cursor()
        share = _load_manageable_share(cur, share_id)
        if not share:
            return _share_error('Compartilhamento não encontrado.', 404, 'not_found')
        cur.execute(
            'UPDATE shares SET permission = ? WHERE id = ?',
            (permission, share_id),
        )
        conn.commit()
        share['permission'] = permission
        return jsonify(share)
    finally:
        conn.close()


@app.route('/api/shares/<int:share_id>', methods=['DELETE'])
def delete_share(share_id):
    conn = get_db()
    try:
        cur = conn.cursor()
        share = _load_manageable_share(cur, share_id)
        if not share:
            return _share_error('Compartilhamento não encontrado.', 404, 'not_found')
        cur.execute('DELETE FROM shares WHERE id = ?', (share_id,))
        conn.commit()
        return '', 204
    finally:
        conn.close()
