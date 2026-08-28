import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as toca  # noqa: E402


@pytest.fixture(autouse=True)
def _isola_diretorios_de_upload(tmp_path, monkeypatch):
    """Mantém os uploads dos testes fora do diretório de dados real do usuário.

    Sem isto, os testes gravavam em %APPDATA%\\toca-do-coelho\\uploads: os arquivos
    se acumulavam a cada execução e o dedup ia somando sufixos ('nota_1_2_3...'),
    até o nome estourar o limite de caminho do Windows e a suíte falhar sozinha.
    """
    for nome in ('UPLOAD_DIR', 'AUTOTOCA_UPLOAD_DIR', 'REEMBOLSOS_UPLOAD_DIR',
                 'ACCOUNT_UPLOAD_DIR', 'WIKI_UPLOAD_DIR', 'WIKI_TRAINING_UPLOAD_DIR'):
        if hasattr(toca, nome):
            destino = tmp_path / 'uploads' / nome.lower()
            destino.mkdir(parents=True, exist_ok=True)
            monkeypatch.setattr(toca, nome, destino)


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
