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

    # Mostra tenant/client_id/scope/redirect_uri de verdade, e de ONDE cada um
    # veio. `_resolve_setting` dá precedência ao banco: um outlook_graph_client_id
    # antigo salvo em Configurações sobrepõe silenciosamente a credencial
    # embarcada e autorizada pela empresa — e o Azure passa a pedir consentimento
    # para um aplicativo diferente do que o admin liberou. Sem isso aparecer aqui,
    # esse caso é invisível.
    db_tenant = (_resolve_setting('outlook_graph_tenant_id', 'OUTLOOK_GRAPH_TENANT_ID') or '').strip()
    db_client_id = (_resolve_setting('outlook_graph_client_id', 'OUTLOOK_GRAPH_CLIENT_ID') or '').strip()
    graph_settings = _graph_make_settings(redirect_uri=_graph_redirect_uri())
    tenant = graph_settings['tenant']
    client_id = graph_settings['client_id']
    has_graph_creds = bool(tenant and client_id)
    origem_tenant = 'Configurações/ambiente' if db_tenant else 'embarcado no build'
    origem_client = 'Configurações/ambiente' if db_client_id else 'embarcado no build'
    checks.append({
        'label': 'Graph API (credenciais)',
        'ok': has_graph_creds,
        'detail': (
            f'Tenant {tenant or "—"} ({origem_tenant}) · '
            f'Client ID {client_id or "—"} ({origem_client})'
            if has_graph_creds
            else 'Configure Tenant ID / Client ID nas Configurações'
        )
    })
    # O caso "travado na tela 'Precisa de aprovação de administrador'" não deixa
    # rastro nenhum no banco (o Azure nunca redireciona de volta), então o link
    # de consentimento de administrador aparece aqui incondicionalmente — é daqui
    # que o usuário copia o link para mandar ao admin (ou abre, se for admin).
    admin_consent_url = ''
    try:
        admin_consent_url = outlook_graph_build_admin_consent_url(settings=graph_settings)
    except Exception as e:
        logger.debug(f'[outlook_diagnose] sem link de admin consent: {e}')
    checks.append({
        'label': 'Graph API (escopos e redirect)',
        'ok': bool(graph_settings['scope'] and graph_settings['redirect_uri']),
        'detail': (
            f'Escopos: {graph_settings["scope"] or "—"} · '
            f'Redirect URI: {graph_settings["redirect_uri"] or "— (abra o app pelo navegador para registrar)"}. '
            'Estes escopos precisam de consentimento DELEGADO no Azure (não "Aplicativo"), '
            'e o Redirect URI precisa estar registrado no aplicativo.'
            + (
                f' Se o Azure travar em "Precisa de aprovação de administrador", '
                f'um admin resolve de uma vez abrindo: {admin_consent_url}'
                if admin_consent_url else ''
            )
        )
    })

    # Igual ao graph-status: a existência da linha em user_integrations não
    # significa que o token presta. Um grant revogado/sem consentimento aparecia
    # aqui como "Token OAuth ativo".
    graph_state = {'connected': False, 'needs_reauth': False, 'needs_consent': False, 'reason': ''}
    try:
        conn = get_db()
        try:
            graph_state = outlook_graph_get_integration_state(conn, 1)
        finally:
            conn.close()
    except Exception as e:
        logger.debug(f'[outlook_diagnose] exceção ignorada: {e}')
    if graph_state.get('connected'):
        graph_token_detail = 'Token OAuth ativo'
    elif graph_state.get('needs_consent'):
        graph_token_detail = f'Consentimento pendente — {graph_state.get("reason") or "reconecte pedindo consentimento"}'
    elif graph_state.get('needs_reauth'):
        graph_token_detail = f'Autorização inválida — {graph_state.get("reason") or "reconecte a conta"}'
    else:
        graph_token_detail = 'Não autenticado — use "Conectar Microsoft 365"'
    checks.append({
        'label': 'OAuth Graph autenticado',
        'ok': bool(graph_state.get('connected')),
        'detail': graph_token_detail
    })

    total_clients = 0
    clients_with_email = 0
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM clients')
        total_clients = (c.fetchone() or [0])[0]
        c.execute('SELECT COUNT(*) FROM clients WHERE email IS NOT NULL AND TRIM(email) != ""')
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

    has_graph_token = bool(graph_state.get('connected'))
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
        # Opt-in: força a tela de consentimento. Só use quando o consentimento
        # realmente estiver faltando (AADSTS65001) — por padrão o fluxo aproveita
        # o consentimento já concedido pelo administrador do tenant.
        force_consent = (request.args.get('force_consent') or '').strip().lower() in {'1', 'true', 'yes'}
        settings = _graph_make_settings(redirect_uri=_graph_redirect_uri())
        conn = get_db()
        try:
            auth_url = outlook_graph_build_authorize_url(
                conn=conn, user_id=user_id, settings=settings, force_consent=force_consent
            )
        finally:
            conn.close()
        return jsonify({'auth_url': auth_url, 'provider': 'outlook_graph', 'user_id': user_id})
    except OutlookOAuthError as e:
        logger.error(f'[Outlook][OAuth] Falha ao iniciar OAuth: {e}')
        return jsonify({'error': str(e), 'error_type': 'oauth_authentication'}), 400
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/outlook/oauth/start: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/outlook/oauth/admin-consent-url', methods=['GET'])
def outlook_oauth_admin_consent_url():
    """Link do consentimento de administrador (endpoint v2 do Azure).

    Para o caso em que o tenant bloqueia o consentimento de usuário e o Azure
    trava em "Precisa de aprovação de administrador": um admin abre este link
    (ou recebe dele por e-mail) e concede o consentimento delegado do tenant
    inteiro de uma vez — depois disso o Conectar normal funciona."""
    try:
        settings = _graph_make_settings(redirect_uri=_graph_redirect_uri())
        url = outlook_graph_build_admin_consent_url(settings=settings)
        return jsonify({'admin_consent_url': url})
    except OutlookOAuthError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/outlook/oauth/admin-consent-url: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/outlook/oauth/callback', methods=['GET'])
def outlook_oauth_callback():
    try:
        error = (request.args.get('error') or '').strip()
        if error:
            desc = request.args.get('error_description') or error
            # Loga o erro cru do Azure (vem com o código AADSTS e o correlation_id
            # na descrição) — sem isso não há como diagnosticar remotamente.
            logger.error(f'[Outlook][OAuth] Azure recusou a autorização (error={error}): {desc}')
            # Vai para a tela do popup que TEM o botão de tentar novamente pedindo
            # consentimento. Antes caía em /?graph_error=, na janela principal, que
            # só mostra um alerta — deixando o usuário sem nenhuma saída quando o
            # que faltava era exatamente o consentimento.
            params = urllib.parse.urlencode({
                'error': str(desc),
                'needs_consent': '1' if error in {'consent_required', 'access_denied', 'interaction_required'} else '0',
            })
            return redirect(f'/outlook-connected.html?{params}', 302)

        # Retorno do consentimento de administrador (/v2.0/adminconsent): vem
        # com admin_consent=True e SEM code/state — sem este tratamento, o admin
        # que acabou de aprovar caía em "Parâmetros OAuth incompletos".
        if (request.args.get('admin_consent') or '').strip().lower() == 'true':
            logger.info(
                f"[Outlook][OAuth] Consentimento de administrador concedido "
                f"(tenant={request.args.get('tenant') or '?'}, scope={request.args.get('scope') or '?'})"
            )
            return redirect('/outlook-connected.html?admin_consent=1', 302)

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
        params = urllib.parse.urlencode({
            'error': str(e),
            'needs_consent': '1' if isinstance(e, OutlookConsentRequiredError) else '0',
        })
        return redirect(f'/outlook-connected.html?{params}', 302)
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
        c.execute('INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/outlook/graph-status', methods=['GET'])
def outlook_graph_status_endpoint():
    """Retorna se o usuário está conectado ao Microsoft Graph e com qual email."""
    try:
        conn = get_db()
        try:
            state = outlook_graph_get_integration_state(conn, 1)
        finally:
            conn.close()
        if not state.get('connected'):
            # Antes bastava a linha existir em user_integrations para responder
            # connected: true — então um token morto mantinha a UI em "conectado"
            # para sempre, escondendo o botão Conectar e deixando o usuário sem
            # nenhuma forma de refazer a autorização.
            return jsonify({
                'connected': False,
                'needs_reauth': bool(state.get('needs_reauth')),
                'needs_consent': bool(state.get('needs_consent')),
                'error': state.get('reason') or '',
            })
        email = None
        try:
            settings = _graph_make_settings(redirect_uri=_graph_redirect_uri())
            conn2 = get_db()
            try:
                token = outlook_graph_get_valid_access_token(conn=conn2, user_id=1, settings=settings)
            finally:
                conn2.close()
            req = urllib.request.Request('https://graph.microsoft.com/v1.0/me?$select=mail,userPrincipalName', method='GET')
            req.add_header('Authorization', f'Bearer {token}')
            req.add_header('Accept', 'application/json')
            with urllib.request.urlopen(req, timeout=10) as resp:
                me = json.loads(resp.read())
                email = me.get('mail') or me.get('userPrincipalName')
        except OutlookReauthRequiredError as e:
            # A renovação já invalidou o grant — reporta desconectado com o
            # motivo, em vez de mascarar a falha como "conectado".
            logger.warning(f'[outlook_graph_status_endpoint] grant inválido: {e}')
            return jsonify({
                'connected': False,
                'needs_reauth': True,
                'needs_consent': isinstance(e, OutlookConsentRequiredError),
                'error': str(e),
            })
        except Exception as e:
            # Falha de rede/Graph não invalida a conexão — segue conectado sem email.
            logger.debug(f'[outlook_graph_status_endpoint] exceção ignorada: {e}')
        return jsonify({'connected': True, 'email': email, 'expires_at': state.get('expires_at')})
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


# ===========================================================================
# Envio de e-mail pela conta conectada (OAuth / Microsoft Graph)
# Usado pela Mala Direta para despachar a fila inteira sem abrir uma janela
# do Outlook Web por contato. O caminho legado (deeplink "Abrir no Outlook")
# continua disponível e é o fallback quando não há conta conectada.
# ===========================================================================

# O Graph limita o envio delegado a ~30 mensagens/minuto por caixa; o intervalo
# aleatório mantém a fila abaixo disso e evita disparar a heurística de spam do
# tenant em listas grandes.
_EMAIL_SEND_INTERVAL_MIN_DEFAULT = 1.5
_EMAIL_SEND_INTERVAL_MAX_DEFAULT = 3.0


def _email_body_to_html(message):
    """Converte o corpo em texto puro da mala direta para HTML seguro."""
    return '<p>' + html.escape(message or '').replace('\n', '<br>') + '</p>'


def _email_send_and_register(c, client_id, to, subject, message, register_activity=True):
    """Envia um e-mail pela conta Microsoft conectada e registra a atividade.

    Retorna {ok, error, needs_auth, activity_id}. `needs_auth` distingue "a
    conta não está conectada / o consentimento caiu" (a fila inteira falharia,
    não adianta continuar) de uma falha pontual daquele destinatário.
    """
    to = (to or '').strip()
    if not to:
        return {'ok': False, 'error': 'Contato sem e-mail cadastrado.'}
    subject = (subject or '').strip() or '(sem assunto)'
    message = message or ''
    try:
        _outlook_send_mail(to, subject, _email_body_to_html(message))
    except (OutlookReauthRequiredError, OutlookOAuthError) as e:
        return {'ok': False, 'needs_auth': True, 'error': str(e)}
    except Exception as e:
        logger.warning(f'[Outlook][Envio] Falha ao enviar para {to}: {e}')
        return {'ok': False, 'error': str(e)}

    activity_id = None
    if register_activity and client_id:
        info = f'E-mail enviado via Outlook (OAuth): {subject}\n{message[:400]}'
        c.execute("INSERT INTO activities (client_id, contact_type, information) VALUES (?, 'Email', ?)",
                  (client_id, info))
        activity_id = c.lastrowid
        c.execute('UPDATE clients SET last_activity_date = CURRENT_TIMESTAMP WHERE id = ?', (client_id,))
        _inbound_mark_responded(c, client_id, 'email')
    return {'ok': True, 'activity_id': activity_id}


@app.route('/api/outlook/send', methods=['POST'])
def outlook_send_single():
    """Envia um e-mail pela conta conectada e registra a atividade."""
    try:
        data = request.get_json(force=True) or {}
        to = (data.get('to') or '').strip()
        message = (data.get('message') or '').strip()
        if not to or not message:
            return jsonify({'error': 'Destinatário e mensagem são obrigatórios.'}), 400
        conn = get_db()
        c = conn.cursor()
        result = _email_send_and_register(
            c, data.get('client_id'), to, data.get('subject'), message,
            register_activity=data.get('register_activity', True)
        )
        conn.commit()
        conn.close()
        status = 200 if result.get('ok') else (401 if result.get('needs_auth') else 502)
        return jsonify(result), status
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/outlook/send: {e}')
        return jsonify({'error': str(e)}), 500


def _outlook_batch_send_async(task_id, items, interval_min, interval_max):
    import random as _random
    try:
        conn = get_db()
        c = conn.cursor()
        total = len(items)
        sent = failed = blocked = 0
        details = []
        for i, item in enumerate(items):
            name = item.get('name') or item.get('to') or f'contato {i + 1}'
            _bg_task_set(task_id, {
                'step': f'Enviando para {name}... ({i + 1}/{total})',
                'progress': 5 + int((i / max(total, 1)) * 90)
            })
            result = _email_send_and_register(
                c, item.get('client_id'), item.get('to') or '',
                item.get('subject'), item.get('message') or ''
            )
            conn.commit()
            if result.get('needs_auth'):
                # Token/consentimento caiu no meio da fila: o restante falharia
                # igual, então é marcado como bloqueado em vez de erro por contato.
                reason = result.get('error') or 'Conta Microsoft desconectada.'
                details.append({'name': name, 'status': 'blocked', 'error': reason})
                for rest in items[i + 1:]:
                    details.append({'name': rest.get('name') or rest.get('to'),
                                    'status': 'blocked', 'error': reason})
                blocked = total - i
                break
            if result.get('ok'):
                sent += 1
                details.append({'name': name, 'status': 'sent', 'activity_id': result.get('activity_id')})
            else:
                # Falha em 1 destinatário não interrompe a fila.
                failed += 1
                details.append({'name': name, 'status': 'error', 'error': result.get('error')})
            if i < total - 1:
                time.sleep(_random.uniform(interval_min, interval_max))
        conn.close()
        logger.info(f'[Outlook][Mala Direta] Despacho concluído: {sent} enviado(s), '
                    f'{failed} falha(s), {blocked} bloqueado(s) de {total}.')
        _bg_task_set(task_id, {
            'status': 'done', 'progress': 100, 'step': 'Concluído!',
            'result': {'sent': sent, 'failed': failed, 'blocked': blocked, 'details': details}
        })
        _bg_task_cleanup(task_id, delay=600)
    except Exception as e:
        logger.exception(f'[Outlook][Mala Direta] Falha no despacho: {e}')
        _bg_task_set(task_id, {'status': 'error', 'error': str(e)})
        _bg_task_cleanup(task_id)


@app.route('/api/outlook/send-batch', methods=['POST'])
def outlook_send_batch():
    """Dispara a fila da mala direta pela conta conectada, em background."""
    try:
        data = request.get_json(force=True) or {}
        items = data.get('items') or []
        if not items:
            return jsonify({'error': 'Nenhum contato na fila.'}), 400

        # Recusa antes de abrir a thread quando não há conta conectada — assim o
        # usuário recebe o motivo na hora, em vez de uma fila que falha inteira.
        conn = get_db()
        try:
            state = outlook_graph_get_integration_state(conn, 1)
        finally:
            conn.close()
        if not state.get('connected'):
            return jsonify({
                'error': state.get('reason') or 'Conecte sua conta Microsoft 365 para enviar pelo Outlook.',
                'needs_auth': True,
                'needs_consent': bool(state.get('needs_consent')),
            }), 401

        try:
            interval_min = float(_resolve_setting('outlook_send_interval_min', 'OUTLOOK_SEND_INTERVAL_MIN')
                                 or _EMAIL_SEND_INTERVAL_MIN_DEFAULT)
            interval_max = float(_resolve_setting('outlook_send_interval_max', 'OUTLOOK_SEND_INTERVAL_MAX')
                                 or _EMAIL_SEND_INTERVAL_MAX_DEFAULT)
        except Exception:
            interval_min, interval_max = _EMAIL_SEND_INTERVAL_MIN_DEFAULT, _EMAIL_SEND_INTERVAL_MAX_DEFAULT
        if interval_max < interval_min:
            interval_max = interval_min

        task_id = uuid.uuid4().hex
        _bg_task_register_persistent(task_id, 'outlook_batch_send')
        _bg_task_set(task_id, {'status': 'processing', 'step': 'Iniciando despacho...', 'progress': 3})
        threading.Thread(target=_outlook_batch_send_async,
                         args=(task_id, items, interval_min, interval_max), daemon=True).start()
        return jsonify({'task_id': task_id}), 202
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/outlook/send-batch: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/outlook/send-tasks/<task_id>', methods=['GET'])
def outlook_send_task_poll(task_id):
    task = _bg_task_get(task_id)
    if not task:
        return jsonify({'status': 'not_found'}), 404
    return jsonify(task)
