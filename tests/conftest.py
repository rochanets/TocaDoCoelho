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


@pytest.fixture(autouse=True)
def _drena_threads_de_indexacao_wikitoca(monkeypatch):
    """Dá join nas threads de indexação do WikiToca (daemon=True) antes do
    monkeypatch de DB_PATH/WIKI_UPLOAD_DIR ser revertido.

    Sem isto, uma thread de _wiki_index_documents_async ainda viva quando um
    teste falha (timeout do _espera_task, assert anterior, etc.) sobrevive ao
    teardown do fixture `db_path` e, no primeiro `get_db()` seguinte, grava em
    %APPDATA%\\toca-do-coelho\\toca-do-coelho.db — o banco real do usuário —
    usando ids do banco de teste que já sumiu. Mesma classe de bug que motivou
    o isolamento de diretórios em `_isola_diretorios_de_upload` acima.

    Recebe `monkeypatch` explicitamente (mesmo sem usá-lo) só para forçar a
    ordem de teardown: por depender dele, este fixture é finalizado antes do
    `monkeypatch.undo()` que reverte DB_PATH — não dá pra confiar só na ordem
    implícita entre fixtures autouse para uma garantia desta importância.
    """
    yield
    threads = getattr(toca, '_wiki_indexing_threads', [])
    for t in threads:
        if t.is_alive():
            t.join(timeout=5)


@pytest.fixture()
def sample_client_id(client):
    resp = client.post('/api/clientes', data={
        'name': 'Fulano de Teste',
        'company': 'Empresa Teste LTDA',
        'position': 'Gerente de TI',
    })
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()['id']
