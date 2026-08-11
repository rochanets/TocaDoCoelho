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


# ---------------------------------------------------------------------------
# Watcher de feedback → Claude Code (roda só no perfil do administrador).
#
# A parte pura (descoberta de executáveis, worktree, subprocess) vive em
# integrations/feedback_watcher.py (importado no app.py como `fw`). Aqui
# ficam o gate por perfil, o poll da inbox via Graph, a orquestração de cada
# job e o e-mail de resultado. Dedup por graph_message_id na tabela
# feedback_auto_jobs — o e-mail NÃO é marcado como lido (exigiria escopo
# Mail.ReadWrite, que não temos nem vamos pedir).
# ---------------------------------------------------------------------------

FEEDBACK_JOBS_DIR = (Path(os.environ.get('LOCALAPPDATA') or tempfile.gettempdir())
                     / 'TocaDoCoelho' / 'feedback-jobs')


def _feedback_watcher_enabled():
    raw = (_resolve_setting('feedback_watcher_enabled', 'TOCA_FEEDBACK_WATCHER') or '')
    return raw.strip().lower() in ('1', 'true', 'on')


def _feedback_watcher_repo():
    return (_resolve_setting('feedback_watcher_repo', 'TOCA_FEEDBACK_REPO')
            or r'C:\TocaDoCoelho').strip()


def _feedback_watcher_gate():
    """Todas as condições precisam valer; nas máquinas dos demais usuários
    alguma sempre falha (no limite: a caixa conectada não é a do admin).
    Devolve dict com ok/reason e, quando ok, token/claude_exe/repo prontos."""
    gate = {'ok': False, 'reason': '', 'token': None, 'claude_exe': None, 'repo': None}
    if not _feedback_watcher_enabled():
        gate['reason'] = 'desligado (feedback_watcher_enabled)'
        return gate
    claude_exe = fw.find_claude_exe()
    if not claude_exe:
        gate['reason'] = 'claude.exe não encontrado (PATH nem %APPDATA%\\Claude\\claude-code)'
        return gate
    if not fw.find_gh_exe():
        gate['reason'] = 'gh (GitHub CLI) não encontrado no PATH'
        return gate
    repo = Path(_feedback_watcher_repo())
    if not (repo / '.git').exists():
        gate['reason'] = f'repositório git não encontrado em {repo}'
        return gate
    try:
        graph_settings = _graph_make_settings(redirect_uri=_graph_redirect_uri())
        conn = get_db()
        try:
            token = outlook_graph_get_valid_access_token(
                conn=conn, user_id=1, settings=graph_settings)
        finally:
            conn.close()
        me = (_graph_get_me_email(token) or '').strip().lower()
    except Exception as e:
        gate['reason'] = f'Outlook não conectado: {e}'
        return gate
    if me != _feedback_admin_email().lower():
        gate['reason'] = f'conta conectada ({me}) não é a do administrador'
        return gate
    gate.update({'ok': True, 'token': token, 'claude_exe': claude_exe, 'repo': str(repo)})
    return gate


def _feedback_watcher_insert_job(msg):
    """Registra o job; devolve o id, ou None se a mensagem já foi processada
    (dedup pelo UNIQUE de graph_message_id)."""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('INSERT INTO feedback_auto_jobs (graph_message_id, subject, sender) '
                  'VALUES (?, ?, ?)',
                  (msg['id'], msg.get('subject') or '', msg.get('sender_email') or ''))
        conn.commit()
        return c.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def _feedback_watcher_update_job(job_id, **fields):
    if not fields:
        return
    sets = ', '.join(f'{k} = ?' for k in fields)
    conn = get_db()
    conn.execute(f'UPDATE feedback_auto_jobs SET {sets} WHERE id = ?',
                 (*fields.values(), job_id))
    conn.commit()
    conn.close()


def _feedback_watcher_process_job(job_id, msg, gate):
    agora = lambda: datetime.now().isoformat(timespec='seconds')  # noqa: E731
    _feedback_watcher_update_job(job_id, status='running', started_at=agora())
    logger.info(f'[FeedbackWatcher] Job {job_id} iniciado — "{msg.get("subject")}"')

    job_dir = FEEDBACK_JOBS_DIR / str(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    try:
        atts = outlook_graph_fetch_message_attachments(gate['token'], msg['id'])
    except Exception as e:
        logger.warning(f'[FeedbackWatcher] Job {job_id}: anexos indisponíveis: {e}')
        atts = []
    for att in atts:
        nome = os.path.basename(att.get('name') or 'anexo.txt') or 'anexo.txt'
        try:
            (job_dir / nome).write_bytes(base64.b64decode(att.get('content_bytes') or ''))
        except Exception as e:
            logger.warning(f'[FeedbackWatcher] Job {job_id}: anexo "{nome}" ignorado: {e}')
    (job_dir / 'feedback.md').write_text(
        fw.build_feedback_md(msg.get('subject') or '', msg.get('sender_email') or '',
                             msg.get('received_at') or '', msg.get('body_text') or ''),
        encoding='utf-8')

    result = fw.run_claude_job(gate['claude_exe'], gate['repo'], job_dir, job_id)
    logger.info(f'[FeedbackWatcher] Job {job_id} terminou: ok={result["ok"]} '
                f'pr={result.get("pr_url")} erro={result.get("error")}')

    destino = _feedback_admin_email()
    remetente = msg.get('sender_name') or msg.get('sender_email') or 'usuário'
    if result['ok']:
        _feedback_watcher_update_job(job_id, status='done', report=result['report'],
                                     branch=result['branch'], pr_url=result['pr_url'],
                                     error=None, finished_at=agora())
        status_label = 'PR aberto' if result['pr_url'] else 'diagnóstico'
        pr_html = (f'<p><strong>PR:</strong> <a href="{html.escape(result["pr_url"])}">'
                   f'{html.escape(result["pr_url"])}</a></p>' if result['pr_url'] else '')
        body = (
            f'<p><strong>Análise automática do feedback de {html.escape(remetente)}</strong></p>'
            f'{pr_html}'
            f'<pre style="white-space:pre-wrap; font-size:13px;">'
            f'{html.escape(result["report"][:20000])}</pre>'
        )
        assunto = f'🤖 Análise do feedback — {remetente} — {status_label}'
    else:
        _feedback_watcher_update_job(job_id, status='error', report=result['report'],
                                     error=result['error'], finished_at=agora())
        body = (
            f'<p><strong>A análise automática do feedback de {html.escape(remetente)} '
            f'falhou.</strong></p>'
            f'<p>{html.escape(result["error"] or "erro desconhecido")}</p>'
            f'<p style="color:#6b7280; font-size:12px;">Material do job em '
            f'{html.escape(str(job_dir))}.</p>'
        )
        assunto = f'🤖 Análise do feedback — {remetente} — erro'
    try:
        _outlook_send_mail(destino, assunto, body)
    except Exception as e:
        logger.warning(f'[FeedbackWatcher] Job {job_id}: e-mail de resultado falhou: {e}')


def _feedback_watcher_tick():
    """Uma rodada: gate → não lidas → filtra feedback → processa as novas.
    Devolve o gate (para o loop logar o motivo quando inativo)."""
    gate = _feedback_watcher_gate()
    if not gate['ok']:
        return gate
    msgs = outlook_graph_fetch_unread_inbox(gate['token'])
    for msg in msgs:
        if not fw.is_feedback_subject(msg.get('subject')):
            continue
        job_id = _feedback_watcher_insert_job(msg)
        if job_id is None:
            continue  # já processado numa rodada anterior
        _feedback_watcher_process_job(job_id, msg, gate)
    return gate


_feedback_watcher_started = False


def _start_feedback_watcher():
    global _feedback_watcher_started
    if _feedback_watcher_started or os.environ.get('TOCA_DISABLE_BG_JOBS') == '1':
        return
    _feedback_watcher_started = True

    def _loop():
        last_reason = None
        while True:
            try:
                minutes = int(_resolve_setting('feedback_watcher_poll_minutes',
                                               'TOCA_FEEDBACK_POLL_MINUTES') or 5)
            except Exception:
                minutes = 5
            time.sleep(max(minutes, 1) * 60)
            try:
                gate = _feedback_watcher_tick()
                reason = gate.get('reason') or ''
                if not gate.get('ok') and reason != last_reason:
                    # loga só na mudança para não poluir o app.log a cada 5 min
                    logger.info(f'[FeedbackWatcher] Inativo: {reason}')
                last_reason = reason
            except Exception as e:
                logger.warning(f'[FeedbackWatcher] Tick falhou: {e}')

    threading.Thread(target=_loop, daemon=True).start()
    logger.info('[FeedbackWatcher] Watcher de feedback iniciado')
