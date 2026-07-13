"""Testes de fumaça das rotas principais — referência de comportamento a
preservar durante a modularização (Bloco 3)."""


def test_home_overview(client):
    resp = client.get('/api/home/overview')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'accounts' in data or 'contacts' in data or isinstance(data, dict)


def test_client_crud(client):
    # criar
    resp = client.post('/api/clientes', data={
        'name': 'Maria CRUD', 'company': 'ACME', 'position': 'CIO',
    })
    assert resp.status_code == 201
    cid = resp.get_json()['id']

    # campos obrigatórios
    resp = client.post('/api/clientes', data={'name': 'Sem Empresa'})
    assert resp.status_code == 400

    # listar (alias pt e en devem responder igual)
    for url in ('/api/clientes', '/api/clients'):
        resp = client.get(url)
        assert resp.status_code == 200
        assert any(c['id'] == cid for c in resp.get_json())

    # detalhe
    resp = client.get(f'/api/clients/{cid}')
    assert resp.status_code == 200
    assert resp.get_json()['name'] == 'Maria CRUD'

    # atualizar
    resp = client.put(f'/api/clientes/{cid}', data={
        'name': 'Maria CRUD', 'company': 'ACME', 'position': 'CTO',
    })
    assert resp.status_code == 200
    assert client.get(f'/api/clients/{cid}').get_json()['position'] == 'CTO'

    # excluir
    resp = client.delete(f'/api/clientes/{cid}')
    assert resp.status_code == 200
    assert client.get(f'/api/clients/{cid}').status_code == 404


def test_activity_updates_last_activity_date(client, sample_client_id):
    before = client.get(f'/api/clients/{sample_client_id}').get_json()
    assert not before.get('last_activity_date')

    resp = client.post('/api/atividades', json={
        'client_id': sample_client_id,
        'contact_type': 'Ligação',
        'information': 'Conversa inicial sobre o projeto',
    })
    assert resp.status_code == 201

    after = client.get(f'/api/clients/{sample_client_id}').get_json()
    assert after.get('last_activity_date')

    resp = client.get('/api/atividades')
    assert resp.status_code == 200


def test_activity_requires_client(client):
    resp = client.post('/api/atividades', json={
        'client_id': 999999, 'information': 'cliente inexistente',
    })
    assert resp.status_code == 404
