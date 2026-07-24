# -*- coding: utf-8 -*-
# Rotas de administração (Fase 3, PR 3.3): provisionamento de usuários na
# allowlist. Executado no namespace de app.py por _load_route_modules().
#
# A allowlist da PR 3.2 só deixa entrar no login quem já existe em `users`.
# Aqui o admin cadastra novos emails (entra_object_id fica NULL até o 1º login
# casar por email e vinculá-lo). Tudo guardado por @admin_required.


def _admin_org_id(conn):
    """Org do usuário logado; fallback para a org fundadora (menor id)."""
    user = current_user()
    if user and user.get('org_id'):
        return user['org_id']
    c = conn.cursor()
    c.execute('SELECT MIN(id) AS m FROM organizations')
    row = c.fetchone()
    return row['m'] if row else None


def _user_public_dict(row):
    return {
        'id': row['id'],
        'email': row['email'],
        'full_name': row['full_name'],
        'nickname': row['nickname'],
        'position': row['position'],
        'role': row['role'],
        # linked = já fez login e vinculou a identidade do Entra
        'linked': bool((row.get('entra_object_id') or '').strip()),
        'created_at': row['created_at'],
    }


@app.route('/api/admin/users', methods=['GET'])
@admin_required
def admin_list_users():
    """Lista os usuários provisionados (allowlist)."""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT id, org_id, email, full_name, nickname, position, role, '
                  'entra_object_id, created_at FROM users ORDER BY id')
        users = [_user_public_dict(dict_from_row(r)) for r in c.fetchall()]
    finally:
        conn.close()
    return jsonify({'users': users})


@app.route('/api/admin/users', methods=['POST'])
@admin_required
def admin_create_user():
    """Adiciona um email à allowlist. entra_object_id fica NULL — é preenchido no
    1º login do usuário (casando por email). role: 'member' (padrão) ou 'admin'."""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    if not _valid_email(email):
        return jsonify({'error': 'Email inválido.', 'error_type': 'validation'}), 400
    role = (data.get('role') or 'member').strip().lower()
    if role not in ('admin', 'member'):
        return jsonify({'error': "role deve ser 'admin' ou 'member'.", 'error_type': 'validation'}), 400
    full_name = (data.get('full_name') or '').strip()
    nickname = (data.get('nickname') or '').strip()
    position = (data.get('position') or '').strip()

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT id FROM users WHERE LOWER(email) = LOWER(?) LIMIT 1', (email,))
        if c.fetchone():
            return jsonify({'error': 'Já existe um usuário com esse email.', 'error_type': 'conflict'}), 409
        org_id = _admin_org_id(conn)
        c.execute(
            'INSERT INTO users (org_id, email, full_name, nickname, position, role) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (org_id, email, full_name, nickname, position, role),
        )
        new_id = c.lastrowid
        conn.commit()
    finally:
        conn.close()

    logger.info(f'[Admin] Usuário provisionado: id={new_id} email={email!r} role={role} '
                f'por user_id={current_user_id()}.')
    return jsonify({
        'id': new_id, 'email': email, 'full_name': full_name,
        'nickname': nickname, 'position': position, 'role': role, 'linked': False,
    }), 201
