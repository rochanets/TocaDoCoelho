import sqlite3
import urllib.parse

import pytest

from integrations import outlook_graph


_SETTINGS = {
    'tenant': 'contoso.onmicrosoft.com',
    'client_id': '11111111-2222-3333-4444-555555555555',
    'redirect_uri': 'http://localhost:5000/api/outlook/oauth/callback',
    'scope': 'offline_access Mail.Read Mail.Send User.Read',
}


@pytest.fixture()
def conn():
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    outlook_graph.ensure_schema(c)
    c.commit()
    try:
        yield c
    finally:
        c.close()


def _query(url):
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)


def test_authorize_url_nao_forca_consentimento_por_padrao(conn):
    """prompt=consent pede um consentimento NOVO do usuário e ignora o
    consentimento de administrador já concedido no tenant. Em tenants onde o
    consentimento de usuário está bloqueado (o caso corporativo comum), isso
    joga o usuário na tela 'Aprovação necessária' para sempre, mesmo com as
    permissões já liberadas pelo admin."""
    params = _query(outlook_graph.build_authorize_url(conn, 1, settings=_SETTINGS))
    assert 'prompt' not in params


def test_authorize_url_forca_consentimento_quando_pedido(conn):
    params = _query(outlook_graph.build_authorize_url(conn, 1, settings=_SETTINGS, force_consent=True))
    assert params.get('prompt') == ['consent']


def test_authorize_url_mantem_pkce_e_state(conn):
    params = _query(outlook_graph.build_authorize_url(conn, 1, settings=_SETTINGS))
    assert params['code_challenge_method'] == ['S256']
    assert params['client_id'] == [_SETTINGS['client_id']]
    state = params['state'][0]
    user_id, verifier = outlook_graph.consume_oauth_state(conn, state)
    assert user_id == 1
    assert outlook_graph._pkce_make_challenge(verifier) == params['code_challenge'][0]
