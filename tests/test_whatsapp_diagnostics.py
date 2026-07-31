import app as toca


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = ''

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    def json(self):
        return self._payload


def test_whatsapp_diagnostics_combines_and_redacts_logs(client, tmp_path, monkeypatch):
    app_log = tmp_path / 'app.log'
    waha_log = tmp_path / 'waha-lite.log'
    app_log.write_text(
        '[WhatsApp Sync][sync:abc123] contato 5511999999999@c.us\n'
        '[Outro] linha que não pertence à execução\n',
        encoding='utf-8',
    )
    waha_log.write_text(
        '[INFO] [sync:abc123] consulta 5511888888888@c.us\n'
        '[WARN] [sync:abc123] X-Api-Key: segredo\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(toca, 'LOG_FILE', app_log)
    monkeypatch.setattr(toca, '_waha_log_file_path', lambda: waha_log)

    def fake_get(url, **_kwargs):
        if url.endswith('/ping'):
            return _FakeResponse(200, {'status': 'WORKING'})
        return _FakeResponse(200, {'status': 'WORKING'})

    monkeypatch.setattr(toca.requests, 'get', fake_get)

    response = client.get('/api/whatsapp/diagnostics?run_id=abc123&limit=50')
    assert response.status_code == 200
    data = response.get_json()
    assert data['health']['reachable'] is True
    assert data['health']['session_state'] == 'WORKING'
    assert len(data['app_log']) == 1
    combined = '\n'.join(data['app_log'] + data['waha_log'])
    assert '5511999999999' not in combined
    assert '5511888888888' not in combined
    assert 'segredo' not in combined
    assert '<contato>' in combined
    assert '<redigido>' in combined


def test_whatsapp_sync_reports_why_contacts_were_skipped(
    client, db_path, monkeypatch, caplog
):
    conn = toca.get_db()
    conn.execute(
        "INSERT INTO clients (name, company, position, phone, is_archived) VALUES (?, ?, ?, ?, 0)",
        ('Contato de Teste', 'Empresa Teste', 'Gerente', '11999999999'),
    )
    conn.commit()
    conn.close()

    def fake_get(_url, **kwargs):
        assert kwargs['headers']['X-Toca-Sync-Id'] == 'abc123def456'
        return _FakeResponse(
            404,
            {'code': 'CHAT_NOT_FOUND', 'error': 'Sem conversa.'},
            {
                'X-WAHA-Match-Strategy': 'not-found',
                'X-WAHA-Available-Chats': '42',
            },
        )

    monkeypatch.setattr(toca.requests, 'get', fake_get)
    monkeypatch.setattr(toca, '_bg_task_cleanup', lambda *_args, **_kwargs: None)
    task_id = 'abc123def4567890'
    caplog.set_level('INFO')

    try:
        toca._bg_task_set(task_id, {'status': 'processing'})
        toca._whatsapp_sync_async(task_id, 7)
        task = toca._bg_task_get(task_id)
        result = task['result']
        assert task['status'] == 'done'
        assert result['pending'] == 0
        assert result['diagnostics']['run_id'] == 'abc123def456'
        assert result['diagnostics']['counts']['chat_not_found'] == 1
        assert 'nenhuma conversa correspondeu' in result['diagnostics']['summary']
        assert any(
            '[sync:abc123def456]' in record.message and 'motivo=chat_not_found' in record.message
            for record in caplog.records
        )
    finally:
        with toca._bg_tasks_lock:
            toca._bg_tasks.pop(task_id, None)
        toca._bg_persistent_kinds.pop(task_id, None)


def test_old_local_waha_gateway_is_restarted_before_sync(monkeypatch):
    state = {'restarted': False}

    def fake_get(url, **_kwargs):
        if url.endswith('/ping'):
            if state['restarted']:
                return _FakeResponse(200, {
                    'pid': 222,
                    'status': 'WORKING',
                    'gatewayVersion': 4,
                    'capabilities': [
                        'chat-list-match',
                        'sync-diagnostics',
                        'cached-message-fetch',
                        'bounded-history-fetch',
                    ],
                })
            return _FakeResponse(200, {'pid': 111, 'status': 'WORKING'})
        return _FakeResponse(200, {'status': 'WORKING'})

    def fake_restart():
        state['restarted'] = True
        return True

    monkeypatch.setattr(toca.requests, 'get', fake_get)
    monkeypatch.setattr(toca, '_restart_waha_lite', fake_restart)

    updated = toca._waha_ensure_sync_gateway(
        'http://localhost:3001',
        {'X-Api-Key': 'teste'},
        'default',
        'task-test',
        '[WhatsApp Sync][sync:test]',
    )

    assert updated is True
    assert state['restarted'] is True


def test_whatsapp_scope_matches_active_contacts_with_phone(client):
    conn = toca.get_db()
    conn.executemany(
        """INSERT INTO clients (name, company, position, phone, is_archived)
           VALUES (?, 'Empresa', 'Cargo', ?, ?)""",
        [
            ('Ativo com telefone', '11999999999', 0),
            ('Ativo sem telefone', '', 0),
            ('Arquivado com telefone', '11888888888', 1),
        ],
    )
    conn.commit()
    conn.close()

    response = client.get('/api/whatsapp/scope')
    assert response.status_code == 200
    scope = response.get_json()['scope']
    assert scope == {
        'total': 3,
        'active_total': 2,
        'active_with_phone': 1,
        'active_without_phone': 1,
        'archived_with_phone': 1,
    }
