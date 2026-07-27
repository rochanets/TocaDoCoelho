# -*- coding: utf-8 -*-
"""Contrato HTTP do Toca Companion (Fase 7.4).

Executado no namespace de app.py. O web cria tarefas persistentes e o
Companion vinculado ao mesmo usuário as retira por polling autenticado. Esta
fase não executa Playwright no Companion; apenas entrega o contrato seguro que
a F7.5 consumirá.
"""

import hmac as _companion_hmac


COMPANION_PROTOCOL_VERSION = 1
COMPANION_TASK_TYPE_CHAMADO_JURIDICO = 'chamado_juridico'
COMPANION_PAIRING_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
COMPANION_PAIRING_LENGTH = 12
COMPANION_MAX_JSON_BYTES = 64 * 1024
COMPANION_TERMINAL_STATUSES = frozenset({
    'cancelled', 'succeeded', 'failed', 'expired',
})
COMPANION_ACTIVE_STATUSES = frozenset({
    'leased', 'running', 'awaiting_user', 'cancel_requested',
})
COMPANION_ALLOWED_TRANSITIONS = {
    'leased': frozenset({'running', 'failed', 'cancelled'}),
    'running': frozenset({'awaiting_user', 'succeeded', 'failed', 'cancelled'}),
    'awaiting_user': frozenset({'succeeded', 'failed', 'cancelled'}),
    'cancel_requested': frozenset({'cancelled', 'failed'}),
}


def _companion_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _companion_timestamp(value):
    return value.isoformat(sep=' ', timespec='seconds')


def _companion_parse_timestamp(value):
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _companion_env_int(name, default, minimum, maximum):
    try:
        value = int((os.environ.get(name) or '').strip() or default)
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


def _companion_pairing_ttl_minutes():
    return _companion_env_int(
        'TOCA_COMPANION_PAIRING_TTL_MINUTES', 10, 5, 30
    )


def _companion_task_ttl_minutes():
    return _companion_env_int(
        'TOCA_COMPANION_TASK_TTL_MINUTES', 30, 5, 120
    )


def _companion_lease_seconds():
    return _companion_env_int(
        'TOCA_COMPANION_LEASE_SECONDS', 90, 30, 300
    )


def _companion_max_attempts():
    return _companion_env_int(
        'TOCA_COMPANION_MAX_CLAIM_ATTEMPTS', 3, 1, 5
    )


def _companion_minimum_version():
    return _normalize_version(
        os.environ.get('TOCA_COMPANION_MIN_VERSION', '')
    )


def _companion_version_below_minimum(current):
    minimum = _companion_minimum_version()
    current = _normalize_version(current)
    return bool(
        minimum and (
            not current or _version_key(current) < _version_key(minimum)
        )
    )


def _companion_secret_hash(kind, value):
    material = f'toca-companion:{COMPANION_PROTOCOL_VERSION}:{kind}:{value}'
    return hashlib.sha256(material.encode('utf-8')).hexdigest()


def _companion_new_pairing_code():
    raw = ''.join(
        secrets.choice(COMPANION_PAIRING_ALPHABET)
        for _ in range(COMPANION_PAIRING_LENGTH)
    )
    return '-'.join(raw[index:index + 4] for index in range(0, len(raw), 4))


def _companion_normalize_pairing_code(value):
    return ''.join(
        char for char in str(value or '').upper()
        if char in COMPANION_PAIRING_ALPHABET
    )


def _companion_bearer_token():
    header = (request.headers.get('Authorization') or '').strip()
    if not header.lower().startswith('bearer '):
        return ''
    return header[7:].strip()


def _companion_device_from_request():
    raw_token = _companion_bearer_token()
    if not raw_token:
        return None
    token_hash = _companion_secret_hash('device', raw_token)
    conn = get_db()
    try:
        row = conn.execute(
            '''SELECT d.*
               FROM companion_devices d
               JOIN users u ON u.id = d.owner_id
               WHERE d.token_hash = ? AND d.status = 'active'
                 AND COALESCE(u.is_active, 1) = 1
               LIMIT 1''',
            (token_hash,),
        ).fetchone()
        if not row:
            return None
        device = dict_from_row(row)
        conn.execute(
            '''UPDATE companion_devices
               SET last_seen_at = CURRENT_TIMESTAMP
               WHERE id = ?''',
            (device['id'],),
        )
        conn.commit()
        return device
    finally:
        conn.close()


def companion_device_required(fn):
    @functools.wraps(fn)
    def _wrapper(*args, **kwargs):
        if not _auth_enabled():
            return jsonify({
                'error': 'O Toca Companion é usado somente no modo web autenticado.',
                'code': 'COMPANION_WEB_ONLY',
            }), 409
        if (
            request.method in {'POST', 'PUT', 'PATCH'}
            and request.content_length is not None
            and request.content_length > COMPANION_MAX_JSON_BYTES
        ):
            return jsonify({
                'error': 'Payload do Companion excede o limite permitido.',
                'code': 'COMPANION_PAYLOAD_TOO_LARGE',
                'max_bytes': COMPANION_MAX_JSON_BYTES,
            }), 413
        device = _companion_device_from_request()
        if not device:
            return jsonify({
                'error': 'Credencial do Toca Companion inválida ou revogada.',
                'code': 'COMPANION_AUTH_REQUIRED',
            }), 401
        g.companion_device = device
        return fn(*args, **kwargs)
    return _wrapper


def _companion_event(
    conn,
    task_id,
    event_type,
    *,
    actor_type,
    actor_id=None,
    from_status=None,
    to_status=None,
    message=None,
    details=None,
):
    conn.execute(
        '''INSERT INTO companion_task_events
           (task_id, actor_type, actor_id, event_type, from_status, to_status,
            message, details_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            task_id,
            actor_type,
            str(actor_id) if actor_id is not None else None,
            event_type,
            from_status,
            to_status,
            message,
            json.dumps(details, ensure_ascii=False) if details else None,
        ),
    )


def _companion_safe_file(path_value):
    candidate = Path(path_value or '').resolve()
    allowed_roots = (
        CHAMADO_JURIDICO_UPLOAD_DIR.resolve(),
        AUTOTOCA_SUPPORT_FILES_DIR.resolve(),
    )
    if not any(
        candidate == root or root in candidate.parents
        for root in allowed_roots
    ):
        raise ValueError('Arquivo fora do storage autorizado do Chamado Jurídico.')
    if not candidate.is_file():
        raise ValueError('Arquivo do Chamado Jurídico não está mais disponível.')
    return candidate


def _companion_file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _companion_idempotency_key(raw=None):
    value = str(raw or '').strip()
    if not value:
        return uuid.uuid4().hex
    if len(value) > 128 or not re.fullmatch(r'[A-Za-z0-9._:-]+', value):
        raise ValueError(
            'Idempotency-Key deve ter até 128 caracteres alfanuméricos.'
        )
    return value


def _companion_find_idempotent_task(owner_id, task_type, idempotency_key):
    if not idempotency_key:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            '''SELECT * FROM companion_tasks
               WHERE owner_id = ? AND task_type = ? AND idempotency_key = ?
               LIMIT 1''',
            (owner_id, task_type, idempotency_key),
        ).fetchone()
        return dict_from_row(row)
    finally:
        conn.close()


def _companion_enqueue_task(
    *,
    task_type,
    payload,
    history_id,
    files_by_field,
    idempotency_key,
):
    user = current_user()
    if not user:
        raise ValueError('Usuário não autenticado para criar tarefa do Companion.')
    owner_id = user['id']
    org_id = user.get('org_id')
    idempotency_key = _companion_idempotency_key(idempotency_key)

    existing = _companion_find_idempotent_task(
        owner_id, task_type, idempotency_key
    )
    if existing:
        return existing, False

    file_rows = []
    for field_key, entries in (files_by_field or {}).items():
        for entry in entries or []:
            stored_path = _companion_safe_file(entry.get('stored_path'))
            file_rows.append({
                'id': uuid.uuid4().hex,
                'field_key': str(field_key),
                'original_name': str(
                    entry.get('original_name') or stored_path.name
                )[:255],
                'stored_path': str(stored_path),
                'size_bytes': stored_path.stat().st_size,
                'sha256': _companion_file_sha256(stored_path),
            })

    task_id = uuid.uuid4().hex
    expires_at = _companion_timestamp(
        _companion_now() + timedelta(minutes=_companion_task_ttl_minutes())
    )
    task_payload = {
        'schema_version': COMPANION_PROTOCOL_VERSION,
        'task_type': task_type,
        'history_id': history_id,
        'form_url': AUTOTOCA_CHAMADO_JURIDICO_FORMS_URL,
        'fields': payload,
        'constraints': {
            'allow_submit': False,
            'requires_user_review': True,
        },
    }

    conn = get_db()
    try:
        try:
            conn.execute(
                '''INSERT INTO companion_tasks
                   (id, owner_id, org_id, task_type, idempotency_key,
                    payload_json, history_id, status, progress, step,
                    expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?)''',
                (
                    task_id,
                    owner_id,
                    org_id,
                    task_type,
                    idempotency_key,
                    json.dumps(task_payload, ensure_ascii=False),
                    history_id,
                    'Aguardando um Toca Companion vinculado...',
                    expires_at,
                ),
            )
            for file_row in file_rows:
                conn.execute(
                    '''INSERT INTO companion_task_files
                       (id, task_id, field_key, original_name, stored_path,
                        size_bytes, sha256)
                       VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (
                        file_row['id'],
                        task_id,
                        file_row['field_key'],
                        file_row['original_name'],
                        file_row['stored_path'],
                        file_row['size_bytes'],
                        file_row['sha256'],
                    ),
                )
            _companion_event(
                conn,
                task_id,
                'queued',
                actor_type='user',
                actor_id=owner_id,
                to_status='queued',
                message='Tarefa criada e aguardando o Toca Companion.',
                details={'file_count': len(file_rows)},
            )
            conn.commit()
        except Exception:
            conn.rollback()
            existing = conn.execute(
                '''SELECT * FROM companion_tasks
                   WHERE owner_id = ? AND task_type = ?
                     AND idempotency_key = ? LIMIT 1''',
                (owner_id, task_type, idempotency_key),
            ).fetchone()
            if existing:
                return dict_from_row(existing), False
            raise
        task = conn.execute(
            'SELECT * FROM companion_tasks WHERE id = ?',
            (task_id,),
        ).fetchone()
        return dict_from_row(task), True
    finally:
        conn.close()


def _companion_task_for_owner(task_id, owner_id=None):
    owner_id = owner_id if owner_id is not None else current_user_id()
    conn = get_db()
    try:
        _companion_expire_stale_tasks(conn, owner_id)
        row = conn.execute(
            '''SELECT * FROM companion_tasks
               WHERE id = ? AND owner_id = ? LIMIT 1''',
            (task_id, owner_id),
        ).fetchone()
        return dict_from_row(row)
    finally:
        conn.close()


def _companion_task_files(conn, task_id):
    rows = conn.execute(
        '''SELECT id, field_key, original_name, size_bytes, sha256
           FROM companion_task_files WHERE task_id = ?
           ORDER BY field_key, original_name''',
        (task_id,),
    ).fetchall()
    return [{
        **dict_from_row(row),
        'download_url': (
            f'/api/companion/v1/tasks/{task_id}/files/{row["id"]}'
        ),
    } for row in rows]


def _companion_task_payload(conn, task, *, include_lease_token=None):
    payload = {
        'protocol_version': COMPANION_PROTOCOL_VERSION,
        'task_id': task['id'],
        'type': task['task_type'],
        'status': task['status'],
        'progress': int(task.get('progress') or 0),
        'step': task.get('step'),
        'expires_at': str(task.get('expires_at') or ''),
        'payload': json.loads(task.get('payload_json') or '{}'),
        'files': _companion_task_files(conn, task['id']),
    }
    if include_lease_token:
        payload['lease_token'] = include_lease_token
        payload['lease_expires_at'] = str(task.get('lease_expires_at') or '')
    return payload


def _companion_expire_stale_tasks(conn, owner_id):
    now = _companion_now()
    now_value = _companion_timestamp(now)
    rows = conn.execute(
        '''SELECT * FROM companion_tasks
           WHERE owner_id = ? AND status NOT IN
             ('cancelled', 'succeeded', 'failed', 'expired')''',
        (owner_id,),
    ).fetchall()
    changed = False
    for raw in rows:
        task = dict_from_row(raw)
        old_status = task['status']
        new_status = None
        error_code = None
        message = None
        if (
            _companion_parse_timestamp(task.get('expires_at')) <= now
            and old_status == 'queued'
        ):
            new_status = 'expired'
            error_code = 'COMPANION_TASK_EXPIRED'
            message = 'A tarefa expirou antes de ser retirada por um Companion.'
        elif (
            old_status == 'leased'
            and task.get('lease_expires_at')
            and _companion_parse_timestamp(task['lease_expires_at']) <= now
        ):
            if int(task.get('attempt_count') or 0) < _companion_max_attempts():
                cursor = conn.execute(
                    '''UPDATE companion_tasks
                       SET status = 'queued', assigned_device_id = NULL,
                           lease_token_hash = NULL, lease_expires_at = NULL,
                           step = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND status = 'leased' ''',
                    ('Lease expirado; aguardando outro Companion...', task['id']),
                )
                if cursor.rowcount == 1:
                    _companion_event(
                        conn,
                        task['id'],
                        'lease_requeued',
                        actor_type='server',
                        from_status='leased',
                        to_status='queued',
                        message='Lease expirado antes do início; tarefa reenfileirada.',
                    )
                    changed = True
                continue
            new_status = 'failed'
            error_code = 'COMPANION_CLAIM_LIMIT'
            message = 'A tarefa excedeu o limite de tentativas de retirada.'
        elif (
            old_status == 'cancel_requested'
            and task.get('lease_expires_at')
            and _companion_parse_timestamp(task['lease_expires_at']) <= now
        ):
            new_status = 'cancelled'
            message = 'Cancelamento concluído após perda do lease do Companion.'
        elif (
            old_status in {'running', 'awaiting_user'}
            and task.get('lease_expires_at')
            and _companion_parse_timestamp(task['lease_expires_at']) <= now
        ):
            new_status = 'failed'
            error_code = 'COMPANION_CONNECTION_LOST'
            message = 'O Companion perdeu o lease durante a execução.'

        if new_status:
            cursor = conn.execute(
                '''UPDATE companion_tasks
                   SET status = ?, error_code = ?, error_message = ?,
                       completed_at = ?, updated_at = CURRENT_TIMESTAMP,
                       lease_token_hash = NULL, lease_expires_at = NULL
                   WHERE id = ? AND status = ?''',
                (
                    new_status,
                    error_code,
                    message,
                    now_value,
                    task['id'],
                    old_status,
                ),
            )
            if cursor.rowcount == 1:
                _companion_event(
                    conn,
                    task['id'],
                    new_status,
                    actor_type='server',
                    from_status=old_status,
                    to_status=new_status,
                    message=message,
                )
                changed = True
    if changed:
        conn.commit()


@app.route('/api/companion/pairings', methods=['POST'])
def companion_pairing_create():
    if not _auth_enabled():
        return jsonify({
            'error': 'O Toca Companion é usado somente no modo web autenticado.',
            'code': 'COMPANION_WEB_ONLY',
        }), 409
    user = current_user()
    code = _companion_new_pairing_code()
    normalized = _companion_normalize_pairing_code(code)
    expires_at = _companion_timestamp(
        _companion_now() + timedelta(minutes=_companion_pairing_ttl_minutes())
    )
    conn = get_db()
    try:
        now_value = _companion_timestamp(_companion_now())
        conn.execute(
            '''UPDATE companion_pairings SET expires_at = ?
               WHERE owner_id = ? AND claimed_at IS NULL AND expires_at > ?''',
            (now_value, user['id'], now_value),
        )
        conn.execute(
            '''INSERT INTO companion_pairings
               (code_hash, owner_id, org_id, expires_at)
               VALUES (?, ?, ?, ?)''',
            (
                _companion_secret_hash('pairing', normalized),
                user['id'],
                user.get('org_id'),
                expires_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    logger.info(
        '[Companion] Código de vínculo criado por user_id=%s; expira em %s.',
        user['id'],
        expires_at,
    )
    return jsonify({
        'pairing_code': code,
        'expires_at': expires_at,
        'protocol_version': COMPANION_PROTOCOL_VERSION,
    }), 201


@app.route('/api/companion/v1/pairings/claim', methods=['POST'])
def companion_pairing_claim():
    if not _auth_enabled():
        return jsonify({
            'error': 'O Toca Companion é usado somente no modo web autenticado.',
            'code': 'COMPANION_WEB_ONLY',
        }), 409
    if (
        request.content_length is not None
        and request.content_length > 8 * 1024
    ):
        return jsonify({
            'error': 'Payload de vínculo excede o limite permitido.',
            'code': 'COMPANION_PAYLOAD_TOO_LARGE',
            'max_bytes': 8 * 1024,
        }), 413
    data = request.get_json(silent=True) or {}
    normalized = _companion_normalize_pairing_code(data.get('pairing_code'))
    if len(normalized) != COMPANION_PAIRING_LENGTH:
        return jsonify({
            'error': 'Código de vínculo inválido ou expirado.',
            'code': 'COMPANION_PAIRING_INVALID',
        }), 400
    name = str(data.get('device_name') or '').strip()
    platform = str(data.get('platform') or '').strip()
    app_version = str(data.get('app_version') or '').strip()
    if not name or len(name) > 80:
        return jsonify({
            'error': 'Informe um nome de dispositivo com até 80 caracteres.',
            'code': 'COMPANION_DEVICE_NAME_INVALID',
        }), 400
    if len(platform) > 40 or len(app_version) > 32:
        return jsonify({
            'error': 'Metadados do dispositivo excedem o limite.',
            'code': 'COMPANION_DEVICE_METADATA_INVALID',
        }), 400

    code_hash = _companion_secret_hash('pairing', normalized)
    now_value = _companion_timestamp(_companion_now())
    device_id = uuid.uuid4().hex
    raw_token = secrets.token_urlsafe(32)
    conn = get_db()
    try:
        row = conn.execute(
            '''SELECT p.*
               FROM companion_pairings p
               JOIN users u ON u.id = p.owner_id
               WHERE p.code_hash = ? AND p.claimed_at IS NULL
                 AND p.expires_at > ? AND COALESCE(u.is_active, 1) = 1
               LIMIT 1''',
            (code_hash, now_value),
        ).fetchone()
        if not row:
            return jsonify({
                'error': 'Código de vínculo inválido ou expirado.',
                'code': 'COMPANION_PAIRING_INVALID',
            }), 404
        pairing = dict_from_row(row)
        cursor = conn.execute(
            '''UPDATE companion_pairings SET claimed_at = ?
               WHERE id = ? AND claimed_at IS NULL AND expires_at > ?''',
            (now_value, pairing['id'], now_value),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return jsonify({
                'error': 'Este código de vínculo já foi utilizado.',
                'code': 'COMPANION_PAIRING_ALREADY_CLAIMED',
            }), 409
        conn.execute(
            '''INSERT INTO companion_devices
               (id, owner_id, org_id, name, platform, app_version, token_hash,
                last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                device_id,
                pairing['owner_id'],
                pairing.get('org_id'),
                name,
                platform[:40] or None,
                app_version[:32] or None,
                _companion_secret_hash('device', raw_token),
                now_value,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    logger.info(
        '[Companion] Dispositivo %s vinculado a user_id=%s.',
        device_id,
        pairing['owner_id'],
    )
    return jsonify({
        'device_id': device_id,
        'device_token': raw_token,
        'protocol_version': COMPANION_PROTOCOL_VERSION,
    }), 201


@app.route('/api/companion/devices', methods=['GET'])
def companion_devices_list():
    if not _auth_enabled():
        return jsonify([])
    conn = get_db()
    try:
        rows = conn.execute(
            '''SELECT id, name, platform, app_version, status, paired_at,
                      last_seen_at, revoked_at
               FROM companion_devices WHERE owner_id = ?
               ORDER BY paired_at DESC''',
            (current_user_id(),),
        ).fetchall()
        return jsonify([dict_from_row(row) for row in rows])
    finally:
        conn.close()


@app.route('/api/companion/devices/<device_id>', methods=['DELETE'])
def companion_device_revoke(device_id):
    conn = get_db()
    try:
        cursor = conn.execute(
            '''UPDATE companion_devices
               SET status = 'revoked', revoked_at = CURRENT_TIMESTAMP,
                   token_hash = ?
               WHERE id = ? AND owner_id = ? AND status = 'active' ''',
            (
                _companion_secret_hash(
                    'revoked-device', f'{device_id}:{secrets.token_hex(16)}'
                ),
                device_id,
                current_user_id(),
            ),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return jsonify({'error': 'Companion não encontrado.'}), 404
        active_tasks = conn.execute(
            '''SELECT id, status FROM companion_tasks
               WHERE assigned_device_id = ?
                 AND status IN ('leased', 'running', 'awaiting_user')''',
            (device_id,),
        ).fetchall()
        for active_row in active_tasks:
            active_task = dict_from_row(active_row)
            conn.execute(
                '''UPDATE companion_tasks
                   SET status = 'cancel_requested',
                       step = 'Cancelamento solicitado: Companion revogado.',
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = ?''',
                (active_task['id'], active_task['status']),
            )
            _companion_event(
                conn,
                active_task['id'],
                'cancel_requested',
                actor_type='user',
                actor_id=current_user_id(),
                from_status=active_task['status'],
                to_status='cancel_requested',
                message='Companion revogado pelo usuário.',
            )
        conn.commit()
    finally:
        conn.close()
    logger.info(
        '[Companion] Dispositivo %s revogado por user_id=%s.',
        device_id,
        current_user_id(),
    )
    return ('', 204)


@app.route('/api/companion/tasks/<task_id>', methods=['GET'])
def companion_task_status_web(task_id):
    task = _companion_task_for_owner(task_id)
    if not task:
        return jsonify({'error': 'Tarefa não encontrada.'}), 404
    conn = get_db()
    try:
        events = conn.execute(
            '''SELECT actor_type, event_type, from_status, to_status, message,
                      created_at
               FROM companion_task_events WHERE task_id = ?
               ORDER BY id DESC LIMIT 50''',
            (task_id,),
        ).fetchall()
    finally:
        conn.close()
    result = json.loads(task.get('result_json') or '{}')
    return jsonify({
        'task_id': task['id'],
        'type': task['task_type'],
        'status': task['status'],
        'progress': int(task.get('progress') or 0),
        'step': task.get('step'),
        'error_code': task.get('error_code'),
        'error': task.get('error_message'),
        'result': result,
        'expires_at': str(task.get('expires_at') or ''),
        'created_at': str(task.get('created_at') or ''),
        'updated_at': str(task.get('updated_at') or ''),
        'events': [dict_from_row(row) for row in events],
    })


@app.route('/api/companion/tasks/<task_id>/cancel', methods=['POST'])
def companion_task_cancel_web(task_id):
    owner_id = current_user_id()
    conn = get_db()
    try:
        _companion_expire_stale_tasks(conn, owner_id)
        row = conn.execute(
            '''SELECT * FROM companion_tasks
               WHERE id = ? AND owner_id = ? LIMIT 1''',
            (task_id, owner_id),
        ).fetchone()
        if not row:
            return jsonify({'error': 'Tarefa não encontrada.'}), 404
        task = dict_from_row(row)
        old_status = task['status']
        if old_status in COMPANION_TERMINAL_STATUSES:
            return jsonify({
                'task_id': task_id,
                'status': old_status,
                'already_terminal': True,
            })
        new_status = (
            'cancelled' if old_status == 'queued' else 'cancel_requested'
        )
        completed_at = (
            _companion_timestamp(_companion_now())
            if new_status == 'cancelled' else None
        )
        conn.execute(
            '''UPDATE companion_tasks
               SET status = ?, step = ?, completed_at = ?,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND owner_id = ?''',
            (
                new_status,
                'Tarefa cancelada.' if new_status == 'cancelled'
                else 'Cancelamento solicitado ao Companion.',
                completed_at,
                task_id,
                owner_id,
            ),
        )
        _companion_event(
            conn,
            task_id,
            'cancel_requested' if new_status == 'cancel_requested'
            else 'cancelled',
            actor_type='user',
            actor_id=owner_id,
            from_status=old_status,
            to_status=new_status,
            message='Cancelamento solicitado pelo usuário.',
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({'task_id': task_id, 'status': new_status})


@app.route('/api/companion/v1/tasks/next', methods=['POST'])
@companion_device_required
def companion_task_next():
    device = g.companion_device
    data = request.get_json(silent=True) or {}
    current_version = str(
        data.get('app_version')
        or request.headers.get('X-Toca-Companion-Version')
        or device.get('app_version')
        or ''
    ).strip()[:32]
    if _companion_version_below_minimum(current_version):
        return jsonify({
            'error': 'Atualize o Toca Companion antes de retirar tarefas.',
            'code': 'COMPANION_UPDATE_REQUIRED',
            'minimum_version': _companion_minimum_version(),
        }), 426
    conn = get_db()
    try:
        if current_version:
            conn.execute(
                '''UPDATE companion_devices SET app_version = ?
                   WHERE id = ?''',
                (current_version, device['id']),
            )
            conn.commit()
        _companion_expire_stale_tasks(conn, device['owner_id'])
        candidates = conn.execute(
            '''SELECT * FROM companion_tasks
               WHERE owner_id = ? AND status = 'queued'
                 AND expires_at > ?
                 AND (assigned_device_id IS NULL OR assigned_device_id = ?)
               ORDER BY created_at, id LIMIT 10''',
            (
                device['owner_id'],
                _companion_timestamp(_companion_now()),
                device['id'],
            ),
        ).fetchall()
        for raw in candidates:
            task = dict_from_row(raw)
            lease_token = secrets.token_urlsafe(32)
            lease_expires_at = _companion_timestamp(
                _companion_now() + timedelta(seconds=_companion_lease_seconds())
            )
            cursor = conn.execute(
                '''UPDATE companion_tasks
                   SET status = 'leased', assigned_device_id = ?,
                       lease_token_hash = ?, lease_expires_at = ?,
                       attempt_count = attempt_count + 1,
                       step = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'queued' ''',
                (
                    device['id'],
                    _companion_secret_hash('lease', lease_token),
                    lease_expires_at,
                    'Tarefa retirada pelo Toca Companion.',
                    task['id'],
                ),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                continue
            _companion_event(
                conn,
                task['id'],
                'leased',
                actor_type='device',
                actor_id=device['id'],
                from_status='queued',
                to_status='leased',
                message='Tarefa retirada pelo Toca Companion.',
            )
            conn.commit()
            claimed = conn.execute(
                'SELECT * FROM companion_tasks WHERE id = ?',
                (task['id'],),
            ).fetchone()
            return jsonify(_companion_task_payload(
                conn,
                dict_from_row(claimed),
                include_lease_token=lease_token,
            ))
        return ('', 204)
    finally:
        conn.close()


def _companion_validate_lease(task, device, lease_token):
    if task.get('assigned_device_id') != device.get('id'):
        return False
    expected = str(task.get('lease_token_hash') or '')
    supplied = _companion_secret_hash('lease', lease_token or '')
    return bool(expected) and _companion_hmac.compare_digest(expected, supplied)


@app.route('/api/companion/v1/tasks/<task_id>', methods=['PATCH'])
@companion_device_required
def companion_task_update(task_id):
    device = g.companion_device
    lease_token = (request.headers.get('X-Toca-Task-Lease') or '').strip()
    data = request.get_json(silent=True) or {}
    conn = get_db()
    try:
        row = conn.execute(
            'SELECT * FROM companion_tasks WHERE id = ? LIMIT 1',
            (task_id,),
        ).fetchone()
        if not row:
            return jsonify({'error': 'Tarefa não encontrada.'}), 404
        task = dict_from_row(row)
        if (
            task.get('owner_id') != device.get('owner_id')
            or not _companion_validate_lease(task, device, lease_token)
        ):
            return jsonify({
                'error': 'Lease da tarefa inválido.',
                'code': 'COMPANION_TASK_LEASE_INVALID',
            }), 403
        if task['status'] in COMPANION_TERMINAL_STATUSES:
            return jsonify({
                'task_id': task_id,
                'status': task['status'],
                'already_terminal': True,
            })
        lease_expires = _companion_parse_timestamp(task.get('lease_expires_at'))
        if not lease_expires or lease_expires <= _companion_now():
            return jsonify({
                'error': 'O lease da tarefa expirou.',
                'code': 'COMPANION_TASK_LEASE_EXPIRED',
            }), 409

        requested_status = str(data.get('status') or task['status']).strip()
        old_status = task['status']
        if requested_status != old_status and requested_status not in (
            COMPANION_ALLOWED_TRANSITIONS.get(old_status) or frozenset()
        ):
            return jsonify({
                'error': (
                    f'Transição inválida: {old_status} → {requested_status}.'
                ),
                'code': 'COMPANION_TASK_TRANSITION_INVALID',
            }), 409
        result = data.get('result') if isinstance(data.get('result'), dict) else {}
        if bool(result.get('submitted')):
            return jsonify({
                'error': 'O Companion não pode enviar o formulário automaticamente.',
                'code': 'COMPANION_AUTO_SUBMIT_FORBIDDEN',
            }), 422

        progress = data.get('progress', task.get('progress') or 0)
        try:
            progress = min(100, max(0, int(progress)))
        except (TypeError, ValueError):
            return jsonify({
                'error': 'Progresso inválido.',
                'code': 'COMPANION_PROGRESS_INVALID',
            }), 400
        step = str(data.get('step') or task.get('step') or '').strip()[:500]
        terminal = requested_status in COMPANION_TERMINAL_STATUSES
        now_value = _companion_timestamp(_companion_now())
        new_lease_expires = None if terminal else _companion_timestamp(
            _companion_now() + timedelta(seconds=_companion_lease_seconds())
        )
        started_at = (
            now_value
            if requested_status == 'running' and not task.get('started_at')
            else task.get('started_at')
        )
        completed_at = now_value if terminal else None
        error_code = str(data.get('error_code') or '').strip()[:80] or None
        error_message = (
            str(data.get('error_message') or '').strip()[:2000] or None
        )
        conn.execute(
            '''UPDATE companion_tasks
               SET status = ?, progress = ?, step = ?, lease_expires_at = ?,
                   lease_token_hash = ?, result_json = ?, error_code = ?,
                   error_message = ?, started_at = ?, completed_at = ?,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ?''',
            (
                requested_status,
                progress,
                step,
                new_lease_expires,
                None if terminal else task.get('lease_token_hash'),
                json.dumps(result, ensure_ascii=False) if result else None,
                error_code,
                error_message,
                started_at,
                completed_at,
                task_id,
            ),
        )
        if requested_status != old_status or step != (task.get('step') or ''):
            _companion_event(
                conn,
                task_id,
                requested_status if requested_status != old_status else 'progress',
                actor_type='device',
                actor_id=device['id'],
                from_status=old_status,
                to_status=requested_status,
                message=step or None,
                details={'progress': progress},
            )
        conn.commit()
        return jsonify({
            'task_id': task_id,
            'status': requested_status,
            'lease_expires_at': new_lease_expires,
            'cancel_requested': requested_status == 'cancel_requested',
        })
    finally:
        conn.close()


@app.route(
    '/api/companion/v1/tasks/<task_id>/files/<file_id>',
    methods=['GET'],
)
@companion_device_required
def companion_task_file_download(task_id, file_id):
    device = g.companion_device
    lease_token = (request.headers.get('X-Toca-Task-Lease') or '').strip()
    conn = get_db()
    try:
        task_row = conn.execute(
            'SELECT * FROM companion_tasks WHERE id = ? LIMIT 1',
            (task_id,),
        ).fetchone()
        if not task_row:
            return jsonify({'error': 'Tarefa não encontrada.'}), 404
        task = dict_from_row(task_row)
        if (
            task.get('owner_id') != device.get('owner_id')
            or not _companion_validate_lease(task, device, lease_token)
            or task.get('status') not in COMPANION_ACTIVE_STATUSES
            or not task.get('lease_expires_at')
            or _companion_parse_timestamp(task['lease_expires_at'])
            <= _companion_now()
        ):
            return jsonify({
                'error': 'Lease da tarefa inválido.',
                'code': 'COMPANION_TASK_LEASE_INVALID',
            }), 403
        row = conn.execute(
            '''SELECT * FROM companion_task_files
               WHERE id = ? AND task_id = ? LIMIT 1''',
            (file_id, task_id),
        ).fetchone()
        if not row:
            return jsonify({'error': 'Arquivo não encontrado.'}), 404
        file_row = dict_from_row(row)
    finally:
        conn.close()
    try:
        path = _companion_safe_file(file_row['stored_path'])
    except ValueError:
        logger.warning(
            '[Companion] Arquivo indisponível task=%s file=%s.',
            task_id,
            file_id,
        )
        return jsonify({
            'error': 'Arquivo não está mais disponível.',
            'code': 'COMPANION_FILE_UNAVAILABLE',
        }), 410
    if (
        path.stat().st_size != int(file_row['size_bytes'])
        or not _companion_hmac.compare_digest(
            _companion_file_sha256(path),
            str(file_row['sha256']),
        )
    ):
        logger.error(
            '[Companion] Integridade divergente task=%s file=%s.',
            task_id,
            file_id,
        )
        return jsonify({
            'error': 'A integridade do arquivo não pôde ser confirmada.',
            'code': 'COMPANION_FILE_INTEGRITY_MISMATCH',
        }), 409
    return send_file(
        path,
        as_attachment=True,
        download_name=file_row['original_name'],
        max_age=0,
    )


@app.route('/api/companion/v1/manifest', methods=['GET'])
@companion_device_required
def companion_update_manifest():
    device = g.companion_device
    latest = _normalize_version(
        os.environ.get('TOCA_COMPANION_LATEST_VERSION', '')
    )
    minimum = _companion_minimum_version()
    download_url = (
        os.environ.get('TOCA_COMPANION_DOWNLOAD_URL') or ''
    ).strip()
    parsed_download_url = urlparse(download_url) if download_url else None
    if (
        parsed_download_url
        and (
            parsed_download_url.scheme.lower() != 'https'
            or not parsed_download_url.netloc
        )
    ):
        download_url = ''
    sha256_value = (
        os.environ.get('TOCA_COMPANION_DOWNLOAD_SHA256') or ''
    ).strip().lower()
    if sha256_value and not re.fullmatch(r'[0-9a-f]{64}', sha256_value):
        sha256_value = ''
    current = _normalize_version(
        request.args.get('current_version') or device.get('app_version') or ''
    )
    update_available = bool(
        latest and (
            not current or _version_key(latest) > _version_key(current)
        )
    )
    update_required = bool(
        minimum and (
            not current or _version_key(minimum) > _version_key(current)
        )
    )
    return jsonify({
        'protocol_version': COMPANION_PROTOCOL_VERSION,
        'current_version': current or None,
        'latest_version': latest or None,
        'minimum_version': minimum or None,
        'update_available': update_available,
        'update_required': update_required,
        'download': {
            'url': download_url or None,
            'sha256': sha256_value or None,
        } if latest and download_url and sha256_value else None,
    })
