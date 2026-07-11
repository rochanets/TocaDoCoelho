"""Radar do Dia (Bloco 5): priorização, filtros e reposição."""


def _mk_client(client, name, company='ACME', position='CEO', **extra):
    data = {'name': name, 'company': company, 'position': position}
    data.update(extra)
    resp = client.post('/api/clientes', data=data)
    assert resp.status_code == 201
    return resp.get_json()['id']


def test_radar_prioriza_nunca_contatado_e_filtra_arquivado(client, db_path):
    import app as toca
    nunca_id = _mk_client(client, 'Nunca Contatado')
    atrasado_id = _mk_client(client, 'Atrasado Quinze')
    arquivado_id = _mk_client(client, 'Contato Arquivado')
    frio_id = _mk_client(client, 'Contato Frio', is_cold_contact='1')

    conn = toca.get_db()
    # atrasado: 15 dias sem contato (threshold universal 7/14)
    conn.execute("UPDATE clients SET last_activity_date = datetime('now', '-15 days') WHERE id = ?", (atrasado_id,))
    conn.execute("UPDATE clients SET is_archived = 1 WHERE id = ?", (arquivado_id,))
    conn.commit()
    conn.close()

    items = client.get('/api/suggestions/today').get_json()
    overdue = [s for s in items if s['suggestion_type'] == 'contact_overdue']
    titles = [s['title'] for s in overdue]
    assert any('Nunca Contatado' in t for t in titles)
    assert any('Atrasado Quinze' in t for t in titles)
    # nunca contatado vem antes do atrasado de 15 dias
    assert titles.index(next(t for t in titles if 'Nunca Contatado' in t)) < \
           titles.index(next(t for t in titles if 'Atrasado Quinze' in t))
    # arquivado e frio nunca aparecem em nenhuma categoria
    all_titles = ' '.join(s['title'] for s in items)
    assert 'Contato Arquivado' not in all_titles
    assert 'Contato Frio' not in all_titles


def test_radar_followup_vencido(client, sample_client_id, db_path):
    import app as toca
    conn = toca.get_db()
    conn.execute(
        "INSERT INTO commitments (client_id, title, due_date, source_type) VALUES (?, 'Retornar proposta', date('now', '-3 days'), 'activity')",
        (sample_client_id,))
    conn.commit()
    conn.close()
    items = client.get('/api/suggestions/today').get_json()
    fups = [s for s in items if s['suggestion_type'] == 'followup_overdue']
    assert fups and 'Retornar proposta' in fups[0]['description']


def test_radar_completar_repoe_e_snooze_esconde(client, db_path):
    for i in range(12):
        _mk_client(client, f'Cliente Sem Contato {i:02d}')

    items = client.get('/api/suggestions/today').get_json()
    active = [s for s in items if not s['completed']]
    assert len(active) == 8  # RADAR_MAX_ACTIVE

    # completar uma => reposição mantém 8 ativas
    sid = active[0]['id']
    assert client.post(f'/api/suggestions/{sid}/complete').status_code == 200
    items2 = client.get('/api/suggestions/today').get_json()
    active2 = [s for s in items2 if not s['completed']]
    assert len(active2) == 8
    assert sid not in [s['id'] for s in active2]

    # adiar uma => some da lista de hoje
    sid2 = active2[0]['id']
    resp = client.post(f'/api/suggestions/{sid2}/snooze', json={'days': 2})
    assert resp.status_code == 200
    items3 = client.get('/api/suggestions/today').get_json()
    assert sid2 not in [s['id'] for s in items3]


def test_radar_aniversario_na_semana(client, db_path):
    from datetime import datetime, timedelta
    bday = (datetime.now() + timedelta(days=2)).strftime('%d/%m')
    resp = client.post('/api/clientes', data={
        'name': 'Aniversariante Silva', 'company': 'ACME', 'position': 'CEO',
        'birthday': bday,
    })
    assert resp.status_code == 201
    items = client.get('/api/suggestions/today').get_json()
    bdays = [s for s in items if s['suggestion_type'] == 'birthday']
    assert bdays and 'Aniversariante Silva' in bdays[0]['title']


def test_thread_score_single_threaded(client, db_path):
    import app as toca
    # conta target com 1 contato ativo => risco
    client.post('/api/clientes', data={'name': 'Unico Contato', 'company': 'SoloCorp', 'position': 'Gerente de TI'})
    conn = toca.get_db()
    conn.execute("UPDATE clients SET last_activity_date = datetime('now', '-1 day') WHERE name = 'Unico Contato'")
    conn.execute("UPDATE accounts SET is_target = 1 WHERE LOWER(TRIM(name)) = 'solocorp'")
    row = conn.execute("SELECT id FROM accounts WHERE LOWER(TRIM(name)) = 'solocorp'").fetchone()
    conn.commit()
    conn.close()
    assert row is not None
    score = client.get(f'/api/accounts/{row[0]}/thread-score').get_json()
    assert score['single_threaded'] is True
    assert score['active_contacts'] == 1
    assert 'C-level' in score['missing_levels']

    # aparece no Radar com o nível ausente
    items = client.get('/api/suggestions/today').get_json()
    mt = [s for s in items if s['suggestion_type'] == 'multithreading']
    assert mt and 'SoloCorp' in mt[0]['title']
    assert 'C-level' in mt[0]['description']


def test_whitespace_por_conta(client, db_path):
    import app as toca
    client.post('/api/clientes', data={'name': 'Contato WS', 'company': 'WhiteCorp', 'position': 'CEO'})
    conn = toca.get_db()
    conn.execute("UPDATE accounts SET is_target = 1 WHERE LOWER(TRIM(name)) = 'whitecorp'")
    acc_id = conn.execute("SELECT id FROM accounts WHERE LOWER(TRIM(name)) = 'whitecorp'").fetchone()[0]
    conn.execute("INSERT INTO portfolio_offers (title) VALUES ('Cloud Services')")
    conn.execute("INSERT INTO portfolio_offers (title) VALUES ('Cybersecurity')")
    conn.execute("INSERT INTO account_presences (account_id, delivery_name) VALUES (?, 'Cloud Services')", (acc_id,))
    conn.commit()
    conn.close()

    ws = client.get(f'/api/accounts/{acc_id}/whitespace').get_json()
    assert [o['title'] for o in ws['present']] == ['Cloud Services']
    assert [o['title'] for o in ws['missing']] == ['Cybersecurity']

    matrix = client.get('/api/portfolio/whitespace-matrix').get_json()
    row = next(r for r in matrix['rows'] if r['name'] == 'WhiteCorp')
    cyber = next(o for o in matrix['offers'] if o['title'] == 'Cybersecurity')
    cloud = next(o for o in matrix['offers'] if o['title'] == 'Cloud Services')
    assert row['cells'][str(cloud['id'])] is True
    assert row['cells'][str(cyber['id'])] is False

    # sugestão no Radar não repete oferta presente
    items = client.get('/api/suggestions/today').get_json()
    ws_sugs = [s for s in items if s['suggestion_type'] == 'whitespace']
    assert ws_sugs and 'Cybersecurity' in ws_sugs[0]['title']
    assert 'Cloud Services' not in ws_sugs[0]['title']
