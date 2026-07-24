# -*- coding: utf-8 -*-
# Rotas de autenticação SSO Microsoft (Fase 3, PR 3.2).
# Executado no namespace de app.py por _load_route_modules(): usa get_db,
# current_user, session, os helpers _graph_make_login_settings/_find_user_for_login
# e os wrappers outlook_graph_* já importados em app.py.
#
# Fluxo (Authorization Code + PKCE): /api/auth/login monta a URL de autorização
# (state/nonce/PKCE guardados no cookie de sessão pré-auth) e redireciona ao
# Entra; /api/auth/callback valida o state, troca o code, lê a identidade via
# Graph /me e — política de ALLOWLIST — só entra quem já existe em `users`
# (casando por entra_object_id → email); email desconhecido é NEGADO, nunca
# cria usuário. Nenhum token é persistido: o login só precisa das claims.


def _auth_message_page(title, message, status=200, retry=True):
    """Página HTML mínima e temática para erros/negação do login. Retornada
    diretamente (sem redirect para '/') para não criar loop com o gate, que
    manda navegações de página não autenticadas de volta para /api/auth/login."""
    safe_title = html.escape(title)
    safe_msg = html.escape(message)
    retry_html = (
        '<a class="btn" href="/api/auth/login">Entrar com a Microsoft</a>'
        if retry else '<a class="btn" href="/">Voltar</a>'
    )
    doc = f"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title} — Toca do Coelho</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif; background:#0f1115; color:#e8eaed; }}
  .card {{ max-width:440px; padding:40px 36px; background:#171a21; border:1px solid #262b36;
          border-radius:16px; text-align:center; box-shadow:0 10px 40px rgba(0,0,0,.35); }}
  h1 {{ margin:0 0 12px; font-size:22px; }}
  p {{ margin:0 0 24px; color:#aab2c0; line-height:1.5; }}
  .btn {{ display:inline-block; padding:12px 20px; border-radius:10px; text-decoration:none;
         font-weight:600; background:#2e7d32; color:#fff; }}
  .btn:hover {{ background:#276a2b; }}
</style></head>
<body><main class="card">
<h1>{safe_title}</h1>
<p>{safe_msg}</p>
<div>{retry_html}</div>
</main></body></html>"""
    return Response(doc, status=status, mimetype='text/html; charset=utf-8')


@app.route('/api/auth/login', methods=['GET'])
def auth_login():
    # Login desligado: não há handshake a fazer.
    if not _auth_enabled():
        return redirect('/', 302)
    # Já autenticado: vai direto ao destino.
    if current_user() is not None:
        return redirect(_safe_next(request.args.get('next')), 302)
    try:
        settings = _graph_make_login_settings()
        verifier, challenge = outlook_graph_new_pkce_pair()
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(16)
        auth_url = outlook_graph_build_login_authorize_url(
            settings=settings, state=state, nonce=nonce, code_challenge=challenge,
        )
    except OutlookOAuthError as e:
        logger.error(f'[Auth] Login indisponível (config OAuth): {e}')
        return _auth_message_page(
            'Login indisponível',
            f'A autenticação Microsoft não está configurada. {e}',
            status=503, retry=False,
        )
    except Exception as e:
        logger.exception(f'[Auth] Falha ao iniciar login: {e}')
        return _auth_message_page('Login indisponível',
                                  'Não foi possível iniciar o login. Tente novamente mais tarde.',
                                  status=500, retry=False)
    # state/PKCE no cookie de sessão pré-auth (uso único, validado no callback).
    session['oauth_login'] = {
        'state': state, 'verifier': verifier, 'nonce': nonce,
        'next': _safe_next(request.args.get('next')),
    }
    return redirect(auth_url, 302)


@app.route('/api/auth/callback', methods=['GET'])
def auth_callback():
    if not _auth_enabled():
        return redirect('/', 302)

    err = (request.args.get('error') or '').strip()
    if err:
        desc = request.args.get('error_description') or err
        logger.warning(f'[Auth] Erro OAuth no callback: {desc}')
        return _auth_message_page('Falha no login', str(desc), status=400)

    pending = session.pop('oauth_login', None) or {}
    code = (request.args.get('code') or '').strip()
    state = (request.args.get('state') or '').strip()
    if not code or not state or not pending or not secrets.compare_digest(state, pending.get('state', '')):
        return _auth_message_page(
            'Falha no login',
            'O fluxo de login expirou ou é inválido. Tente novamente.',
            status=400,
        )

    try:
        settings = _graph_make_login_settings()
        token_payload = outlook_graph_exchange_login_code(
            code=code, verifier=pending.get('verifier', ''), settings=settings,
        )
        claims = outlook_graph_fetch_user_claims(token_payload.get('access_token'))
    except OutlookOAuthError as e:
        logger.error(f'[Auth] Falha na troca do code de login: {e}')
        return _auth_message_page('Falha no login', str(e), status=400)
    except Exception as e:
        logger.exception(f'[Auth] Erro inesperado no callback de login: {e}')
        return _auth_message_page('Falha no login',
                                  'Não foi possível concluir o login. Tente novamente.',
                                  status=500)

    email = (claims.get('email') or '').strip().lower()
    oid = (claims.get('oid') or '').strip()
    conn = get_db()
    try:
        user = _find_user_for_login(conn, oid, email)
        if user is None:
            # ALLOWLIST: autenticou no Entra, mas não está cadastrado. Nega.
            logger.warning(f'[Auth] Login negado (allowlist): email={email!r} oid={oid!r}.')
            return _auth_message_page(
                'Acesso negado',
                'Sua conta Microsoft foi autenticada, mas ainda não está '
                'autorizada no Toca do Coelho. Peça a um administrador para '
                'liberar seu acesso e tente novamente.',
                status=403,
            )
        _apply_login_to_user(conn, user, oid, claims.get('name'))
    finally:
        conn.close()

    session['user_id'] = user['id']
    session.permanent = True
    _reset_request_user_cache()
    logger.info(f'[Auth] Login OK: user_id={user["id"]} email={email!r}.')
    return redirect(_safe_next(pending.get('next')), 302)


@app.route('/api/auth/logout', methods=['GET', 'POST'])
def auth_logout():
    session.pop('user_id', None)
    session.pop('oauth_login', None)
    _reset_request_user_cache()
    if request.method == 'GET':
        return redirect('/', 302)
    return jsonify({'ok': True})


@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    """Estado de autenticação para a SPA decidir o que renderizar."""
    u = current_user()
    if not u:
        return jsonify({'authenticated': False, 'auth_enabled': _auth_enabled()})
    return jsonify({
        'authenticated': True,
        'auth_enabled': _auth_enabled(),
        'user': {
            'id': u.get('id'),
            'email': u.get('email'),
            'full_name': u.get('full_name'),
            'nickname': u.get('nickname'),
            'role': u.get('role'),
            'photo_url': u.get('photo_url'),
        },
    })
