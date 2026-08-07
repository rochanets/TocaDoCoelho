# -*- coding: utf-8 -*-
# Rotas do domínio "feedback".
# Este arquivo é executado no namespace de app.py por _load_route_modules():
# tem acesso a todos os helpers/globals de app.py e registra as rotas no
# mesmo objeto Flask `app`.
#
# O feedback do usuário é gravado no banco e enviado por e-mail ao
# administrador via Microsoft Graph (o mesmo caminho do briefing matinal),
# com o tail do app.log anexado. Nenhum segredo novo é distribuído: o envio
# usa o Outlook que o próprio usuário já autenticou.

FEEDBACK_LOG_MAX_LINES = 3000
FEEDBACK_LOG_MAX_BYTES = 1024 * 1024  # 1 MB de anexo é o teto


def _feedback_admin_email():
    return (_resolve_setting('feedback_admin_email', 'TOCA_FEEDBACK_EMAIL')
            or DEFAULT_FEEDBACK_EMAIL).strip()


def _feedback_user_nickname():
    """Apelido do usuário para identificar o remetente no assunto do e-mail."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT full_name, nickname FROM user_profile WHERE id = 1')
        row = c.fetchone()
        conn.close()
        if row:
            return (row['nickname'] or row['full_name'] or '').strip()
    except Exception as e:
        logger.debug(f'[Feedback] Não foi possível ler o perfil do usuário: {e}')
    return ''


def _feedback_log_tail():
    """Últimas linhas do app.log, respeitando o teto de bytes do anexo.
    Devolve (texto, total_de_linhas_do_arquivo)."""
    if not LOG_FILE.exists():
        return '', 0
    with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as fh:
        all_lines = fh.readlines()
    tail = all_lines[-FEEDBACK_LOG_MAX_LINES:]
    text = ''.join(tail)
    encoded = text.encode('utf-8', errors='replace')
    if len(encoded) > FEEDBACK_LOG_MAX_BYTES:
        # Corta pelo fim do arquivo, que é a parte relevante para diagnóstico.
        encoded = encoded[-FEEDBACK_LOG_MAX_BYTES:]
        text = encoded.decode('utf-8', errors='replace')
        text = '[... início truncado ...]\n' + text
    return text, len(all_lines)


def _feedback_set_status(feedback_id, status, error=None, sent_to=None):
    try:
        conn = get_db()
        c = conn.cursor()
        if status == 'sent':
            c.execute("UPDATE feedback SET status = ?, error = NULL, sent_to = ?, sent_at = CURRENT_TIMESTAMP WHERE id = ?",
                      (status, sent_to, feedback_id))
        else:
            c.execute('UPDATE feedback SET status = ?, error = ? WHERE id = ?',
                      (status, error, feedback_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f'[Feedback] Falha ao atualizar status do feedback {feedback_id}: {e}')


def _feedback_send_async(task_id, feedback_id, message, nickname, client_log=''):
    import platform
    try:
        destino = _feedback_admin_email()

        _bg_task_set(task_id, {'status': 'processing', 'step': 'Coletando o log do sistema...', 'progress': 35})
        log_text, total_lines = _feedback_log_tail()

        _bg_task_set(task_id, {'step': 'Montando a mensagem...', 'progress': 60})
        enviado_em = datetime.now().strftime('%d/%m/%Y %H:%M')
        remetente = nickname or 'Usuário'
        body = (
            '<p><strong>Novo feedback do Toca do Coelho 🐇</strong></p>'
            f'<p><strong>De:</strong> {html.escape(remetente)}<br>'
            f'<strong>Versão:</strong> {html.escape(str(APP_VERSION))}<br>'
            f'<strong>Sistema:</strong> {html.escape(platform.platform())}<br>'
            f'<strong>Enviado em:</strong> {html.escape(enviado_em)}</p>'
            '<hr>'
            f'<p style="white-space:pre-wrap;">{html.escape(message)}</p>'
            '<hr>'
            f'<p style="color:#6b7280; font-size:12px;">Log técnico em anexo '
            f'({total_lines} linhas no arquivo, últimas {min(total_lines, FEEDBACK_LOG_MAX_LINES)} anexadas).</p>'
        )

        attachments = []
        if log_text:
            attachments.append({
                'name': f'app-log-{datetime.now().strftime("%Y%m%d-%H%M%S")}.txt',
                'content_bytes': base64.b64encode(log_text.encode('utf-8', errors='replace')).decode('ascii'),
                'content_type': 'text/plain'
            })
        if client_log:
            # Buffer do navegador enviado pelo frontend (inclui os erros que o
            # usuário viu na tela) — complementa o app.log do servidor.
            attachments.append({
                'name': f'client-log-{datetime.now().strftime("%Y%m%d-%H%M%S")}.txt',
                'content_bytes': base64.b64encode(client_log.encode('utf-8', errors='replace')).decode('ascii'),
                'content_type': 'text/plain'
            })

        _bg_task_set(task_id, {'step': 'Enviando para o administrador...', 'progress': 75})
        assunto = f'🐇 Feedback do Toca — {remetente} — v{APP_VERSION}'
        _outlook_send_mail(destino, assunto, body, attachments)

        _feedback_set_status(feedback_id, 'sent', sent_to=destino)
        logger.info(f'[Feedback] Feedback {feedback_id} enviado para {destino}')
        _bg_task_set(task_id, {
            'status': 'done', 'progress': 100,
            'step': 'Feedback enviado! Obrigado 🐇',
            'sent_to': destino
        })
        _bg_task_cleanup(task_id, delay=300)
    except Exception as e:
        # Outlook desconectado é o erro mais provável — a mensagem precisa dizer
        # o que fazer, e o feedback fica salvo para reenvio.
        texto = str(e)
        minusculo = texto.lower()
        if (isinstance(e, (OutlookSyncError, OutlookOAuthError))
                or any(t in minusculo for t in ('token', 'graph', 'oauth', 'outlook'))):
            amigavel = ('Não foi possível enviar: conecte o Outlook em Configurações → '
                        'Microsoft 365 e envie novamente. Seu feedback foi salvo.')
        else:
            amigavel = f'Não foi possível enviar o feedback: {texto}'
        logger.exception(f'[Feedback] Falha ao enviar o feedback {feedback_id}: {e}')
        _feedback_set_status(feedback_id, 'error', error=texto)
        _bg_task_set(task_id, {'status': 'error', 'progress': 100, 'step': 'Falha no envio.', 'error': amigavel})
        _bg_task_cleanup(task_id, delay=300)


@app.route('/api/feedback', methods=['POST'])
def create_feedback():
    """Registra o feedback e dispara o envio em thread (barra de progresso)."""
    try:
        data = request.get_json() or {}
        message = (data.get('message') or '').strip()
        if not message:
            return jsonify({'error': 'Escreva sua mensagem antes de enviar.'}), 400
        if len(message) > 5000:
            message = message[:5000]

        # Log do navegador (opcional). Mantém o FIM, que é a parte recente.
        client_log = (data.get('client_log') or '').strip()
        if len(client_log) > 200000:
            client_log = client_log[-200000:]

        nickname = _feedback_user_nickname()

        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT INTO feedback (message, user_nickname, app_version, status)
                     VALUES (?, ?, ?, 'pending')''',
                  (message, nickname, str(APP_VERSION)))
        feedback_id = c.lastrowid
        conn.commit()
        conn.close()

        task_id = uuid.uuid4().hex
        _bg_task_set(task_id, {'status': 'processing', 'step': 'Registrando seu feedback...', 'progress': 10})
        threading.Thread(
            target=_feedback_send_async,
            args=(task_id, feedback_id, message, nickname, client_log),
            daemon=True
        ).start()

        return jsonify({'task_id': task_id, 'feedback_id': feedback_id}), 202
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/feedback: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/feedback/tasks/<task_id>', methods=['GET'])
def get_feedback_task(task_id):
    return jsonify(_bg_task_get(task_id))
