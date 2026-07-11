"""'Siga o campeão' (Bloco 11): mudança de emprego via extensão."""


def _mk_linkedin_client(client):
    resp = client.post('/api/clientes', data={
        'name': 'Campeao Silva', 'company': 'Empresa Velha', 'position': 'Diretor de TI',
        'linkedin': 'https://www.linkedin.com/in/campeao-silva/',
    })
    assert resp.status_code == 201
    return resp.get_json()['id']


def test_auto_capture_gera_evento_e_sugestao(client, db_path, monkeypatch):
    import app as toca
    cid = _mk_linkedin_client(client)

    wl = client.get('/api/linkedin/watchlist').get_json()
    assert any(w['slug'] == 'campeao-silva' for w in wl)

    monkeypatch.setattr(toca, '_llm_openrouter_first',
                        lambda *a, **k: '{"empresa_atual": "Empresa Nova SA", "cargo_atual": "CIO"}')
    resp = client.post('/api/linkedin/auto-capture', json={
        'url': 'https://www.linkedin.com/in/campeao-silva/',
        'text': 'Campeao Silva — CIO na Empresa Nova SA. ' + 'x' * 300,
    })
    payload = resp.get_json()
    assert payload['changed'] is True
    assert payload['potential_new_account'] is True
    event_id = payload['event_id']

    # captura repetida não duplica evento pendente
    resp2 = client.post('/api/linkedin/auto-capture', json={
        'url': 'https://www.linkedin.com/in/campeao-silva/',
        'text': 'Campeao Silva — CIO na Empresa Nova SA. ' + 'x' * 300,
    })
    assert resp2.get_json().get('duplicate') is True

    # sugestão de alta prioridade no Radar
    items = client.get('/api/suggestions/today').get_json()
    jc = [s for s in items if s['suggestion_type'] == 'job_change']
    assert jc and 'Empresa Nova SA' in jc[0]['title']

    # ação em um clique: cria conta + card e trata o evento
    resp3 = client.post(f'/api/job-changes/{event_id}/open-account')
    p3 = resp3.get_json()
    assert resp3.status_code == 200 and p3['account_id'] and p3['card_id']

    conn = toca.get_db()
    assert conn.execute("SELECT status FROM job_change_events WHERE id = ?", (event_id,)).fetchone()[0] == 'tratado'
    # ação repetida não duplica o card
    resp4 = client.post(f'/api/job-changes/{event_id}/open-account')
    assert resp4.get_json()['card_id'] == p3['card_id']
    conn.close()


def test_auto_capture_mesma_empresa_nao_gera_evento(client, db_path, monkeypatch):
    import app as toca
    _mk_linkedin_client(client)
    monkeypatch.setattr(toca, '_llm_openrouter_first',
                        lambda *a, **k: '{"empresa_atual": "Empresa Velha", "cargo_atual": "Diretor de TI"}')
    resp = client.post('/api/linkedin/auto-capture', json={
        'url': 'https://www.linkedin.com/in/campeao-silva/',
        'text': 'Campeao Silva — Diretor de TI na Empresa Velha. ' + 'x' * 300,
    })
    assert resp.get_json()['changed'] is False


def test_briefing_cache(client, sample_client_id, db_path, monkeypatch):
    import app as toca
    conn = toca.get_db()
    conn.execute("INSERT INTO commitments (client_id, title, due_date, source_type) "
                 "VALUES (?, 'Reunião de alinhamento', date('now', 'localtime'), 'activity')",
                 (sample_client_id,))
    conn.commit()
    cid = conn.execute('SELECT id FROM commitments ORDER BY id DESC LIMIT 1').fetchone()[0]

    calls = {'n': 0}
    def fake_llm(*a, **k):
        calls['n'] += 1
        return '## Contexto\n- teste\n## Últimos assuntos\n- x\n## Pendências suas\n- y\n## Pendências dele\n- z\n## Oportunidades em aberto\n- w\n## Sugestão de pauta\n- k'
    monkeypatch.setattr(toca, '_llm_openrouter_first', fake_llm)

    c = conn.cursor()
    commitment = dict(conn.execute('SELECT * FROM commitments WHERE id = ?', (cid,)).fetchone())
    r1 = toca._generate_briefing(c, commitment)
    conn.commit()
    assert not r1['cached'] and calls['n'] == 1
    # segunda chamada usa o cache — não regera
    r2 = toca._generate_briefing(c, commitment)
    assert r2['cached'] and calls['n'] == 1
    # refresh força regeração
    r3 = toca._generate_briefing(c, commitment, force=True)
    assert not r3['cached'] and calls['n'] == 2
    conn.close()

    # GET do cache responde rápido
    resp = client.get(f'/api/commitments/{cid}/briefing')
    assert resp.status_code == 200 and 'Contexto' in resp.get_json()['content']
