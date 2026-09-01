# -*- coding: utf-8 -*-
"""Follow-up do WhatsApp Update no calendário do PRÓPRIO usuário (Graph/OAuth).

O compromisso do calendário interno já existia; o que se testa aqui é o segundo
destino (Microsoft 365) e, principalmente, que ele nunca sequestra a importação:
o Graph é rede, o CRM é banco local — falhar em um não pode desfazer o outro.
"""

import io
import json
import urllib.error
import urllib.request

import pytest

import app as toca
from integrations import outlook_graph


def _payload(client_id, content_hash='cal001', **extra):
    item = {
        'client_id': client_id,
        'client_name': 'Fulano de Teste',
        'summary': 'Cliente pediu retorno com a proposta revisada.',
        'content_hash': content_hash,
        'phone': '5511999999999',
        'period_days': 7,
        'message_count': 4,
        'last_message_ts': 1700000000,
        'followup_date': '2030-03-10',
        'followup_title': 'Retornar proposta revisada',
    }
    item.update(extra)
    return {'items': [item]}


@pytest.fixture()
def eventos_criados(monkeypatch):
    """Captura as chamadas ao Graph sem tocar a rede."""
    chamadas = []

    def _fake_token(user_id=1):
        return 'token-de-teste'

    def _fake_event(title, due_date, due_time=None, notes='', access_token=None, duration_minutes=30):
        chamadas.append({'title': title, 'date': due_date, 'time': due_time,
                         'notes': notes, 'token': access_token})
        return {'id': f'evt{len(chamadas)}', 'web_link': 'https://outlook.office.com/evt', 'subject': title}

    monkeypatch.setattr(toca, '_outlook_graph_access_token', _fake_token)
    monkeypatch.setattr(toca, '_outlook_create_followup_event', _fake_event)
    return chamadas


def test_followup_aceito_vai_para_o_calendario_do_usuario(client, sample_client_id, eventos_criados):
    resp = client.post('/api/whatsapp/approve',
                       json=_payload(sample_client_id, followup_to_outlook=True, followup_time='14:30'))
    data = resp.get_json()
    assert data['inserted'] == 1
    assert data['commitments'] == 1          # calendário interno
    assert data['calendar_events'] == 1      # calendário do usuário
    assert data['calendar_errors'] == []
    assert data['calendar_links'][0]['web_link'] == 'https://outlook.office.com/evt'

    assert len(eventos_criados) == 1
    assert eventos_criados[0]['date'] == '2030-03-10'
    assert eventos_criados[0]['time'] == '14:30'
    assert 'proposta revisada' in eventos_criados[0]['title']


def test_hora_combinada_tambem_entra_no_compromisso_interno(client, sample_client_id, eventos_criados):
    client.post('/api/whatsapp/approve',
                json=_payload(sample_client_id, followup_to_outlook=True, followup_time='09:15'))
    conn = toca.get_db()
    row = conn.execute('SELECT due_date, due_time FROM commitments WHERE client_id = ?',
                       (sample_client_id,)).fetchone()
    conn.close()
    assert row['due_date'] == '2030-03-10'
    assert row['due_time'] == '09:15'


def test_hora_invalida_e_ignorada_em_vez_de_gravada(client, sample_client_id, eventos_criados):
    client.post('/api/whatsapp/approve',
                json=_payload(sample_client_id, followup_to_outlook=True, followup_time='amanha de manha'))
    conn = toca.get_db()
    row = conn.execute('SELECT due_time FROM commitments WHERE client_id = ?',
                       (sample_client_id,)).fetchone()
    conn.close()
    assert row['due_time'] is None
    assert eventos_criados[0]['time'] == ''


def test_hora_fora_da_faixa_nao_e_aceita(client, sample_client_id, eventos_criados):
    """O horário pode vir do LLM, que alucina '25:00' — validar só o formato
    deixaria isso chegar ao banco e ao Graph."""
    client.post('/api/whatsapp/approve',
                json=_payload(sample_client_id, followup_to_outlook=True, followup_time='25:70'))
    conn = toca.get_db()
    row = conn.execute('SELECT due_time FROM commitments WHERE client_id = ?',
                       (sample_client_id,)).fetchone()
    conn.close()
    assert row['due_time'] is None
    assert eventos_criados[0]['time'] == ''


def test_sem_optar_pelo_outlook_nada_e_enviado_ao_graph(client, sample_client_id, eventos_criados):
    data = client.post('/api/whatsapp/approve', json=_payload(sample_client_id)).get_json()
    assert data['commitments'] == 1
    assert data['calendar_events'] == 0
    assert eventos_criados == []


def test_followup_desligado_nao_cria_evento_no_calendario_do_usuario(client, sample_client_id, eventos_criados):
    """O switch do calendário interno é o mestre: sem compromisso, sem evento."""
    data = client.post('/api/whatsapp/approve', json=_payload(
        sample_client_id, followup_enabled=False, followup_to_outlook=True)).get_json()
    assert data['commitments'] == 0
    assert data['calendar_events'] == 0
    assert eventos_criados == []


def test_falha_do_graph_nao_desfaz_a_importacao(client, sample_client_id, monkeypatch):
    def _boom(user_id=1):
        raise toca.OutlookReauthRequiredError('A autorização da conta Microsoft não é mais válida.')

    monkeypatch.setattr(toca, '_outlook_graph_access_token', _boom)
    data = client.post('/api/whatsapp/approve',
                       json=_payload(sample_client_id, followup_to_outlook=True)).get_json()
    assert data['ok'] is True
    assert data['inserted'] == 1            # atividade no CRM permanece
    assert data['commitments'] == 1         # compromisso interno permanece
    assert data['calendar_events'] == 0
    assert data['calendar_needs_reauth'] is True
    assert data['calendar_errors']


def test_permissao_de_calendario_ausente_interrompe_o_lote(client, sample_client_id, monkeypatch):
    """403 do Graph vale para todos os eventos — repetir só multiplicaria a recusa."""
    tentativas = []

    monkeypatch.setattr(toca, '_outlook_graph_access_token', lambda user_id=1: 'tok')

    def _sem_permissao(*args, **kwargs):
        tentativas.append(args)
        raise toca.OutlookCalendarPermissionError('Reconecte o Microsoft 365 para liberar o calendário.')

    monkeypatch.setattr(toca, '_outlook_create_followup_event', _sem_permissao)
    payload = _payload(sample_client_id, followup_to_outlook=True)
    payload['items'].append(dict(payload['items'][0], content_hash='cal002'))
    data = client.post('/api/whatsapp/approve', json=payload).get_json()
    assert data['inserted'] == 2
    assert data['calendar_events'] == 0
    assert data['calendar_needs_reauth'] is True
    assert len(tentativas) == 1


# -- Reenvio ao calendário (depois de reconectar a conta) ---------------------

def test_reenvio_cria_o_evento_sem_reinserir_atividade(client, sample_client_id, eventos_criados):
    """Depois do /approve o dedup por content_hash bloqueia a reimportação, então
    o reenvio precisa de rota própria — só o Graph, sem tocar o banco."""
    item = dict(_payload(sample_client_id, followup_to_outlook=True, followup_time='16:00')['items'][0])
    resp = client.post('/api/whatsapp/calendar-followups', json={'items': [item]})
    data = resp.get_json()
    assert data['ok'] is True
    assert data['requested'] == 1
    assert data['calendar_events'] == 1
    assert eventos_criados[0]['time'] == '16:00'

    conn = toca.get_db()
    atividades = conn.execute('SELECT COUNT(*) FROM activities WHERE client_id = ?',
                              (sample_client_id,)).fetchone()[0]
    compromissos = conn.execute('SELECT COUNT(*) FROM commitments WHERE client_id = ?',
                                (sample_client_id,)).fetchone()[0]
    conn.close()
    assert atividades == 0
    assert compromissos == 0


def test_reenvio_recusa_lista_sem_followup_para_o_calendario(client, sample_client_id, eventos_criados):
    resp = client.post('/api/whatsapp/calendar-followups',
                       json={'items': [_payload(sample_client_id)['items'][0]]})
    assert resp.status_code == 400
    assert eventos_criados == []


# -- Montagem do evento no Graph ---------------------------------------------

def _capture_urlopen(monkeypatch, payload=None):
    capturado = {}

    class _Resp:
        status = 201

        def read(self):
            return json.dumps(payload or {'id': 'AAA', 'webLink': 'https://outlook/evt'}).encode('utf-8')

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake(req, *args, **kwargs):
        capturado['url'] = req.full_url
        capturado['body'] = json.loads(req.data.decode('utf-8'))
        capturado['auth'] = req.get_header('Authorization')
        return _Resp()

    monkeypatch.setattr(urllib.request, 'urlopen', _fake)
    return capturado


def test_evento_com_hora_usa_janela_de_30_minutos(monkeypatch):
    capturado = _capture_urlopen(monkeypatch)
    evento = toca._outlook_create_followup_event('Ligar para o cliente', '2030-03-10', '14:30',
                                                 notes='contexto', access_token='tok')
    assert evento['web_link'] == 'https://outlook/evt'
    body = capturado['body']
    assert capturado['url'].endswith('/me/events')
    assert capturado['auth'] == 'Bearer tok'
    assert body['start']['dateTime'] == '2030-03-10T14:30:00'
    assert body['end']['dateTime'] == '2030-03-10T15:00:00'
    assert body['isAllDay'] is False
    assert body['isReminderOn'] is True
    assert body['start']['timeZone'] == outlook_graph.CALENDAR_DEFAULT_TIMEZONE


def test_evento_sem_hora_entra_como_dia_inteiro(monkeypatch):
    """Sem horário combinado na conversa, inventar um seria pior do que marcar o
    dia — o Graph exige início/fim à meia-noite e fim no dia seguinte."""
    capturado = _capture_urlopen(monkeypatch)
    toca._outlook_create_followup_event('Retorno combinado', '2030-03-10', '', access_token='tok')
    body = capturado['body']
    assert body['isAllDay'] is True
    assert body['start']['dateTime'] == '2030-03-10T00:00:00'
    assert body['end']['dateTime'] == '2030-03-11T00:00:00'
    assert body['isReminderOn'] is False


def test_graph_403_vira_erro_de_permissao_de_calendario(monkeypatch):
    def _boom(*_a, **_k):
        raise urllib.error.HTTPError(
            'https://graph.microsoft.com/v1.0/me/events', 403, 'Forbidden', {},
            io.BytesIO(json.dumps({'error': {'code': 'ErrorAccessDenied'}}).encode('utf-8')),
        )

    monkeypatch.setattr(urllib.request, 'urlopen', _boom)
    with pytest.raises(outlook_graph.OutlookCalendarPermissionError):
        outlook_graph.create_calendar_event('tok', 'Assunto', '2030-03-10T09:00:00', '2030-03-10T09:30:00')


def test_graph_401_pede_reconexao(monkeypatch):
    def _boom(*_a, **_k):
        raise urllib.error.HTTPError(
            'https://graph.microsoft.com/v1.0/me/events', 401, 'Unauthorized', {},
            io.BytesIO(b'{}'),
        )

    monkeypatch.setattr(urllib.request, 'urlopen', _boom)
    with pytest.raises(outlook_graph.OutlookReauthRequiredError):
        outlook_graph.create_calendar_event('tok', 'Assunto', '2030-03-10T09:00:00', '2030-03-10T09:30:00')


def test_escopo_do_calendario_entra_no_pedido_de_autorizacao():
    assert 'Calendars.ReadWrite' in toca._graph_make_settings(redirect_uri='http://localhost/cb')['scope']
    assert 'Calendars.ReadWrite' in outlook_graph._ALLOWED_SCOPES
