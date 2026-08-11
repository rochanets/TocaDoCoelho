"""Match de contas por nome de chat (WhatsApp Update) e domínio de email
(Sync Outlook), e registro de atividade direto na conta quando o contato
não está cadastrado no Toca."""
import sqlite3

import app as toca


def _conn(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _seed_accounts(db_path, *names):
    conn = _conn(db_path)
    for name in names:
        conn.execute('INSERT INTO accounts (name) VALUES (?)', (name,))
    conn.commit()
    index = toca._load_accounts_match_index(conn.cursor())
    conn.close()
    return index


# ── Normalização ────────────────────────────────────────────────────────────

def test_normalize_match_text_remove_acento_e_pontuacao():
    assert toca._normalize_match_text('  Grupo Boticário — S.A. ') == 'grupo boticario s a'
    assert toca._normalize_match_text(None) == ''


# ── Nome do chat/grupo (WhatsApp) ───────────────────────────────────────────

def test_chat_name_casa_nome_da_conta_como_palavra_inteira(db_path):
    index = _seed_accounts(db_path, 'Vale', 'Petrobras')
    hit = toca._match_account_by_chat_name('Projeto Vale x Stefanini', index)
    assert hit and hit['name'] == 'Vale'


def test_chat_name_nao_casa_substring_de_outra_palavra(db_path):
    index = _seed_accounts(db_path, 'Vale')
    assert toca._match_account_by_chat_name('Valentina Souza', index) is None


def test_chat_name_ignora_nomes_de_conta_muito_curtos(db_path):
    index = _seed_accounts(db_path, 'GM')
    assert toca._match_account_by_chat_name('Reunião GM amanhã', index) is None


def test_chat_name_empate_vence_o_nome_mais_especifico(db_path):
    index = _seed_accounts(db_path, 'Vale', 'Vale do Rio Doce')
    hit = toca._match_account_by_chat_name('Grupo Vale do Rio Doce - Projetos', index)
    assert hit and hit['name'] == 'Vale do Rio Doce'


# ── Domínio de email (Outlook) ──────────────────────────────────────────────

def test_dominio_igual_ao_nome_da_conta(db_path):
    index = _seed_accounts(db_path, 'Vale')
    hit = toca._match_account_by_email_domain('joao.silva@vale.com', index)
    assert hit and hit['name'] == 'Vale'


def test_dominio_contem_o_nome_da_conta(db_path):
    index = _seed_accounts(db_path, 'Boticário')
    hit = toca._match_account_by_email_domain('ana@grupoboticario.com.br', index)
    assert hit and hit['name'] == 'Boticário'


def test_provedor_de_email_pessoal_nunca_casa(db_path):
    index = _seed_accounts(db_path, 'Gmail Solutions', 'Vale')
    assert toca._match_account_by_email_domain('joao@gmail.com', index) is None
    assert toca._match_account_by_email_domain('maria@outlook.com', index) is None


def test_email_invalido_nao_casa(db_path):
    index = _seed_accounts(db_path, 'Vale')
    assert toca._match_account_by_email_domain('', index) is None
    assert toca._match_account_by_email_domain('sem-arroba', index) is None


# ── Aprovação do WhatsApp Update direto na conta ────────────────────────────

def _account_item(account_id, **overrides):
    item = {
        'account_id': account_id,
        'account_name': 'Vale',
        'chat_id': '5511999999999@c.us',
        'chat_name': 'Projeto Vale x Stefanini',
        'is_group': 1,
        'summary': 'Discutido cronograma da fase 2 e pendência de contrato.',
        'activity_date': '2026-08-10 15:00:00',
        'message_count': 12,
        'content_hash': 'abc123',
        'last_message_ts': 1780000000,
        'period_days': 7,
    }
    item.update(overrides)
    return item


def test_approve_registra_atividade_direto_na_conta(client, db_path):
    conn = _conn(db_path)
    conn.execute('INSERT INTO accounts (name) VALUES (?)', ('Vale',))
    account_id = conn.execute('SELECT id FROM accounts').fetchone()['id']
    conn.commit()
    conn.close()

    resp = client.post('/api/whatsapp/approve', json={'items': [_account_item(account_id)]})
    assert resp.status_code == 200
    assert resp.get_json()['inserted'] == 1

    conn = _conn(db_path)
    act = conn.execute('SELECT * FROM account_activities WHERE account_id = ?', (account_id,)).fetchone()
    assert act is not None
    assert 'não cadastrado no Toca' in act['description']
    assert 'Projeto Vale x Stefanini' in act['description']
    log = conn.execute('SELECT * FROM whatsapp_account_sync_log WHERE account_id = ?', (account_id,)).fetchone()
    assert log is not None and log['content_hash'] == 'abc123'
    assert log['activity_id'] == act['id']
    conn.close()

    # Reaprovar o mesmo conteúdo não duplica (dedupe por account_id+content_hash)
    resp2 = client.post('/api/whatsapp/approve', json={'items': [_account_item(account_id)]})
    assert resp2.get_json()['inserted'] == 0


def test_approve_item_de_contato_continua_funcionando(client, db_path):
    conn = _conn(db_path)
    conn.execute("INSERT INTO clients (name, company, position, phone) VALUES ('João', 'Vale', 'Gerente', '11999998888')")
    client_id = conn.execute('SELECT id FROM clients').fetchone()['id']
    conn.commit()
    conn.close()

    resp = client.post('/api/whatsapp/approve', json={'items': [{
        'client_id': client_id,
        'summary': 'Conversa sobre proposta.',
        'activity_date': '2026-08-10 10:00:00',
        'content_hash': 'hash-contato',
        'period_days': 7,
        'message_count': 3,
        'last_message_ts': 1780000001,
    }]})
    assert resp.status_code == 200
    assert resp.get_json()['inserted'] == 1


# ── Confirmação do Outlook direto na conta ──────────────────────────────────

def test_outlook_confirm_registra_atividade_na_conta(db_path, monkeypatch):
    monkeypatch.setattr(toca, '_outlook_call_llm', lambda prompt: None)
    conn = _conn(db_path)
    conn.execute('INSERT INTO accounts (name) VALUES (?)', ('Vale',))
    account_id = conn.execute('SELECT id FROM accounts').fetchone()['id']
    conn.commit()
    conn.close()

    toca._outlook_confirm_async('teste-task-conta', [{
        'account_id': account_id,
        'account_name': 'Vale',
        'subject': 'Proposta fase 2',
        'date': '2026-08-10T14:30:00Z',
        'counterpart_label': 'De',
        'counterpart_name': 'Carlos Pereira',
        'counterpart_email': 'carlos.pereira@vale.com',
        'body_preview': 'Segue a proposta revisada.',
        'messages': [],
        'message_ids': ['msg-1'],
        'conversation_id': 'conv-1',
    }])

    conn = _conn(db_path)
    act = conn.execute('SELECT * FROM account_activities WHERE account_id = ?', (account_id,)).fetchone()
    assert act is not None
    assert 'Carlos Pereira' in act['description']
    assert 'não cadastrado no Toca' in act['description']
    processed = conn.execute("SELECT * FROM outlook_processed_emails WHERE message_id = 'msg-1'").fetchone()
    assert processed is not None
    conn.close()


# ── Varredura de chats por conta (WAHA simulado) ────────────────────────────

class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.headers = {}
        self.text = ''

    def json(self):
        return self._payload


def _fake_waha(overview_payload, messages_payload, overview_status=200):
    def fake_get(url, **kwargs):
        if url.endswith('/chats/overview'):
            return _FakeResp(overview_status, overview_payload)
        return _FakeResp(200, messages_payload)
    return fake_get


def test_scan_account_chats_casa_grupo_e_ignora_contato_conhecido(db_path, monkeypatch):
    conn = _conn(db_path)
    conn.execute('INSERT INTO accounts (name) VALUES (?)', ('Vale',))
    conn.commit()
    c = conn.cursor()

    now_ts = 1780000500
    overview = [
        # grupo casado pelo nome da conta → deve entrar
        {'id': '123@g.us', 'user': '', 'name': 'Projeto Vale x Stefanini', 'isGroup': True, 'lastMessageTs': now_ts},
        # chat individual de contato JÁ cadastrado → excluído (coberto pelo loop principal)
        {'id': '5511999998888@c.us', 'user': '5511999998888', 'name': 'Vale Comercial', 'isGroup': False, 'lastMessageTs': now_ts},
        # nome sem relação com contas → ignorado
        {'id': '5511777776666@c.us', 'user': '5511777776666', 'name': 'Valentina Souza', 'isGroup': False, 'lastMessageTs': now_ts},
    ]
    messages = [
        {'id': {'id': 'a', 'fromMe': False}, 'body': 'Cronograma da fase 2 aprovado.', 'type': 'chat',
         'timestamp': now_ts - 100, 'fromMe': False},
    ]
    monkeypatch.setattr(toca.requests, 'get', _fake_waha(overview, messages))
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: None)
    monkeypatch.setattr(toca, '_bg_task_set', lambda *a, **k: None)

    clients = [(1, 'João', '11999998888')]
    counts = {}
    items = toca._whatsapp_scan_account_chats(
        c, 'http://waha', {}, 'default', clients, now_ts - 7 * 86400, now_ts,
        7, '1 semana', 'task-teste', '[teste]', counts
    )
    conn.close()

    assert len(items) == 1
    item = items[0]
    assert item['account_name'] == 'Vale'
    assert item['chat_id'] == '123@g.us'
    assert item['is_group'] == 1
    assert item['content_hash']
    assert 'Projeto Vale x Stefanini' in item['summary']  # fallback sem LLM


def test_scan_account_chats_degrada_sem_endpoint_no_gateway(db_path, monkeypatch):
    conn = _conn(db_path)
    conn.execute('INSERT INTO accounts (name) VALUES (?)', ('Vale',))
    conn.commit()
    c = conn.cursor()
    monkeypatch.setattr(toca.requests, 'get', _fake_waha(None, None, overview_status=404))
    monkeypatch.setattr(toca, '_bg_task_set', lambda *a, **k: None)

    counts = {}
    items = toca._whatsapp_scan_account_chats(
        c, 'http://waha', {}, 'default', [], 1000, 2000, 7, '1 semana',
        'task-teste', '[teste]', counts
    )
    conn.close()
    assert items == []
    assert counts.get('account_scan_unavailable') == 1


def test_migracao_cria_tabela_de_dedupe_por_conta(db_path):
    conn = _conn(db_path)
    tables = {r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert 'whatsapp_account_sync_log' in tables
