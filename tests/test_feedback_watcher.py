# -*- coding: utf-8 -*-
"""Watcher de feedback → Claude Code: Graph, lógica pura e orquestração."""
import base64
import subprocess
import types

import pytest

import app as toca
from integrations import outlook_graph as og


# ---------------------------------------------------------------------------
# Graph: leitura de não lidas e anexos
# ---------------------------------------------------------------------------

def test_fetch_unread_inbox_messages_mapeia_campos_e_pede_corpo_texto(monkeypatch):
    payload = {'value': [{
        'id': 'AAA==',
        'subject': '🐇 Feedback do Toca — X — v1',
        'receivedDateTime': '2026-08-11T10:00:00Z',
        'from': {'emailAddress': {'name': 'Fulano', 'address': 'Fulano@Empresa.com'}},
        'body': {'contentType': 'text', 'content': 'quebrou o botão'},
    }]}
    captured = {}

    def fake_get(url, headers=None):
        captured['url'] = url
        captured['headers'] = headers
        return payload

    monkeypatch.setattr(og, '_http_get_json', fake_get)
    msgs = og.fetch_unread_inbox_messages('tok')
    assert msgs == [{
        'id': 'AAA==',
        'subject': '🐇 Feedback do Toca — X — v1',
        'sender_email': 'fulano@empresa.com',
        'sender_name': 'Fulano',
        'received_at': '2026-08-11T10:00:00Z',
        'body_text': 'quebrou o botão',
    }]
    assert 'isRead+eq+false' in captured['url'] or 'isRead%20eq%20false' in captured['url']
    assert captured['headers']['Prefer'] == 'outlook.body-content-type="text"'


def test_fetch_message_attachments_filtra_somente_file_attachment(monkeypatch):
    payload = {'value': [
        {'@odata.type': '#microsoft.graph.fileAttachment', 'name': 'app-log.txt',
         'contentBytes': base64.b64encode(b'log').decode(), 'contentType': 'text/plain'},
        {'@odata.type': '#microsoft.graph.itemAttachment', 'name': 'email-anexado'},
    ]}
    monkeypatch.setattr(og, '_http_get_json', lambda url, headers=None: payload)
    atts = og.fetch_message_attachments('tok', 'MSG id/com=chars')
    assert len(atts) == 1
    assert atts[0] == {'name': 'app-log.txt',
                       'content_bytes': base64.b64encode(b'log').decode(),
                       'content_type': 'text/plain'}


def test_fetch_message_attachments_sem_id_devolve_vazio():
    assert og.fetch_message_attachments('tok', '') == []
