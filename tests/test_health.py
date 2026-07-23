"""Teste do endpoint de liveness /healthz (usado por Docker/Nginx/LB)."""


def test_healthz_ok(client):
    resp = client.get('/healthz')
    assert resp.status_code == 200
    assert resp.get_json() == {'status': 'ok'}
