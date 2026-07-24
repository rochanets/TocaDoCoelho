# -*- coding: utf-8 -*-
# Rotas do domínio "outlook" (Bloco 3 — modularização).
# Este arquivo é executado no namespace de app.py por _load_route_modules():
# tem acesso a todos os helpers/globals de app.py e registra as rotas no
# mesmo objeto Flask `app`, com URLs idênticas às originais.

@app.route('/api/outlook/diagnose', methods=['GET'])
def outlook_diagnose():
    """Retorna diagnóstico de configuração e conectividade para o sync do Outlook."""
    checks = []

    is_win = sys.platform == 'win32'
    checks.append({
        'label': 'Windows (COM)',
        'ok': is_win,
        'detail': 'ok' if is_win else 'Não é Windows — conector COM indisponível'
    })

    has_graph_creds = bool(
        _resolve_setting('outlook_graph_client_id', 'OUTLOOK_GRAPH_CLIENT_ID')
    )
    checks.append({
        'label': 'Graph API (credenciais)',
        'ok': has_graph_creds,
        'detail': 'Client ID e Secret configurados' if has_graph_creds else 'Configure Tenant ID / Client ID / Client Secret nas Configurações'
    })

    has_graph_token = False
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT 1 FROM user_integrations WHERE provider = 'outlook_graph' LIMIT 1")
        has_graph_token = c.fetchone() is not None
        conn.close()
    except Exception as e:
        logger.debug(f'[outlook_diagnose] exceção ignorada: {e}')
    checks.append({
        'label': 'OAuth Graph autenticado',
        'ok': has_graph_token,
        'detail': 'Token OAuth ativo' if has_graph_token else 'Não autenticado — use "Conectar Outlook via Graph"'
    })

    total_clients = 0
    clients_with_email = 0
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM clients')
        total_clients = (c.fetchone() or [0])[0]
        c.execute("SELECT COUNT(*) FROM clients WHERE email IS NOT NULL AND TRIM(email) != ''")
        clients_with_email = (c.fetchone() or [0])[0]
        conn.close()
    except Exception as e:
        logger.debug(f'[outlook_diagnose] exceção ignorada: {e}')
    email_pct = int(clients_with_email / total_clients * 100) if total_clients else 0
    checks.append({
        'label': 'Clientes com email',
        'ok': clients_with_email > 0,
        'detail': f'{clients_with_email}/{total_clients} ({email_pct}%) — emails são usados para match com remetentes'
    })

    has_sai = bool(_resolve_setting('itoca_sai_api_key', 'ITOCA_SAI_API_KEY'))
    has_or = bool(_resolve_setting('openrouter_api_key', 'OPENROUTER_API_KEY'))
    has_llm = has_sai or has_or
    llm_detail = (('SAI' if has_sai else '') + (' + ' if has_sai and has_or else '') + ('OpenRouter' if has_or else '')) if has_llm else 'Nenhum LLM configurado — resumos desativados'
    checks.append({'label': 'LLM (resumos)', 'ok': has_llm, 'detail': llm_detail})

    can_sync = is_win or has_graph_token
    connector = 'graph' if has_graph_token else ('com' if is_win else 'none')

    return jsonify({
        'can_sync': can_sync,
        'connector': connector,
        'clients_with_email': clients_with_email,
        'total_clients': total_clients,
        'checks': checks
    })


@app.route('/api/outlook/sync', methods=['POST'])
def sync_outlook_emails():
    """Lê o Outlook via PowerShell e importa os emails como atividades."""
    if sys.platform != 'win32':
        return jsonify({'error': 'Sincronização com Outlook disponível somente no Windows.'}), 400
    try:
        data = request.get_json() or {}
        days = max(1, min(int(data.get('days', 60)), 365))
        emails = _outlook_fetch_via_powershell(days)
        if not emails:
            return jsonify({
                'imported': 0, 'skipped_duplicates': 0, 'skipped_no_match': 0,
                'total_read': 0,
                'message': f'Nenhum email encontrado nos últimos {days} dias.'
            })
        conn = get_db()
        imported, skipped_duplicates, skipped_no_match = _outlook_import_emails(emails, conn)
        conn.close()
        msg = f'{imported} atividade(s) importada(s)'
        if skipped_duplicates:
            msg += f', {skipped_duplicates} duplicata(s) ignorada(s)'
        msg += f'. ({len(emails)} emails lidos do Outlook)'
        return jsonify({
            'imported': imported,
            'skipped_duplicates': skipped_duplicates,
            'skipped_no_match': skipped_no_match,
            'total_read': len(emails),
            'message': msg
        })
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/outlook/sync: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/outlook/sync-stream', methods=['GET'])
def sync_outlook_stream():
    """SSE: roteia para COM legado ou Graph de acordo com OUTLOOK_CONNECTOR_MODE."""
    mode = (os.environ.get('OUTLOOK_CONNECTOR_MODE') or 'auto').strip().lower()
    if mode not in {'com', 'graph', 'auto'}:
        mode = 'auto'

    # comportamento legado explícito
    if mode == 'com':
        return _outlook_sync_stream_com()

    # Graph explícito
    if mode == 'graph':
        return _outlook_sync_stream_graph()

    # auto: prioriza Graph se houver integração conectada; fallback para COM em Windows
    user_id = max(1, int(request.args.get('user_id', 1)))
    has_graph_integration = False
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT 1 FROM user_integrations WHERE user_id = ? AND provider = 'outlook_graph' LIMIT 1",
            (user_id,)
        )
        has_graph_integration = c.fetchone() is not None
        conn.close()
    except Exception:
        has_graph_integration = False

    if has_graph_integration:
        return _outlook_sync_stream_graph()
    return _outlook_sync_stream_com()


@app.route('/api/outlook/sync-stream-graph', methods=['GET'])
def sync_outlook_stream_graph():
    """SSE dedicado do conector Graph (OAuth + Graph API)."""
    return _outlook_sync_stream_graph()


@app.route('/api/outlook/oauth/start', methods=['GET'])
def outlook_oauth_start():
    try:
        user_id = max(1, int(request.args.get('user_id', 1)))
        settings = _graph_make_settings(redirect_uri=_graph_redirect_uri())
        conn = get_db()
        try:
            auth_url = outlook_graph_build_authorize_url(conn=conn, user_id=user_id, settings=settings)
        finally:
            conn.close()
        return jsonify({'auth_url': auth_url, 'provider': 'outlook_graph', 'user_id': user_id})
    except OutlookOAuthError as e:
        logger.error(f'[Outlook][OAuth] Falha ao iniciar OAuth: {e}')
        return jsonify({'error': str(e), 'error_type': 'oauth_authentication'}), 400
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/outlook/oauth/start: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/outlook/oauth/callback', methods=['GET'])
def outlook_oauth_callback():
    try:
        error = (request.args.get('error') or '').strip()
        if error:
            desc = request.args.get('error_description') or error
            return redirect(f'/?graph_error={urllib.parse.quote(str(desc))}', 302)

        code = (request.args.get('code') or '').strip()
        state = (request.args.get('state') or '').strip()
        if not code or not state:
            return redirect('/outlook-connected.html?error=Par%C3%A2metros+OAuth+incompletos', 302)

        conn = get_db()
        try:
            user_id, verifier = outlook_graph_consume_oauth_state(conn, state)
            settings = _graph_make_settings(redirect_uri=_graph_redirect_uri())
            outlook_graph_exchange_code_and_store(
                conn=conn, code=code, user_id=user_id, verifier=verifier, settings=settings
            )
        finally:
            conn.close()
        return redirect('/outlook-connected.html', 302)
    except OutlookOAuthError as e:
        logger.error(f'[Outlook][OAuth] Falha na callback OAuth: {e}')
        return redirect(f'/outlook-connected.html?error={urllib.parse.quote(str(e))}', 302)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/outlook/oauth/callback: {e}')
        return redirect(f'/outlook-connected.html?error={urllib.parse.quote(str(e))}', 302)


@app.route('/api/outlook/graph-config', methods=['GET', 'POST'])
def outlook_graph_config():
    """Lê ou salva credenciais do Microsoft Graph nas configurações do app."""
    if request.method == 'GET':
        tenant = _resolve_setting('outlook_graph_tenant_id', 'OUTLOOK_GRAPH_TENANT_ID') or _GRAPH_DEFAULT_TENANT
        client_id = _resolve_setting('outlook_graph_client_id', 'OUTLOOK_GRAPH_CLIENT_ID') or _GRAPH_DEFAULT_CLIENT_ID
        return jsonify({
            'tenant_id': tenant,
            'client_id': client_id,
            'configured': bool(tenant and client_id),
        })
    data = request.get_json() or {}
    tenant = (data.get('tenant_id') or '').strip()
    client_id = (data.get('client_id') or '').strip()
    conn = get_db()
    c = conn.cursor()
    for key, value in [('outlook_graph_tenant_id', tenant), ('outlook_graph_client_id', client_id)]:
        c.execute('INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP', (key, value))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/outlook/graph-status', methods=['GET'])
def outlook_graph_status_endpoint():
    """Retorna se o usuário está conectado ao Microsoft Graph e com qual email."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT expires_at FROM user_integrations WHERE provider = 'outlook_graph' AND user_id = 1 LIMIT 1")
        row = c.fetchone()
        conn.close()
        if not row:
            return jsonify({'connected': False})
        email = None
        try:
            settings = _graph_make_settings(redirect_uri=_graph_redirect_uri())
            conn2 = get_db()
            token = outlook_graph_get_valid_access_token(conn=conn2, user_id=1, settings=settings)
            conn2.close()
            req = urllib.request.Request('https://graph.microsoft.com/v1.0/me?$select=mail,userPrincipalName', method='GET')
            req.add_header('Authorization', f'Bearer {token}')
            req.add_header('Accept', 'application/json')
            with urllib.request.urlopen(req, timeout=10) as resp:
                me = json.loads(resp.read())
                email = me.get('mail') or me.get('userPrincipalName')
        except Exception as e:
            logger.debug(f'[outlook_graph_status_endpoint] exceção ignorada: {e}')
        return jsonify({'connected': True, 'email': email, 'expires_at': row['expires_at']})
    except Exception as e:
        return jsonify({'connected': False, 'error': str(e)})


@app.route('/api/outlook/graph-disconnect', methods=['DELETE'])
def outlook_graph_disconnect():
    """Remove tokens do Microsoft Graph para o usuário."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM user_integrations WHERE provider = 'outlook_graph'")
        conn.commit()
        conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/outlook/confirm-import', methods=['POST'])
def confirm_import_outlook():
    """Inicia importação assíncrona das atividades confirmadas, retorna task_id para polling."""
    try:
        data = request.get_json() or {}
        activities = data.get('activities', [])
        if not activities:
            return jsonify({'imported': 0, 'message': 'Nenhuma atividade para importar.'})

        task_id = uuid.uuid4().hex
        _outlook_confirm_task_set(task_id, {'status': 'processing', 'step': 'Iniciando...', 'progress': 5})
        threading.Thread(target=_outlook_confirm_async, args=(task_id, activities), daemon=True).start()
        return jsonify({'task_id': task_id}), 202
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/outlook/confirm-import: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/outlook/confirm-tasks/<task_id>', methods=['GET'])
def outlook_confirm_task_status(task_id):
    """Polling do status da importação assíncrona de emails."""
    return jsonify(_outlook_confirm_task_get(task_id))


@app.route('/api/outlook/apply-suggestions', methods=['POST'])
def outlook_apply_suggestions():
    """Aplica sugestões de status e Kanban aprovadas pelo usuário."""
    try:
        data = request.get_json() or {}
        status_updates = data.get('status_updates', [])
        kanban_moves = data.get('kanban_moves', [])

        conn = get_db()
        c = conn.cursor()
        applied = 0

        for upd in status_updates:
            client_id = upd.get('client_id')
            stage = (upd.get('stage') or '').strip()
            if client_id and stage:
                c.execute('UPDATE clients SET relationship_stage = ? WHERE id = ?', (stage, client_id))
                applied += 1

        for mv in kanban_moves:
            card_id = mv.get('card_id')
            col_id = mv.get('column_id')
            if card_id and col_id:
                c.execute(
                    'UPDATE kanban_cards SET column_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                    (col_id, card_id)
                )
                applied += 1

        conn.commit()
        conn.close()
        return jsonify({'applied': applied, 'message': f'{applied} sugestão(ões) aplicada(s).'})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/outlook/apply-suggestions: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/outlook/addon-preview', methods=['POST'])
def outlook_addon_preview():
    """Conta matched/unmatched sem armazenar — usado pela task pane para mostrar estatísticas."""
    try:
        data = request.get_json() or {}
        emails = data.get('emails') or []
        if not emails:
            return jsonify({'matched': 0, 'unmatched': 0})
        conn = get_db()
        activities, unmatched, _ = _outlook_match_emails(emails, conn)
        conn.close()
        return jsonify({'matched': len(activities), 'unmatched': len(unmatched)})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/outlook/addon-preview: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/outlook/ingest-from-addon', methods=['POST'])
def outlook_ingest_from_addon():
    """Recebe emails da task pane do Outlook Add-in, faz matching e armazena como pendente."""
    try:
        data = request.get_json() or {}
        emails = data.get('emails') or []
        if not emails:
            return jsonify({'message': 'Nenhum email recebido.', 'matched': 0, 'unmatched': 0})

        conn = get_db()
        activities, unmatched, all_clients = _outlook_match_emails(emails, conn)
        conn.close()

        payload = {
            'total_read': len(emails),
            'activities': activities,
            'unmatched': unmatched,
            'all_clients': all_clients,
            'message': f'{len(activities)} email(s) com cliente · {len(unmatched)} sem correspondência · {len(emails)} lidos'
        }
        _addin_set_pending(payload)

        return jsonify({
            'message': f'{len(activities)} email(s) prontos para revisão no Toca.',
            'matched': len(activities),
            'unmatched': len(unmatched),
            'total': len(emails)
        })
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/outlook/ingest-from-addon: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/outlook/addon-pending', methods=['GET'])
def outlook_addon_pending():
    """Retorna dados pendentes do add-in (se existirem e não expirarem)."""
    pending = _addin_get_pending()
    if pending is None:
        return jsonify({'has_data': False})
    return jsonify(dict(has_data=True, **pending))


@app.route('/api/outlook/addon-pending', methods=['DELETE'])
def outlook_addon_pending_clear():
    """Limpa dados pendentes do add-in."""
    _addin_clear_pending()
    return jsonify({'ok': True})


@app.route('/api/outlook/manifest.xml')
def outlook_addin_manifest():
    """Serve o manifest do Outlook Add-in com a URL base correta para o host atual."""
    base_url = f"{request.scheme}://{request.host}"
    addin_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<OfficeApp xmlns="http://schemas.microsoft.com/office/appforoffice/1.1"
           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
           xmlns:bt="http://schemas.microsoft.com/office/officeappbasictypes/1.0"
           xmlns:mailappor="http://schemas.microsoft.com/office/mailappversionoverrides/1.0"
           xsi:type="MailApp">
  <Id>{addin_id}</Id>
  <Version>1.1.0.0</Version>
  <ProviderName>TocaDoCoelho</ProviderName>
  <DefaultLocale>pt-BR</DefaultLocale>
  <DisplayName DefaultValue="Toca do Coelho"/>
  <Description DefaultValue="Exporta emails do Outlook para atividades no Toca"/>
  <IconUrl DefaultValue="{base_url}/favicon.png"/>
  <HighResolutionIconUrl DefaultValue="{base_url}/favicon.png"/>
  <SupportUrl DefaultValue="{base_url}"/>
  <AppDomains>
    <AppDomain>{base_url}</AppDomain>
  </AppDomains>
  <Hosts>
    <Host Name="Mailbox"/>
  </Hosts>
  <Requirements>
    <Sets>
      <Set Name="MailBox" MinVersion="1.1"/>
    </Sets>
  </Requirements>
  <FormSettings>
    <Form xsi:type="ItemRead">
      <DesktopSettings>
        <SourceLocation DefaultValue="{base_url}/outlook-addin/taskpane.html"/>
        <RequestedHeight>220</RequestedHeight>
      </DesktopSettings>
    </Form>
  </FormSettings>
  <Permissions>ReadWriteMailbox</Permissions>
  <Rule xsi:type="RuleCollection" Mode="Or">
    <Rule xsi:type="ItemIs" ItemType="Message" FormType="Read"/>
  </Rule>
  <DisableEntityHighlighting>false</DisableEntityHighlighting>
</OfficeApp>"""
    resp = Response(xml, mimetype='application/xml')
    if request.args.get('download'):
        resp.headers['Content-Disposition'] = 'attachment; filename="toca-manifest.xml"'
    return resp


@app.route('/api/outlook/install-addin.bat')
def outlook_install_addin_bat():
    """Gera instalador .bat do suplemento Outlook com a URL base correta."""
    base_url = f"{request.scheme}://{request.host}"
    manifest_url = f"{base_url}/api/outlook/manifest.xml"
    catalog_guid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    bat = (
        "@echo off\r\n"
        "setlocal enabledelayedexpansion\r\n"
        "chcp 65001 >nul 2>&1\r\n"
        "echo ======================================\r\n"
        "echo  Instalador do Suplemento Toca do Coelho\r\n"
        "echo ======================================\r\n"
        "echo.\r\n"
        "set ADDIN_DIR=%USERPROFILE%\\TocaAddin\r\n"
        "if not exist \"%ADDIN_DIR%\" mkdir \"%ADDIN_DIR%\"\r\n"
        "echo Baixando manifest do suplemento...\r\n"
        f"powershell -Command \"Invoke-WebRequest -Uri '{manifest_url}' -OutFile '%ADDIN_DIR%\\manifest.xml' -UseBasicParsing\"\r\n"
        "if not exist \"%ADDIN_DIR%\\manifest.xml\" (\r\n"
        "    echo ERRO: Nao foi possivel baixar o manifest.\r\n"
        f"    echo Verifique que o Toca esta rodando em {base_url}\r\n"
        "    pause\r\n"
        "    exit /b 1\r\n"
        ")\r\n"
        "echo Configurando catalogo confiavel do Outlook...\r\n"
        f"reg add \"HKCU\\Software\\Microsoft\\Office\\16.0\\WEF\\TrustedCatalogs\\{{{catalog_guid}}}\" /v Url /t REG_SZ /d \"%ADDIN_DIR%\\\" /f >nul\r\n"
        f"reg add \"HKCU\\Software\\Microsoft\\Office\\16.0\\WEF\\TrustedCatalogs\\{{{catalog_guid}}}\" /v Flags /t REG_DWORD /d 1 /f >nul\r\n"
        f"reg add \"HKCU\\Software\\Microsoft\\Office\\16.0\\WEF\\TrustedCatalogs\\{{{catalog_guid}}}\" /v DisplayName /t REG_SZ /d \"Toca do Coelho\" /f >nul\r\n"
        "echo.\r\n"
        "echo Suplemento instalado com sucesso!\r\n"
        "echo.\r\n"
        "echo PROXIMOS PASSOS:\r\n"
        "echo 1. Feche e reabra o Outlook\r\n"
        "echo 2. No Outlook: Pagina Inicial ^> Obter Suplementos\r\n"
        "echo 3. Clique em \"Pasta Compartilhada\" e ative \"Toca do Coelho\"\r\n"
        "echo 4. Ao abrir qualquer email, o painel Toca aparece na ribbon\r\n"
        "echo 5. Carregue os emails e clique em \"Enviar para Toca\"\r\n"
        "echo.\r\n"
        "pause\r\n"
    )
    resp = Response(bat, mimetype='application/octet-stream')
    resp.headers['Content-Disposition'] = 'attachment; filename="instalar-suplemento-toca.bat"'
    return resp


@app.route('/api/outlook/import', methods=['POST'])
def import_outlook_emails():
    """Importação via arquivo JSON (fallback / uso avançado)."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'Nenhum arquivo enviado'}), 400
        file = request.files['file']
        if not (file.filename or '').lower().endswith('.json'):
            return jsonify({'error': 'Formato inválido. Envie um arquivo .json com emails do Outlook.'}), 400
        file.seek(0, 2)
        if file.tell() > 20 * 1024 * 1024:
            return jsonify({'error': 'Arquivo muito grande. Máximo: 20MB.'}), 400
        file.seek(0)
        try:
            data = json.loads(file.read().decode('utf-8'))
        except Exception:
            return jsonify({'error': 'Arquivo JSON inválido.'}), 400
        emails = data.get('emails', [])
        if not emails:
            return jsonify({'imported': 0, 'skipped_duplicates': 0, 'skipped_no_match': 0,
                            'message': 'Nenhum email encontrado no arquivo.'}), 200
        conn = get_db()
        imported, skipped_duplicates, skipped_no_match = _outlook_import_emails(emails, conn)
        conn.close()
        msg = f'{imported} atividade(s) importada(s)'
        if skipped_duplicates:
            msg += f', {skipped_duplicates} duplicata(s) ignorada(s)'
        msg += '.'
        return jsonify({'imported': imported, 'skipped_duplicates': skipped_duplicates,
                        'skipped_no_match': skipped_no_match, 'message': msg})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/outlook/import: {e}')
        return jsonify({'error': str(e)}), 500
