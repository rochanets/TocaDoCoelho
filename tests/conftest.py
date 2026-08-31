import sys
import urllib.parse
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as toca  # noqa: E402


class _ChamadaDeLlmProibida(BaseException):
    """Levantada quando a suíte tenta uma chamada de rede real para SAI/
    OpenRouter sem mockar. Deriva de `BaseException`, não de `Exception`, de
    propósito: um `except Exception` genérico dentro do código de produção
    (ex.: o try/except do worker de indexação da Capacitação) captura
    `Exception` e tudo que dela deriva -- inclusive `AssertionError`, o que
    a primeira versão desta guarda usava. Com `AssertionError` um teste sem
    mock que exercitasse esse caminho terminava a TASK em 'error' (a guarda
    "funcionou", só que silenciosamente: virou um resultado de negócio
    comum, não uma falha da suíte) e o teste podia passar mesmo assim,
    escondendo que bateu na rede de verdade. `BaseException` atravessa esse
    `except Exception` e estoura a suíte de verdade."""


_MENSAGEM_LLM_PROIBIDO = (
    'Chamada real de LLM (SAI/OpenRouter) durante os testes. Mocke explicitamente a função de '
    "LLM que este teste exercita, por exemplo: monkeypatch.setattr(toca, '_llm_prompt', "
    "lambda *a, **k: 'resposta fake')"
)

# Hosts reais de SAI e OpenRouter -- usado para filtrar o bloqueio na camada
# de rede (requests.post / urllib.request.urlopen) por destino, não por
# função chamadora. Ver docstring de `_bloqueia_chamada_real_de_llm` abaixo
# para o motivo de precisar descer até este nível.
_HOSTS_DE_LLM = ('saiapplications.com', 'openrouter.ai')


def _e_host_de_llm(alvo):
    try:
        host = (urllib.parse.urlparse(str(alvo)).hostname or '').lower()
    except Exception:
        return False
    return any(host == h or host.endswith('.' + h) for h in _HOSTS_DE_LLM)


@pytest.fixture(autouse=True)
def _bloqueia_chamada_real_de_llm(monkeypatch):
    """Impede que a suíte chame o LLM de verdade pela rede.

    Este ambiente tem a integração SAI acessível — e com uma chave "Geral
    Claude" com fallback hardcoded no próprio `app.py` (assunto separado,
    não mexido aqui), ela responde mesmo com o banco de configurações vazio.
    Um teste da Task 7 que esquecera de mockar `_llm_prompt` chamou o
    provider real e passou — gastando cota do usuário e ficando dependente
    de rede e de resposta não determinística. O modo de falha é silencioso,
    que é o pior tipo: o teste fica verde e ninguém percebe.

    A primeira versão desta guarda só substituía `_llm_prompt` — o que deixa
    passar quem chama a rede por um caminho que não passa por ali:
    `_sai_simple_prompt` (13+ chamadores diretos em app.py) e
    `_openrouter_web_prompt` (app.py e routes/home.py) não são `_llm_prompt`,
    e `_campaign_llm_text` (app.py) faz sua própria chamada `urllib.request`
    pro OpenRouter sem passar por nenhum helper nomeado. Por isso o
    estrangulamento aqui é em duas camadas: (1) as funções nomeadas que
    fazem a chamada de fato (`_sai_execute_question_template`,
    `_openrouter_web_prompt`) e (2) a camada de rede crua
    (`requests.post`/`urllib.request.urlopen`), filtrada pelo HOST de
    destino — não bloqueia chamadas de rede para outros serviços (Outlook
    Graph, Tavily, etc.), só para SAI/OpenRouter.

    Qualquer teste que exercite um caminho de IA precisa mockar a função
    correspondente explicitamente (`monkeypatch.setattr(toca, '_llm_prompt',
    ...)` cobre a maioria dos casos, por chamar por baixo tudo que está
    guardado aqui), o que sobrescreve este bloqueio só para esse teste. Se
    este erro aparecer, é porque um caminho de IA ficou sem mock — o
    conserto é mockar no teste, nunca afrouxar esta guarda.
    """
    def _proibido(*args, **kwargs):
        raise _ChamadaDeLlmProibida(_MENSAGEM_LLM_PROIBIDO)

    monkeypatch.setattr(toca, '_llm_prompt', _proibido)
    monkeypatch.setattr(toca, '_sai_execute_question_template', _proibido)
    monkeypatch.setattr(toca, '_openrouter_web_prompt', _proibido)

    real_post = toca.requests.post

    def _post_guardado(url, *args, **kwargs):
        if _e_host_de_llm(url):
            _proibido()
        return real_post(url, *args, **kwargs)

    monkeypatch.setattr(toca.requests, 'post', _post_guardado)

    real_urlopen = toca.urllib.request.urlopen

    def _urlopen_guardado(req, *args, **kwargs):
        alvo = getattr(req, 'full_url', req)
        if _e_host_de_llm(alvo):
            _proibido()
        return real_urlopen(req, *args, **kwargs)

    monkeypatch.setattr(toca.urllib.request, 'urlopen', _urlopen_guardado)


@pytest.fixture(autouse=True)
def _isola_cache_do_tesseract(monkeypatch):
    """Isola o cache de `_itoca_find_tesseract_cmd` entre testes.

    O cache (ver app.py) só guarda resultado POSITIVO — nunca `None` — de
    propósito: cachear `None` deixaria o OCR morto em silêncio pelo resto do
    processo pra quem instala o Tesseract no meio de uma sessão longa (o app
    roda como desktop na bandeja por horas). Isso já elimina o risco de
    "envenenamento" entre testes que motivava limpar o cache antes desta
    correção (um positivo cacheado sempre reflete o ambiente real, nunca um
    falso-negativo preso). Ainda assim zeramos entre testes — sobretudo para
    os testes que exercitam o cache em si (ver test_wikitoca.py) — para que
    nenhum teste dependa da ordem de execução dos outros."""
    toca._itoca_reset_tesseract_cache()
    yield
    toca._itoca_reset_tesseract_cache()


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
