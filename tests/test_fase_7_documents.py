# -*- coding: utf-8 -*-
"""Fase 7.1: geração server-side dos PDFs core na imagem web."""

import builtins
from io import BytesIO

import pdfplumber

import app as toca


def _seed_owner_and_account():
    conn = toca.get_db()
    c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org F7 Docs')")
    org_id = c.lastrowid
    c.execute(
        """INSERT INTO users (org_id, email, full_name, role)
           VALUES (?, 'docs@empresa.test', 'Pessoa Docs', 'member')""",
        (org_id,),
    )
    user_id = c.lastrowid
    c.execute(
        """INSERT INTO accounts (name, sector, owner_id)
           VALUES ('Conta PDF F7', 'Tecnologia', ?)""",
        (user_id,),
    )
    account_id = c.lastrowid
    conn.commit()
    conn.close()
    return user_id, account_id


def _login(client, monkeypatch, user_id):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)
    with client.session_transaction() as session:
        session['user_id'] = user_id


def _narrative(_report_data):
    return {
        'executive_summary': 'Resumo executivo validado na Fase 7.',
        'highlights': ['PDF gerado no servidor'],
        'topic_breakdown': {},
        'next_steps': ['Revisar o relatório com a equipe'],
    }


def test_briefing_pdf_is_valid_and_extractable():
    pdf_bytes = toca._briefings_to_pdf(
        'Briefing Fase 7',
        [('Reunião', '## Contexto\n- Primeiro ponto\n- Segundo ponto')],
    )

    assert pdf_bytes.startswith(b'%PDF-')
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        assert len(pdf.pages) == 1
        text = pdf.pages[0].extract_text() or ''
    assert 'Briefing Fase 7' in text
    assert 'Primeiro ponto' in text


def test_relation_report_pdf_is_available_for_visible_account(client, monkeypatch):
    user_id, account_id = _seed_owner_and_account()
    _login(client, monkeypatch, user_id)
    monkeypatch.setattr(toca, '_relation_report_generate_narrative', _narrative)

    response = client.get(
        f'/api/report/relation?account_id={account_id}&full_period=true'
    )

    assert response.status_code == 200
    assert response.mimetype == 'application/pdf'
    assert response.data.startswith(b'%PDF-')
    with pdfplumber.open(BytesIO(response.data)) as pdf:
        text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
    assert 'Conta PDF F7' in text
    assert 'Resumo executivo validado na Fase 7' in text


def test_relation_report_has_controlled_degradation_without_reportlab(
    client, monkeypatch
):
    user_id, account_id = _seed_owner_and_account()
    _login(client, monkeypatch, user_id)
    monkeypatch.setattr(toca, '_relation_report_generate_narrative', _narrative)
    monkeypatch.setattr(toca, 'REPORTLAB_AVAILABLE', False)
    monkeypatch.setattr(toca, 'REPORTLAB_IMPORT_ERROR', None)
    original_import = builtins.__import__

    def import_without_reportlab(name, *args, **kwargs):
        if name == 'reportlab' or name.startswith('reportlab.'):
            raise ImportError('reportlab ausente no teste')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', import_without_reportlab)
    response = client.get(
        f'/api/report/relation?account_id={account_id}&full_period=true'
    )

    assert response.status_code == 503
    assert response.get_json() == {
        'error': 'Geração de PDF indisponível neste ambiente.',
        'code': 'PDF_GENERATION_UNAVAILABLE',
    }


def test_authenticated_web_multipart_has_configurable_size_limit(
    client, monkeypatch
):
    user_id, _ = _seed_owner_and_account()
    _login(client, monkeypatch, user_id)
    monkeypatch.setenv('TOCA_WEB_MAX_UPLOAD_BYTES', '64')

    response = client.post(
        '/api/autotoca/upload',
        data={'file': (BytesIO(b'x' * 128), 'arquivo.pdf')},
        content_type='multipart/form-data',
    )

    assert response.status_code == 413
    assert response.get_json() == {
        'error': 'Arquivo ou formulário excede o limite permitido.',
        'code': 'WEB_UPLOAD_TOO_LARGE',
        'max_bytes': 64,
    }


def test_desktop_mode_keeps_legacy_upload_behavior_without_web_limit(
    client, monkeypatch
):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    monkeypatch.setenv('TOCA_WEB_MAX_UPLOAD_BYTES', '1')

    response = client.post('/api/autotoca/upload')

    assert response.status_code == 400
    assert response.get_json()['error'] == 'Nenhum arquivo enviado.'
