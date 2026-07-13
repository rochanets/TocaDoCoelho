import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as toca  # noqa: E402


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    """Banco SQLite temporário e isolado, com o schema completo migrado."""
    path = tmp_path / 'test.db'
    monkeypatch.setattr(toca, 'DB_PATH', path)
    toca._run_schema_migrations()
    return path


@pytest.fixture()
def client(db_path):
    toca.app.config['TESTING'] = True
    with toca.app.test_client() as c:
        yield c


@pytest.fixture()
def sample_client_id(client):
    resp = client.post('/api/clientes', data={
        'name': 'Fulano de Teste',
        'company': 'Empresa Teste LTDA',
        'position': 'Gerente de TI',
    })
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()['id']
