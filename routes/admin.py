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
        'photo_url': row.get('photo_url'),
        # linked = já fez login e vinculou a identidade do Entra
        'linked': bool((row.get('entra_object_id') or '').strip()),
        'is_active': bool(row.get('is_active', 1)),
        'created_at': row['created_at'],
    }


def _active_user_in_admin_org(conn, user_id):
    org_id = _admin_org_id(conn)
    c = conn.cursor()
    c.execute(
        '''SELECT id, org_id, email, full_name, nickname, position, role,
                  photo_url, entra_object_id, is_active, created_at
           FROM users
           WHERE id = ? AND org_id = ? AND COALESCE(is_active, 1) = 1
           LIMIT 1''',
        (user_id, org_id),
    )
    return dict_from_row(c.fetchone())


def _active_admin_count(conn, org_id):
    c = conn.cursor()
    c.execute(
        '''SELECT COUNT(*) AS n FROM users
           WHERE org_id = ? AND role = 'admin' AND COALESCE(is_active, 1) = 1''',
        (org_id,),
    )
    row = dict_from_row(c.fetchone())
    return int((row or {}).get('n') or 0)


@app.route('/api/admin/users', methods=['GET'])
@admin_required
def admin_list_users():
    """Lista os usuários provisionados (allowlist)."""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            '''SELECT id, org_id, email, full_name, nickname, position, role,
                      photo_url, entra_object_id, is_active, created_at
               FROM users
               WHERE org_id = ? AND COALESCE(is_active, 1) = 1
               ORDER BY LOWER(COALESCE(full_name, '')),
                        LOWER(COALESCE(email, '')), id''',
            (_admin_org_id(conn),),
        )
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
        org_id = _admin_org_id(conn)
        c.execute(
            '''SELECT id, org_id, is_active FROM users
               WHERE LOWER(email) = LOWER(?) ORDER BY id LIMIT 1''',
            (email,),
        )
        existing = dict_from_row(c.fetchone())
        reactivated = False
        if existing and bool(existing.get('is_active', 1)):
            return jsonify({
                'error': 'Já existe um usuário com esse email.',
                'error_type': 'conflict',
            }), 409
        if existing:
            if existing.get('org_id') != org_id:
                return jsonify({
                    'error': 'Não foi possível provisionar esse email.',
                    'error_type': 'conflict',
                }), 409
            new_id = existing['id']
            c.execute(
                '''UPDATE users
                   SET full_name = ?, nickname = ?, position = ?, role = ?,
                       is_active = 1, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?''',
                (full_name, nickname, position, role, new_id),
            )
            reactivated = True
        else:
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
        'is_active': True, 'reactivated': reactivated,
    }), 201


@app.route('/api/admin/users/<int:user_id>', methods=['PATCH'])
@admin_required
def admin_update_user_role(user_id):
    """Altera somente o papel. Auto-rebaixamento exige confirmação explícita."""
    data = request.get_json(silent=True) or {}
    role = (data.get('role') or '').strip().lower()
    if role not in ('admin', 'member'):
        return jsonify({
            'error': "role deve ser 'admin' ou 'member'.",
            'error_type': 'validation',
        }), 400

    conn = get_db()
    try:
        user = _active_user_in_admin_org(conn, user_id)
        if not user:
            return jsonify({
                'error': 'Usuário não encontrado.',
                'error_type': 'not_found',
            }), 404
        is_self = user_id == current_user_id()
        demoting = user.get('role') == 'admin' and role == 'member'
        if is_self and demoting and data.get('confirm_self_change') is not True:
            return jsonify({
                'error': 'Confirme explicitamente o rebaixamento da sua própria conta.',
                'error_type': 'confirmation_required',
            }), 400
        if demoting and _active_admin_count(conn, user['org_id']) <= 1:
            return jsonify({
                'error': 'A organização precisa manter ao menos um administrador.',
                'error_type': 'last_admin',
            }), 409
        c = conn.cursor()
        c.execute(
            'UPDATE users SET role = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            (role, user_id),
        )
        conn.commit()
        user['role'] = role
        return jsonify(_user_public_dict(user))
    finally:
        conn.close()


@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def admin_deactivate_user(user_id):
    """Revoga acesso sem apagar dados ou autoria. Auto-bloqueio exige confirmação."""
    data = request.get_json(silent=True) or {}
    conn = get_db()
    try:
        user = _active_user_in_admin_org(conn, user_id)
        if not user:
            return jsonify({
                'error': 'Usuário não encontrado.',
                'error_type': 'not_found',
            }), 404
        is_self = user_id == current_user_id()
        if is_self and data.get('confirm_self_change') is not True:
            return jsonify({
                'error': 'Confirme explicitamente a desativação da sua própria conta.',
                'error_type': 'confirmation_required',
            }), 400
        if (
            user.get('role') == 'admin'
            and _active_admin_count(conn, user['org_id']) <= 1
        ):
            return jsonify({
                'error': 'A organização precisa manter ao menos um administrador.',
                'error_type': 'last_admin',
            }), 409
        c = conn.cursor()
        # Acesso recebido deixa de existir. Registros de autoria/propriedade
        # permanecem intactos para não perder dados e podem ser administrados.
        c.execute('DELETE FROM shares WHERE shared_with_user_id = ?', (user_id,))
        c.execute(
            '''UPDATE users
               SET is_active = 0, entra_object_id = NULL,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ?''',
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()
    logger.info(
        f'[Admin] Usuário desativado: id={user_id} '
        f'por user_id={current_user_id()}.'
    )
    return '', 204


@app.route('/api/admin/jobs/status', methods=['GET'])
@admin_required
def admin_jobs_status():
    """Estado operacional compartilhado dos jobs da F8.2."""
    conn = get_db()
    try:
        states = [
            dict_from_row(row)
            for row in conn.execute(
                '''SELECT job_key, owner_id, status, started_at, heartbeat_at,
                          completed_at, detail, updated_at
                   FROM job_runtime_state
                   ORDER BY job_key'''
            ).fetchall()
        ]
        claims = [
            dict_from_row(row)
            for row in conn.execute(
                '''SELECT job_key, run_key, owner_id, status, started_at,
                          completed_at, detail
                   FROM job_execution_claims
                   ORDER BY started_at DESC
                   LIMIT 100'''
            ).fetchall()
        ]
        return jsonify({
            'instance_id': _PROCESS_INSTANCE_ID,
            'backend': DB_BACKEND,
            'states': states,
            'recent_claims': claims,
        })
    finally:
        conn.close()
