import io
import json
import logging
import sqlite3
import urllib.error
import urllib.parse
import urllib.request

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


# ── Classificação dos erros do token endpoint ────────────────────────────────
# O sintoma relatado ("continua pedindo autorização do administrador") aparecia
# no SYNC, não na autorização: o refresh token guardado tinha sido emitido antes
# de Mail.Send/User.Read entrarem no escopo, o Azure respondia AADSTS65001 e o
# app repetia a mensagem de "peça ao administrador" para sempre — sem descartar
# o grant morto nem oferecer caminho de volta. Remover prompt=consent não podia
# consertar isso.

_TOKEN_URL = 'https://login.microsoftonline.com/contoso.onmicrosoft.com/oauth2/v2.0/token'


def _raise_http_error(payload, code=400):
    def _boom(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            _TOKEN_URL, code, 'Bad Request', {},
            io.BytesIO(json.dumps(payload).encode('utf-8')),
        )
    return _boom


def _seed_token(conn, refresh_token='refresh-antigo', expires_in=-60):
    outlook_graph._upsert_tokens(conn, 1, {
        'access_token': 'access-velho',
        'refresh_token': refresh_token,
        'scope': 'offline_access Mail.Read',
        'token_type': 'Bearer',
        'expires_in': expires_in,
    })


_CONSENT_BODY = {
    'error': 'invalid_grant',
    'error_description': "AADSTS65001: The user or administrator has not consented to use the application.",
    'correlation_id': 'aaaa-bbbb',
    'trace_id': 'cccc-dddd',
}


def test_falta_de_consentimento_vira_erro_especifico(conn, monkeypatch):
    monkeypatch.setattr(urllib.request, 'urlopen', _raise_http_error(_CONSENT_BODY))
    with pytest.raises(outlook_graph.OutlookConsentRequiredError):
        outlook_graph._http_form_post(_TOKEN_URL, {'grant_type': 'refresh_token'})


def test_mfa_nao_e_classificado_como_falta_de_consentimento(conn, monkeypatch):
    """A checagem antiga (`'consent' in err.lower()`) era ampla demais e mandava
    erros de MFA/sessão para o fluxo de consentimento forçado."""
    monkeypatch.setattr(urllib.request, 'urlopen', _raise_http_error({
        'error': 'interaction_required',
        'error_description': 'AADSTS50076: Due to a configuration change, you must use multi-factor authentication.',
    }))
    with pytest.raises(outlook_graph.OutlookReauthRequiredError) as exc:
        outlook_graph._http_form_post(_TOKEN_URL, {'grant_type': 'refresh_token'})
    assert not isinstance(exc.value, outlook_graph.OutlookConsentRequiredError)


def test_erro_bruto_do_azure_vai_para_o_log(conn, monkeypatch, caplog):
    """O branch de consentimento levantava a exceção ANTES do logger.error, então
    o código AADSTS e o correlation_id nunca chegavam ao app.log — era por isso
    que não se conseguia confirmar nem refutar se a correção tinha efeito."""
    monkeypatch.setattr(urllib.request, 'urlopen', _raise_http_error(_CONSENT_BODY))
    with caplog.at_level(logging.ERROR, logger='toca-do-coelho.outlook-graph'):
        with pytest.raises(outlook_graph.OutlookConsentRequiredError):
            outlook_graph._http_form_post(_TOKEN_URL, {'grant_type': 'refresh_token'})
    registro = '\n'.join(r.getMessage() for r in caplog.records)
    assert 'AADSTS65001' in registro
    assert 'aaaa-bbbb' in registro


# ── Invalidação do grant morto ───────────────────────────────────────────────

def test_refresh_com_consentimento_faltando_descarta_o_grant(conn, monkeypatch):
    _seed_token(conn)
    assert outlook_graph.get_integration_state(conn, 1)['connected'] is True

    monkeypatch.setattr(urllib.request, 'urlopen', _raise_http_error(_CONSENT_BODY))
    with pytest.raises(outlook_graph.OutlookConsentRequiredError):
        outlook_graph.get_valid_access_token(conn, 1, settings=_SETTINGS)

    estado = outlook_graph.get_integration_state(conn, 1)
    assert estado['connected'] is False
    assert estado['needs_reauth'] is True
    assert estado['needs_consent'] is True


def test_refresh_revogado_pede_reconexao_sem_forcar_consentimento(conn, monkeypatch):
    _seed_token(conn)
    monkeypatch.setattr(urllib.request, 'urlopen', _raise_http_error({
        'error': 'invalid_grant',
        'error_description': 'AADSTS700082: The refresh token has expired due to inactivity.',
    }))
    with pytest.raises(outlook_graph.OutlookReauthRequiredError):
        outlook_graph.get_valid_access_token(conn, 1, settings=_SETTINGS)

    estado = outlook_graph.get_integration_state(conn, 1)
    assert estado['connected'] is False
    assert estado['needs_reauth'] is True
    assert estado['needs_consent'] is False


def test_grant_invalidado_repete_o_motivo_original(conn, monkeypatch):
    """Depois de invalidado não há mais refresh token, mas o motivo (e o fato de
    exigir consentimento) precisa sobreviver para a UI escolher o botão certo."""
    _seed_token(conn)
    monkeypatch.setattr(urllib.request, 'urlopen', _raise_http_error(_CONSENT_BODY))
    with pytest.raises(outlook_graph.OutlookConsentRequiredError):
        outlook_graph.get_valid_access_token(conn, 1, settings=_SETTINGS)

    # Segunda tentativa: nem chega à rede, e ainda assim classifica certo.
    monkeypatch.setattr(urllib.request, 'urlopen', _raise_http_error({'error': 'nao_deveria_ser_chamado'}))
    with pytest.raises(outlook_graph.OutlookConsentRequiredError):
        outlook_graph.get_valid_access_token(conn, 1, settings=_SETTINGS)


def test_reconexao_bem_sucedida_limpa_a_marca_de_invalido(conn, monkeypatch):
    _seed_token(conn)
    monkeypatch.setattr(urllib.request, 'urlopen', _raise_http_error(_CONSENT_BODY))
    with pytest.raises(outlook_graph.OutlookConsentRequiredError):
        outlook_graph.get_valid_access_token(conn, 1, settings=_SETTINGS)
    assert outlook_graph.get_integration_state(conn, 1)['connected'] is False

    outlook_graph._upsert_tokens(conn, 1, {
        'access_token': 'access-novo',
        'refresh_token': 'refresh-novo',
        'scope': _SETTINGS['scope'],
        'token_type': 'Bearer',
        'expires_in': 3600,
    })
    estado = outlook_graph.get_integration_state(conn, 1)
    assert estado['connected'] is True
    assert estado['needs_reauth'] is False


def test_estado_sem_integracao_nao_e_conectado(conn):
    estado = outlook_graph.get_integration_state(conn, 1)
    assert estado == {'connected': False, 'needs_reauth': False, 'needs_consent': False, 'reason': ''}


# ── Contrato do endpoint /api/outlook/graph-status ───────────────────────────

def _grava_grant(expires_in=3600):
    import app as toca
    conn = toca.get_db()
    try:
        outlook_graph.ensure_schema(conn)
        _seed_token(conn, expires_in=expires_in)
        conn.commit()
    finally:
        conn.close()


def test_graph_status_falha_de_rede_nao_desconecta(client, monkeypatch):
    _grava_grant()
    monkeypatch.setattr(urllib.request, 'urlopen', _raise_http_error({'error': 'offline'}, code=503))
    data = client.get('/api/outlook/graph-status').get_json()
    assert data['connected'] is True


def test_graph_status_reporta_grant_invalido_e_pede_consentimento(client):
    """Antes bastava a linha existir em user_integrations para responder
    connected: true — a UI ficava presa em "conectado", escondia o botão
    Conectar e o usuário não tinha como refazer a autorização."""
    _grava_grant()
    assert client.get('/api/outlook/graph-status').get_json()['connected'] is True

    import app as toca
    conn = toca.get_db()
    try:
        outlook_graph._invalidate_integration(conn, 1, 'Consentimento faltando no Azure.', needs_consent=True)
    finally:
        conn.close()

    data = client.get('/api/outlook/graph-status').get_json()
    assert data['connected'] is False
    assert data['needs_reauth'] is True
    assert data['needs_consent'] is True
    assert 'Consentimento faltando' in data['error']


def test_oauth_start_so_manda_prompt_consent_quando_pedido(client):
    sem = client.get('/api/outlook/oauth/start').get_json()['auth_url']
    com = client.get('/api/outlook/oauth/start?force_consent=1').get_json()['auth_url']
    assert 'prompt' not in urllib.parse.parse_qs(urllib.parse.urlparse(sem).query)
    assert urllib.parse.parse_qs(urllib.parse.urlparse(com).query)['prompt'] == ['consent']


def test_callback_com_erro_do_azure_vai_para_a_tela_com_o_botao(client):
    """O redirect antigo (/?graph_error=) caía na janela principal, que só mostra
    um alerta — sem nenhum caminho para tentar de novo pedindo consentimento."""
    resp = client.get('/api/outlook/oauth/callback?error=consent_required&error_description=AADSTS65001')
    assert resp.status_code == 302
    destino = urllib.parse.urlparse(resp.headers['Location'])
    assert destino.path == '/outlook-connected.html'
    assert urllib.parse.parse_qs(destino.query)['needs_consent'] == ['1']


# ── Consentimento de administrador ───────────────────────────────────────────
# O beco sem saída real (visto no app.log de 07/08/2026): o tenant bloqueia o
# consentimento de usuário, o Azure mostra "Precisa de aprovação de
# administrador" e NUNCA redireciona de volta — nenhum callback chega e nem o
# botão "pedindo consentimento" resolve (cai na mesma tela). A única saída é o
# consentimento de administrador para o tenant, e o mecanismo padrão do Azure
# para isso é o endpoint /v2.0/adminconsent — que o app precisa saber montar e
# cujo retorno o callback precisa reconhecer.

def test_admin_consent_url_usa_o_endpoint_v2_com_escopos_qualificados():
    url = outlook_graph.build_admin_consent_url(settings=_SETTINGS)
    parsed = urllib.parse.urlparse(url)
    assert parsed.hostname == 'login.microsoftonline.com'
    assert parsed.path == '/contoso.onmicrosoft.com/v2.0/adminconsent'
    params = _query(url)
    assert params['client_id'] == [_SETTINGS['client_id']]
    assert params['redirect_uri'] == [_SETTINGS['redirect_uri']]
    scopes = params['scope'][0].split()
    # Escopos da Graph precisam do recurso qualificado no adminconsent v2;
    # escopos OIDC (offline_access etc.) ficam sem prefixo.
    assert 'https://graph.microsoft.com/Mail.Read' in scopes
    assert 'https://graph.microsoft.com/Mail.Send' in scopes
    assert 'https://graph.microsoft.com/User.Read' in scopes
    assert 'offline_access' in scopes


def test_endpoint_devolve_o_link_de_admin_consent(client):
    data = client.get('/api/outlook/oauth/admin-consent-url').get_json()
    assert '/v2.0/adminconsent' in data['admin_consent_url']


def test_callback_de_admin_consent_bem_sucedido_nao_e_tratado_como_erro(client):
    """O retorno do adminconsent não traz code/state — sem tratamento próprio,
    o admin que acabou de aprovar caía em 'Parâmetros OAuth incompletos'."""
    resp = client.get('/api/outlook/oauth/callback?admin_consent=True&tenant=contoso.onmicrosoft.com')
    assert resp.status_code == 302
    destino = urllib.parse.urlparse(resp.headers['Location'])
    assert destino.path == '/outlook-connected.html'
    q = urllib.parse.parse_qs(destino.query)
    assert q.get('admin_consent') == ['1']
    assert 'error' not in q


def test_callback_de_admin_consent_recusado_segue_no_fluxo_de_erro(client):
    resp = client.get('/api/outlook/oauth/callback?admin_consent=False&error=access_denied&error_description=recusado')
    destino = urllib.parse.urlparse(resp.headers['Location'])
    q = urllib.parse.parse_qs(destino.query)
    assert 'error' in q
    assert q.get('admin_consent') != ['1']

# ── Escopo novo sem consentimento não pode derrubar o e-mail ─────────────────
# Cenário real: o tenant consentiu Mail.*/User.Read meses atrás; Calendars.ReadWrite
# entrou depois. Sem o fallback, o primeiro refresh pedindo o escopo novo recebe
# AADSTS65001, o app invalida o grant inteiro e o usuário perde sync de e-mail,
# briefing e envios — por causa de uma permissão de calendário que ele nem usou.

_SETTINGS_COM_CALENDARIO = dict(_SETTINGS, scope='offline_access Mail.Read Mail.Send Calendars.ReadWrite')


def _token_endpoint_por_escopo(monkeypatch, escopos_consentidos):
    """Simula o Azure no nível do HTTP (a classificação AADSTS fica no
    _http_form_post real): recusa se pedirem escopo não consentido."""
    pedidos = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            return json.dumps(self._payload).encode('utf-8')

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, *args, **kwargs):
        form = urllib.parse.parse_qs((req.data or b'').decode('utf-8'))
        scope = (form.get('scope') or [''])[0]
        pedidos.append(scope)
        if set(scope.split()) - set(escopos_consentidos):
            raise urllib.error.HTTPError(
                _TOKEN_URL, 400, 'Bad Request', {},
                io.BytesIO(json.dumps(_CONSENT_BODY).encode('utf-8')),
            )
        return _Resp({'access_token': 'access-novo', 'refresh_token': 'refresh-novo',
                      'scope': scope, 'token_type': 'Bearer', 'expires_in': 3600})

    monkeypatch.setattr(urllib.request, 'urlopen', _fake_urlopen)
    return pedidos


def test_calendario_sem_consentimento_nao_derruba_o_email(conn, monkeypatch):
    consentidos = ['offline_access', 'Mail.Read', 'Mail.Send']
    pedidos = _token_endpoint_por_escopo(monkeypatch, consentidos)
    _seed_token(conn)

    token = outlook_graph.get_valid_access_token(conn, 1, settings=_SETTINGS_COM_CALENDARIO)

    assert token == 'access-novo'                      # e-mail continua funcionando
    assert 'Calendars.ReadWrite' in pedidos[0]         # tentou o escopo completo
    assert 'Calendars.ReadWrite' not in pedidos[1]     # e caiu para o reduzido
    estado = outlook_graph.get_integration_state(conn, 1)
    assert estado['connected'] is True
    assert estado['calendar_authorized'] is False      # UI não promete o calendário


def test_calendario_consentido_mantem_o_escopo_completo(conn, monkeypatch):
    pedidos = _token_endpoint_por_escopo(
        monkeypatch, ['offline_access', 'Mail.Read', 'Mail.Send', 'Calendars.ReadWrite'])
    _seed_token(conn)

    outlook_graph.get_valid_access_token(conn, 1, settings=_SETTINGS_COM_CALENDARIO)

    assert len(pedidos) == 1                           # sem fallback desnecessário
    assert outlook_graph.get_integration_state(conn, 1)['calendar_authorized'] is True


def test_falta_de_consentimento_no_nucleo_ainda_invalida_o_grant(conn, monkeypatch):
    """Se nem Mail.Read passa, não há o que degradar — o grant morreu de verdade
    e precisa voltar para a reconexão, como antes."""
    _token_endpoint_por_escopo(monkeypatch, ['offline_access'])
    _seed_token(conn)

    with pytest.raises(outlook_graph.OutlookConsentRequiredError):
        outlook_graph.get_valid_access_token(conn, 1, settings=_SETTINGS_COM_CALENDARIO)

    estado = outlook_graph.get_integration_state(conn, 1)
    assert estado['connected'] is False
    assert estado['needs_consent'] is True


def test_refresh_token_revogado_nao_tenta_escopo_reduzido(conn, monkeypatch):
    """invalid_grant sem AADSTS de consentimento = token morto: insistir com
    escopo menor só gastaria uma chamada."""
    pedidos = []

    def _fake_urlopen(req, *args, **kwargs):
        form = urllib.parse.parse_qs((req.data or b'').decode('utf-8'))
        pedidos.append((form.get('scope') or [''])[0])
        raise urllib.error.HTTPError(
            _TOKEN_URL, 400, 'Bad Request', {},
            io.BytesIO(json.dumps({'error': 'invalid_grant',
                                   'error_description': 'AADSTS50173: token revogado.'}).encode('utf-8')),
        )

    monkeypatch.setattr(urllib.request, 'urlopen', _fake_urlopen)
    _seed_token(conn)

    with pytest.raises(outlook_graph.OutlookReauthRequiredError):
        outlook_graph.get_valid_access_token(conn, 1, settings=_SETTINGS_COM_CALENDARIO)
    assert len(pedidos) == 1
