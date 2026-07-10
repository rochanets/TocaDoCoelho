# -*- coding: utf-8 -*-
# Rotas do domínio "whatsapp" (Bloco 3 — modularização).
# Este arquivo é executado no namespace de app.py por _load_route_modules():
# tem acesso a todos os helpers/globals de app.py e registra as rotas no
# mesmo objeto Flask `app`, com URLs idênticas às originais.

@app.route('/api/whatsapp/config', methods=['GET'])
def whatsapp_get_config():
    s = _load_app_settings_map(['waha_api_url', 'waha_api_key', 'waha_session_name'])
    has_key = bool((s.get('waha_api_key') or '').strip())
    return jsonify({
        'waha_api_url': s.get('waha_api_url') or 'http://localhost:3001',
        'waha_api_key': '••••••••' if has_key else '',
        'waha_session_name': s.get('waha_session_name') or 'default',
        'configured': bool((s.get('waha_api_url') or '').strip()),
    })


@app.route('/api/whatsapp/config', methods=['PUT'])
def whatsapp_save_config():
    data = request.get_json(force=True) or {}
    waha_url = (data.get('waha_api_url') or '').strip()
    if waha_url:
        app_port = str(os.environ.get('PORT', '3000'))
        for forbidden in (f'localhost:{app_port}', f'127.0.0.1:{app_port}'):
            if forbidden in waha_url:
                return jsonify({'ok': False,
                                'error': f'A URL do WAHA não pode apontar para a porta do próprio app (:{app_port}). Use a porta 3001.'}), 400
    db = get_db()
    c = db.cursor()
    for key in ['waha_api_url', 'waha_api_key', 'waha_session_name']:
        val = (data.get(key) or '').strip()
        if val and val != '••••••••':
            c.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
                (key, val)
            )
    db.commit()
    return jsonify({'ok': True})


@app.route('/api/whatsapp/status', methods=['GET'])
def whatsapp_status():
    api_url, api_key, session = _waha_settings()
    if not api_url:
        return jsonify({'configured': False, 'connected': False, 'state': 'not_configured'})
    try:
        resp = requests.get(f'{api_url}/api/sessions/{session}', headers=_waha_headers(api_key), timeout=5)
        if resp.status_code == 404:
            return jsonify({'configured': True, 'connected': False, 'state': 'no_session'})
        if resp.status_code == 401:
            return jsonify({'configured': True, 'connected': False, 'state': 'unauthorized',
                            'error': 'API Key inválida.'})
        body = resp.json() or {}
        raw = (body.get('status') or 'STOPPED').upper()
        waha_err = body.get('error')
        # Normaliza os estados crus do WAHA-lite (MAIÚSCULOS) para os estados que o front
        # entende (minúsculos). Sem isso, 'STARTING' não casava com nenhum branch do front,
        # que pulava direto para o QR e estourava o timeout de 40s durante o cold start do
        # Chrome — mesmo quando a sessão já estava prestes a ficar WORKING (sessão salva).
        if raw == 'WORKING':
            return jsonify({'configured': True, 'connected': True, 'state': 'connected'})
        if raw == 'SCAN_QR_CODE':
            return jsonify({'configured': True, 'connected': False, 'state': 'scan_qr'})
        if raw == 'STARTING':
            return jsonify({'configured': True, 'connected': False, 'state': 'starting',
                            'error': 'WhatsApp conectando (abrindo o Chrome e restaurando a sessão)... aguarde.'})
        # STOPPED / FAILED: se o WAHA-lite reportou um erro (ex.: navegador não encontrado),
        # mostra a causa real; senão, deixa o front seguir para (re)conectar.
        return jsonify({'configured': True, 'connected': False,
                        'state': 'offline' if waha_err else 'stopped',
                        'error': waha_err or 'Sessão do WhatsApp parada. Clique para reconectar.'})
    except requests.exceptions.ConnectionError:
        # Dependências ausentes: o Node nem sobe. Reiniciar não resolve — orientar reinstalação.
        if _waha_deps_missing():
            return jsonify({'configured': True, 'connected': False, 'state': 'offline',
                            'error': 'WAHA-lite não pôde iniciar: dependências (node_modules) ausentes. '
                                     'Reinstale o Toca do Coelho (ou rode "npm install" na pasta waha-lite).'})
        started_at = float(os.environ.get('WAHA_STARTED_AT', '0'))
        seconds_up = time.time() - started_at
        if seconds_up < 90:
            return jsonify({'configured': True, 'connected': False, 'state': 'starting',
                            'error': 'WAHA-lite está inicializando. Aguarde alguns instantes...'})
        restarted = _restart_waha_lite()
        if restarted:
            return jsonify({'configured': True, 'connected': False, 'state': 'starting',
                            'error': 'WAHA-lite foi reiniciado. Aguarde alguns instantes...'})
        return jsonify({'configured': True, 'connected': False, 'state': 'offline',
                        'error': 'Serviço do WhatsApp (WAHA-lite) offline. Reinicie o Toca do Coelho para iniciá-lo automaticamente.'})
    except Exception as e:
        return jsonify({'configured': True, 'connected': False, 'state': 'error', 'error': str(e)})


@app.route('/api/whatsapp/connect', methods=['POST'])
def whatsapp_connect():
    api_url, api_key, session = _waha_settings()
    if not api_url:
        return jsonify({'ok': False, 'error': 'WAHA não configurado.'}), 400
    headers = _waha_headers(api_key)

    # 1. Garante que a sessão existe e está iniciada
    try:
        st = requests.get(f'{api_url}/api/sessions/{session}', headers=headers, timeout=5)
        if st.status_code == 200:
            status = (st.json() or {}).get('status')
            if status == 'WORKING':
                return jsonify({'ok': True, 'connected': True})
            if status in ('STOPPED', 'FAILED'):
                requests.post(f'{api_url}/api/sessions/{session}/start', headers=headers, timeout=15)
        elif st.status_code == 404:
            # Cria e inicia a sessão
            requests.post(f'{api_url}/api/sessions/', headers=headers,
                          json={'name': session, 'start': True}, timeout=20)
        elif st.status_code == 401:
            return jsonify({'ok': False, 'error': 'API Key inválida.'}), 401
    except requests.exceptions.ConnectionError:
        return jsonify({'ok': False, 'error': 'WAHA não está acessível.'}), 503
    except Exception as exc:
        logger.warning(f'[WhatsApp] WAHA session check error: {exc}')

    # 2. Aguarda o status SCAN_QR_CODE e busca o QR (imagem PNG → base64).
    # 90s: o primeiro start (cold) abre o Chrome e carrega o WhatsApp Web — pode passar de 1 min.
    qr = None
    for _ in range(45):
        time.sleep(2)
        try:
            st = requests.get(f'{api_url}/api/sessions/{session}', headers=headers, timeout=5)
            status = (st.json() or {}).get('status') if st.ok else None
            if status == 'WORKING':
                return jsonify({'ok': True, 'connected': True})
            if status == 'SCAN_QR_CODE':
                qr_resp = requests.get(f'{api_url}/api/{session}/auth/qr',
                                       headers=headers, params={'format': 'image'}, timeout=10)
                if qr_resp.status_code == 200 and qr_resp.content:
                    ctype = qr_resp.headers.get('Content-Type', 'image/png')
                    b64 = base64.b64encode(qr_resp.content).decode('ascii')
                    qr = f'data:{ctype};base64,{b64}'
                    break
        except Exception as e:
            logger.debug(f'[whatsapp_connect] exceção ignorada: {e}')

    if qr:
        return jsonify({'ok': True, 'connected': False, 'qr': qr})

    # Reconfere uma última vez: a sessão pode ter ficado WORKING (sessão salva reconectou)
    # justamente no fim da espera — nesse caso não há QR a exibir e está tudo certo.
    try:
        st = requests.get(f'{api_url}/api/sessions/{session}', headers=headers, timeout=5)
        body = st.json() if st.ok else {}
        if (body or {}).get('status') == 'WORKING':
            return jsonify({'ok': True, 'connected': True})
        # Ainda inicializando (Chrome abrindo): pede para o front aguardar e repetir, em vez
        # de mostrar erro definitivo.
        if (body or {}).get('status') == 'STARTING':
            return jsonify({'ok': False, 'state': 'starting',
                            'error': 'WhatsApp ainda conectando (abrindo o Chrome)... aguarde alguns instantes e tente de novo.'}), 503
    except Exception as e:
        logger.debug(f'[whatsapp_connect] exceção ignorada: {e}')

    return jsonify({'ok': False, 'error': 'O QR code não apareceu a tempo. O Chrome pode estar demorando para abrir na primeira conexão — aguarde alguns instantes e clique em Tentar novamente.'}), 500


@app.route('/api/whatsapp/sync', methods=['POST'])
def whatsapp_sync_start():
    data = request.get_json(force=True) or {}
    period_days = int(data.get('period_days', 7))
    if period_days not in [1, 3, 7, 15, 30]:
        period_days = 7
    task_id = uuid.uuid4().hex
    _bg_task_register_persistent(task_id, 'whatsapp_sync')
    _bg_task_set(task_id, {'status': 'processing', 'step': 'Iniciando sincronização...', 'progress': 5})
    threading.Thread(target=_whatsapp_sync_async, args=(task_id, period_days), daemon=True).start()
    return jsonify({'task_id': task_id}), 202


@app.route('/api/whatsapp/tasks/<task_id>', methods=['GET'])
def whatsapp_task_poll(task_id):
    task = _bg_task_get(task_id)
    if not task:
        return jsonify({'status': 'not_found'}), 404
    return jsonify(task)


@app.route('/api/whatsapp/approve', methods=['POST'])
def whatsapp_approve():
    data = request.get_json(force=True) or {}
    items = data.get('items', [])
    if not isinstance(items, list):
        return jsonify({'ok': False, 'error': 'items deve ser uma lista'}), 400

    db = get_db()
    c = db.cursor()
    inserted = 0
    commitments_created = 0
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    for item in items:
        client_id = item.get('client_id')
        summary = (item.get('summary') or '').strip()
        activity_date = (item.get('activity_date') or now_str).strip()
        content_hash = (item.get('content_hash') or '').strip()
        phone = (item.get('phone') or '').strip()
        period_days = int(item.get('period_days') or 7)
        message_count = int(item.get('message_count') or 0)
        last_message_ts = int(item.get('last_message_ts') or 0)
        followup_date = (item.get('followup_date') or '').strip()
        followup_title = (item.get('followup_title') or '').strip()
        # Permite que o usuário desmarque o FUP no modal de revisão
        followup_enabled = item.get('followup_enabled', True)

        if not client_id or not summary or not content_hash:
            continue

        c.execute('SELECT id FROM whatsapp_sync_log WHERE client_id = ? AND content_hash = ?',
                  (client_id, content_hash))
        if c.fetchone():
            continue

        c.execute(
            "INSERT INTO activities (client_id, contact_type, information, activity_date) VALUES (?, 'WhatsApp', ?, ?)",
            (client_id, summary, activity_date)
        )
        activity_id = c.lastrowid
        c.execute("UPDATE clients SET last_activity_date = ? WHERE id = ?", (activity_date, client_id))
        c.execute(
            "INSERT INTO whatsapp_sync_log (client_id, phone, period_days, message_count, content_hash, last_message_ts, activity_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (client_id, phone, period_days, message_count, content_hash, last_message_ts, activity_id)
        )
        inserted += 1

        # Compromisso de follow-up (FUP) → calendário do sistema
        if followup_enabled and re.match(r'^\d{4}-\d{2}-\d{2}$', followup_date):
            title = followup_title or 'Retorno combinado (WhatsApp)'
            if len(title) > 120:
                title = title[:117] + '...'
            c.execute(
                '''INSERT INTO commitments (client_id, activity_id, title, notes, due_date, due_time, source_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (client_id, activity_id, title, summary, followup_date, None, 'whatsapp')
            )
            commitments_created += 1

    db.commit()
    db.close()
    return jsonify({'ok': True, 'inserted': inserted, 'commitments': commitments_created})


# ===========================================================================
# Caixa de respostas pendentes (Bloco 6) — rotas de inbound
# ===========================================================================

@app.route('/api/whatsapp/webhook', methods=['POST'])
def whatsapp_webhook():
    """Fase B: recebe eventos do WAHA (configurar WHATSAPP_HOOK_URL no
    docker-compose.waha.yml apontando para este endpoint)."""
    try:
        body = request.get_json(force=True, silent=True) or {}
        event = (body.get('event') or '').lower()
        payload = body.get('payload') or {}
        if event not in ('message', 'message.any'):
            return jsonify({'ok': True, 'ignored': event})
        chat_raw = payload.get('from') if not payload.get('fromMe') else payload.get('to')
        chat_id = str(chat_raw or '')
        digits = re.sub(r'\D', '', chat_id.split('@')[0])
        if not digits:
            return jsonify({'ok': True, 'ignored': 'sem_numero'})
        conn = get_db()
        c = conn.cursor()
        # match por telefone normalizado (compara via chatid gerado)
        c.execute("SELECT id, name, phone FROM clients WHERE phone IS NOT NULL AND phone != ''")
        client_id = None
        for row in c.fetchall():
            cid = _phone_to_waha_chatid(row['phone']) or ''
            if cid.split('@')[0] == digits:
                client_id = row['id']
                break
        if not client_id:
            conn.close()
            return jsonify({'ok': True, 'ignored': 'nao_cliente'})
        try:
            ts = int(payload.get('timestamp') or 0)
        except (TypeError, ValueError):
            ts = 0
        when = datetime.fromtimestamp(ts).isoformat(timespec='seconds') if ts else datetime.now().isoformat(timespec='seconds')
        if payload.get('fromMe'):
            _inbound_mark_responded(c, client_id, 'whatsapp', when)
        else:
            msg_id = payload.get('id')
            if isinstance(msg_id, dict):
                msg_id = msg_id.get('_serialized') or msg_id.get('id')
            _inbound_upsert(c, client_id, 'whatsapp', when,
                            payload.get('body') or '(mensagem sem texto)',
                            f'wa:{msg_id or (str(client_id) + ":" + str(ts))}')
        conn.commit()
        conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/whatsapp/webhook: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/inbound/pending', methods=['GET'])
def inbound_pending():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT im.id, im.client_id, im.channel, im.received_at, im.preview,
                   cl.name, cl.company,
                   CAST((julianday('now', 'localtime') - julianday(im.received_at)) * 24 AS INTEGER) AS waiting_hours
            FROM inbound_messages im
            JOIN clients cl ON cl.id = im.client_id
            WHERE im.responded_at IS NULL AND COALESCE(cl.is_archived, 0) = 0
            ORDER BY im.received_at ASC
        """)
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return jsonify(rows)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/inbound/pending: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/inbound/<int:item_id>/respond', methods=['POST'])
def inbound_mark_responded_manual(item_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE inbound_messages SET responded_at = ? WHERE id = ? AND responded_at IS NULL',
                  (datetime.now().isoformat(timespec='seconds'), item_id))
        if c.rowcount == 0:
            conn.close()
            return jsonify({'error': 'Pendência não encontrada (ou já respondida)'}), 404
        conn.commit()
        conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/inbound/{item_id}/respond: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/inbound/metrics', methods=['GET'])
def inbound_metrics():
    """Mediana do tempo de resposta (horas) dos últimos 30 dias."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT (julianday(responded_at) - julianday(received_at)) * 24 AS hours
            FROM inbound_messages
            WHERE responded_at IS NOT NULL
              AND received_at >= datetime('now', 'localtime', '-30 days')
            ORDER BY hours
        """)
        hours = [r['hours'] for r in c.fetchall() if r['hours'] is not None and r['hours'] >= 0]
        conn.close()
        median = None
        if hours:
            mid = len(hours) // 2
            median = hours[mid] if len(hours) % 2 else (hours[mid - 1] + hours[mid]) / 2
        return jsonify({'median_response_hours': round(median, 1) if median is not None else None,
                        'responded_count_30d': len(hours)})
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/inbound/metrics: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/inbound/scan', methods=['POST'])
def inbound_scan_now():
    """Dispara manualmente um ciclo de verificação (útil para testar a conexão)."""
    try:
        result = _inbound_scan_whatsapp()
        return jsonify({'ok': True, **result})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/inbound/scan: {e}')
        return jsonify({'error': str(e)}), 500


# ===========================================================================
# Envio direto via WAHA (Bloco 8) — com limite diário e intervalo aleatório
# para mitigar risco de bloqueio do número.
# ===========================================================================

def _waha_daily_quota(c):
    """Retorna (limite, usados_hoje). Limite configurável em app_settings."""
    try:
        limit = int(_resolve_setting('waha_daily_send_limit', 'WAHA_DAILY_SEND_LIMIT') or 45)
    except Exception:
        limit = 45
    c.execute("SELECT COUNT(*) FROM whatsapp_sends WHERE status = 'sent' AND date(sent_at) = date('now', 'localtime')")
    used = c.fetchone()[0]
    return limit, used


def _waha_send_text(chat_id, text):
    """Envia texto via WAHA sendText. Retorna (ok, erro)."""
    api_url, api_key, session = _waha_settings()
    try:
        resp = requests.post(
            f'{api_url}/api/sendText',
            headers=_waha_headers(api_key),
            json={'chatId': chat_id, 'text': text, 'session': session},
            timeout=30
        )
        if resp.status_code in (200, 201):
            return True, None
        return False, f'HTTP {resp.status_code}: {resp.text[:180]}'
    except Exception as e:
        return False, str(e)


def _waha_send_and_register(c, client_id, phone, message, register_activity=True):
    """Valida, respeita o limite diário, envia e registra atividade.
    Retorna dict {ok, error, activity_id, limit_reached}."""
    limit, used = _waha_daily_quota(c)
    if used >= limit:
        return {'ok': False, 'limit_reached': True,
                'error': f'Limite diário de {limit} mensagens via WAHA atingido. '
                         'Ajuste em Configurações ou use o WhatsApp Web como contingência.'}
    chat_id = _phone_to_waha_chatid(phone)
    if not chat_id:
        return {'ok': False, 'error': 'Telefone inválido para WhatsApp.'}
    ok, err = _waha_send_text(chat_id, message)
    c.execute('INSERT INTO whatsapp_sends (client_id, phone, message, status, error) VALUES (?, ?, ?, ?, ?)',
              (client_id, phone, message[:500], 'sent' if ok else 'error', err))
    if not ok:
        return {'ok': False, 'error': err}
    activity_id = None
    if register_activity and client_id:
        info = f'Mensagem enviada via WhatsApp (WAHA):\n{message[:400]}'
        c.execute("INSERT INTO activities (client_id, contact_type, information) VALUES (?, 'WhatsApp', ?)",
                  (client_id, info))
        activity_id = c.lastrowid
        c.execute('UPDATE clients SET last_activity_date = CURRENT_TIMESTAMP WHERE id = ?', (client_id,))
        _inbound_mark_responded(c, client_id, 'whatsapp')
    return {'ok': True, 'activity_id': activity_id}


@app.route('/api/whatsapp/send-quota', methods=['GET'])
def whatsapp_send_quota():
    conn = get_db()
    limit, used = _waha_daily_quota(conn.cursor())
    conn.close()
    return jsonify({'limit': limit, 'used_today': used, 'remaining': max(limit - used, 0)})


@app.route('/api/whatsapp/send', methods=['POST'])
def whatsapp_send_single():
    try:
        data = request.get_json(force=True) or {}
        message = (data.get('message') or '').strip()
        phone = (data.get('phone') or '').strip()
        client_id = data.get('client_id')
        if not message or not phone:
            return jsonify({'error': 'Telefone e mensagem são obrigatórios.'}), 400
        conn = get_db()
        c = conn.cursor()
        result = _waha_send_and_register(c, client_id, phone, message,
                                         register_activity=data.get('register_activity', True))
        conn.commit()
        conn.close()
        status = 200 if result.get('ok') else (429 if result.get('limit_reached') else 502)
        return jsonify(result), status
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/whatsapp/send: {e}')
        return jsonify({'error': str(e)}), 500


def _whatsapp_batch_send_async(task_id, items, interval_min, interval_max):
    import random as _random
    try:
        conn = get_db()
        c = conn.cursor()
        total = len(items)
        sent = failed = blocked = 0
        details = []
        for i, item in enumerate(items):
            name = item.get('name') or item.get('phone') or f'contato {i + 1}'
            _bg_task_set(task_id, {
                'step': f'📤 Enviando para {name}... ({i + 1}/{total})',
                'progress': 5 + int((i / max(total, 1)) * 90)
            })
            result = _waha_send_and_register(c, item.get('client_id'), item.get('phone') or '',
                                             (item.get('message') or '').strip())
            conn.commit()
            if result.get('limit_reached'):
                blocked = total - i
                details.append({'name': name, 'status': 'blocked', 'error': result.get('error')})
                # limite diário atingido: recusa o restante da fila
                for rest in items[i + 1:]:
                    details.append({'name': rest.get('name') or rest.get('phone'), 'status': 'blocked',
                                    'error': 'Limite diário atingido'})
                break
            if result.get('ok'):
                sent += 1
                details.append({'name': name, 'status': 'sent', 'activity_id': result.get('activity_id')})
            else:
                # falha em 1 contato não interrompe a fila
                failed += 1
                details.append({'name': name, 'status': 'error', 'error': result.get('error')})
            if i < total - 1:
                time.sleep(_random.uniform(interval_min, interval_max))
        conn.close()
        _bg_task_set(task_id, {
            'status': 'done', 'progress': 100, 'step': 'Concluído!',
            'result': {'sent': sent, 'failed': failed, 'blocked': blocked, 'details': details}
        })
        _bg_task_cleanup(task_id, delay=600)
    except Exception as e:
        logger.exception(f'[WAHA batch] Falha no despacho: {e}')
        _bg_task_set(task_id, {'status': 'error', 'error': str(e)})
        _bg_task_cleanup(task_id)


@app.route('/api/whatsapp/send-batch', methods=['POST'])
def whatsapp_send_batch():
    try:
        data = request.get_json(force=True) or {}
        items = data.get('items') or []
        if not items:
            return jsonify({'error': 'Nenhum contato na fila.'}), 400
        try:
            interval_min = float(_resolve_setting('waha_send_interval_min', 'WAHA_SEND_INTERVAL_MIN') or 8)
            interval_max = float(_resolve_setting('waha_send_interval_max', 'WAHA_SEND_INTERVAL_MAX') or 15)
        except Exception:
            interval_min, interval_max = 8.0, 15.0
        if interval_max < interval_min:
            interval_max = interval_min
        task_id = uuid.uuid4().hex
        _bg_task_register_persistent(task_id, 'whatsapp_batch_send')
        _bg_task_set(task_id, {'status': 'processing', 'step': 'Iniciando despacho...', 'progress': 3})
        threading.Thread(target=_whatsapp_batch_send_async,
                         args=(task_id, items, interval_min, interval_max), daemon=True).start()
        return jsonify({'task_id': task_id}), 202
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/whatsapp/send-batch: {e}')
        return jsonify({'error': str(e)}), 500
