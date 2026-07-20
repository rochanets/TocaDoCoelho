# -*- coding: utf-8 -*-
# Rotas do domínio "config" (Bloco 3 — modularização).
# Este arquivo é executado no namespace de app.py por _load_route_modules():
# tem acesso a todos os helpers/globals de app.py e registra as rotas no
# mesmo objeto Flask `app`, com URLs idênticas às originais.

@app.route('/api/config/status', methods=['GET'])
def get_status_config():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT key, value FROM app_settings WHERE key IN ("status_green_days", "status_yellow_days", "target_green_days", "target_yellow_days", "cold_green_days", "cold_yellow_days")')
        settings = {row['key']: row['value'] for row in c.fetchall()}
        c.execute('SELECT id, position, green_days, yellow_days FROM status_rules ORDER BY position')
        rules = [dict_from_row(row) for row in c.fetchall()]
        conn.close()

        return jsonify({
            'universal': {
                'green_days': int(settings.get('status_green_days', '7')),
                'yellow_days': int(settings.get('status_yellow_days', '14'))
            },
            'rules': rules,
            'target': {
                'green_days': int(settings.get('target_green_days', '5')),
                'yellow_days': int(settings.get('target_yellow_days', '10'))
            },
            'cold': {
                'green_days': int(settings.get('cold_green_days', '45')),
                'yellow_days': int(settings.get('cold_yellow_days', '60'))
            }
        })
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/config/status: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/status/universal', methods=['PUT'])
def update_universal_status_config():
    try:
        data = request.get_json() or {}
        green_days = int(data.get('green_days', 7))
        yellow_days = int(data.get('yellow_days', 14))

        if green_days < 0 or yellow_days <= green_days:
            return jsonify({'error': 'Faixas inválidas: amarelo deve ser maior que verde'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE app_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?', (str(green_days), 'status_green_days'))
        c.execute('UPDATE app_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?', (str(yellow_days), 'status_yellow_days'))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Configuração universal atualizada'})
    except Exception as e:
        logger.exception(f'[ERROR] PUT /api/config/status/universal: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/status/target', methods=['PUT'])
def update_target_status_config():
    try:
        data = request.get_json() or {}
        green_days = int(data.get('green_days', 5))
        yellow_days = int(data.get('yellow_days', 10))

        if green_days < 0 or yellow_days <= green_days:
            return jsonify({'error': 'Faixas inválidas: amarelo deve ser maior que verde'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE app_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?', (str(green_days), 'target_green_days'))
        c.execute('UPDATE app_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?', (str(yellow_days), 'target_yellow_days'))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Configuração Target atualizada'})
    except Exception as e:
        logger.exception(f'[ERROR] PUT /api/config/status/target: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/status/cold', methods=['PUT'])
def update_cold_status_config():
    try:
        data = request.get_json() or {}
        green_days = int(data.get('green_days', 45))
        yellow_days = int(data.get('yellow_days', 60))

        if green_days < 0 or yellow_days <= green_days:
            return jsonify({'error': 'Faixas inválidas: amarelo deve ser maior que verde'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE app_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?', (str(green_days), 'cold_green_days'))
        c.execute('UPDATE app_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?', (str(yellow_days), 'cold_yellow_days'))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Configuração de contato frio atualizada'})
    except Exception as e:
        logger.exception(f'[ERROR] PUT /api/config/status/cold: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/position-groupings', methods=['GET'])
def list_position_groupings():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id, name FROM job_groupings ORDER BY name')
        groups = [dict_from_row(row) for row in c.fetchall()]
        for group in groups:
            c.execute('SELECT position FROM job_grouping_positions WHERE grouping_id = ? ORDER BY position', (group['id'],))
            group['positions'] = [row['position'] for row in c.fetchall()]
        conn.close()
        return jsonify(groups)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/config/position-groupings: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/position-groupings', methods=['POST'])
def create_position_grouping():
    try:
        data = request.get_json() or {}
        name = (data.get('name') or '').strip()
        positions = sorted(set([(p or '').strip() for p in (data.get('positions') or []) if (p or '').strip()]))

        if not name or len(positions) < 2:
            return jsonify({'error': 'Informe um nome e ao menos 2 cargos'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('INSERT INTO job_groupings (name, updated_at) VALUES (?, CURRENT_TIMESTAMP)', (name,))
        grouping_id = c.lastrowid
        for position in positions:
            c.execute('INSERT INTO job_grouping_positions (grouping_id, position) VALUES (?, ?)', (grouping_id, position))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Agrupamento criado'})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/config/position-groupings: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/position-groupings/<int:grouping_id>', methods=['DELETE'])
def delete_position_grouping(grouping_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM job_groupings WHERE id = ?', (grouping_id,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Agrupamento removido'})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE /api/config/position-groupings/{grouping_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/status/rules', methods=['POST'])
def create_or_update_status_rule():
    try:
        data = request.get_json() or {}
        position = (data.get('position') or '').strip()
        green_days = int(data.get('green_days', 7))
        yellow_days = int(data.get('yellow_days', 14))

        if not position:
            return jsonify({'error': 'Cargo é obrigatório'}), 400
        if green_days < 0 or yellow_days <= green_days:
            return jsonify({'error': 'Faixas inválidas: amarelo deve ser maior que verde'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT INTO status_rules (position, green_days, yellow_days, updated_at)
                     VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                     ON CONFLICT(position) DO UPDATE SET
                        green_days = excluded.green_days,
                        yellow_days = excluded.yellow_days,
                        updated_at = CURRENT_TIMESTAMP''',
                  (position, green_days, yellow_days))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Regra por cargo salva'})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/config/status/rules: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/status/rules/<int:rule_id>', methods=['DELETE'])
def delete_status_rule(rule_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM status_rules WHERE id = ?', (rule_id,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Regra removida'})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE /api/config/status/rules/{rule_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/profile', methods=['GET'])
def get_profile_config():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM user_profile WHERE id = 1')
        profile = dict_from_row(c.fetchone())
        conn.close()
        return jsonify(profile or {})
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/config/profile: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/ui', methods=['GET'])
def get_ui_config():
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT key, value FROM app_settings WHERE key IN ("iata_video_path")')
        settings = {row['key']: row['value'] for row in c.fetchall()}
        conn.close()
        return jsonify({'iata_video_path': settings.get('iata_video_path', '/videos/TocaVideo.mp4')})
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/config/ui: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/theme', methods=['GET'])
def get_theme_config():
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT value FROM app_settings WHERE key = "ui_color_theme"')
        row = c.fetchone()
        conn.close()
        theme = row['value'] if row and row['value'] in _VALID_THEMES else 'verde-classico'
        return jsonify({'theme': theme})
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/config/theme: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/theme', methods=['PUT'])
def put_theme_config():
    try:
        data = request.get_json(force=True) or {}
        theme = data.get('theme', 'verde-classico')
        if theme not in _VALID_THEMES:
            return jsonify({'error': 'Tema inválido'}), 400
        conn = get_db(); c = conn.cursor()
        c.execute(
            'INSERT INTO app_settings (key, value) VALUES ("ui_color_theme", ?) '
            'ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP',
            (theme,)
        )
        conn.commit()
        conn.close()
        return jsonify({'theme': theme})
    except Exception as e:
        logger.exception(f'[ERROR] PUT /api/config/theme: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/logs', methods=['GET'])
def get_debug_logs():
    try:
        try:
            lines_limit = int(request.args.get('limit', 500))
        except (TypeError, ValueError):
            lines_limit = 500
        lines_limit = max(50, min(lines_limit, 5000))

        if not LOG_FILE.exists():
            return jsonify({
                'lines': [],
                'path': str(LOG_FILE),
                'total_lines': 0,
                'returned_lines': 0,
                'size': 0
            })

        with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()

        tail = all_lines[-lines_limit:] if len(all_lines) > lines_limit else all_lines
        return jsonify({
            'lines': [line.rstrip('\n') for line in tail],
            'path': str(LOG_FILE),
            'total_lines': len(all_lines),
            'returned_lines': len(tail),
            'size': LOG_FILE.stat().st_size
        })
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/config/logs: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/logs/client', methods=['POST'])
def receive_client_logs():
    try:
        data = request.get_json(silent=True) or {}
        entries = data.get('entries') or []
        if not isinstance(entries, list):
            return jsonify({'error': 'entries deve ser uma lista'}), 400

        accepted = 0
        for entry in entries[:500]:
            if not isinstance(entry, dict):
                continue
            try:
                ts = str(entry.get('ts') or '')
                tag = str(entry.get('tag') or 'client')
                message = str(entry.get('message') or '')
                payload = entry.get('data')
                if payload is None:
                    payload_str = ''
                else:
                    try:
                        payload_str = json.dumps(payload, ensure_ascii=False, default=str)
                    except Exception:
                        payload_str = str(payload)
                _CLIENT_LOGGER.info(
                    f'[client:{tag}] ts={ts} msg={message} data={payload_str}'
                )
                accepted += 1
            except Exception:
                continue

        return jsonify({'received': accepted})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/config/logs/client: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/integrations', methods=['GET'])
def get_integrations_config():
    try:
        settings_map = _load_app_settings_map([
            'tavily_api_key',
            'openrouter_api_key',
            'openrouter_model',
            'openrouter_site_url',
            'openrouter_app_name',
            'itoca_sai_api_key',
            'itoca_sai_template_id',
            'itoca_sai_base_url'
        ])

        tavily_key = (settings_map.get('tavily_api_key') or '').strip() or (os.environ.get('TAVILY_API_KEY', '') or '').strip()
        openrouter_key = (settings_map.get('openrouter_api_key') or '').strip() or (os.environ.get('OPENROUTER_API_KEY', '') or '').strip()
        model = (settings_map.get('openrouter_model') or os.environ.get('OPENROUTER_MODEL', 'stepfun/step-3.5-flash:free')).strip() or 'stepfun/step-3.5-flash:free'
        site_url = (settings_map.get('openrouter_site_url') or os.environ.get('OPENROUTER_SITE_URL', 'http://localhost')).strip() or 'http://localhost'
        app_name = (settings_map.get('openrouter_app_name') or os.environ.get('OPENROUTER_APP_NAME', 'TocaDoCoelho')).strip() or 'TocaDoCoelho'
        itoca_sai_key = (settings_map.get('itoca_sai_api_key') or '').strip() or (os.environ.get('ITOCA_SAI_API_KEY', '') or '').strip()
        itoca_sai_template_id = (settings_map.get('itoca_sai_template_id') or '').strip() or '69ac3c87024adc2d2bdc19f5'
        itoca_sai_base_url = (settings_map.get('itoca_sai_base_url') or '').strip() or 'https://sai-library.saiapplications.com'

        return jsonify({
            'tavily_configured': bool(tavily_key),
            'tavily_key_preview': tavily_key[:6] + '...' if tavily_key else '',
            'openrouter_configured': bool(openrouter_key),
            'openrouter_key_preview': openrouter_key[:9] + '...' if openrouter_key else '',
            'openrouter_model': model,
            'openrouter_site_url': site_url,
            'openrouter_app_name': app_name,
            'itoca_sai_configured': bool(itoca_sai_key),
            'itoca_sai_key_preview': itoca_sai_key[:6] + '...' if itoca_sai_key else '',
            'itoca_sai_template_id': itoca_sai_template_id,
            'itoca_sai_base_url': itoca_sai_base_url
        })
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/config/integrations: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/integrations', methods=['PUT'])
def save_integrations_config():
    try:
        data = request.get_json() or {}
        tavily_api_key = (data.get('tavily_api_key') or '').strip()
        openrouter_api_key = (data.get('openrouter_api_key') or '').strip()
        openrouter_model = (data.get('openrouter_model') or '').strip() or 'stepfun/step-3.5-flash:free'
        openrouter_site_url = (data.get('openrouter_site_url') or '').strip() or 'http://localhost'
        openrouter_app_name = (data.get('openrouter_app_name') or '').strip() or 'TocaDoCoelho'
        itoca_sai_api_key = (data.get('itoca_sai_api_key') or '').strip()
        itoca_sai_template_id = (data.get('itoca_sai_template_id') or '').strip() or '69ac3c87024adc2d2bdc19f5'
        itoca_sai_base_url = (data.get('itoca_sai_base_url') or '').strip() or 'https://sai-library.saiapplications.com'

        if openrouter_api_key:
            key_ok, key_msg = _validate_openrouter_api_key(openrouter_api_key)
            if not key_ok:
                return jsonify({'error': f'OpenRouter inválida: {key_msg}'}), 400

        conn = get_db()
        c = conn.cursor()
        updates = [
            ('tavily_api_key', tavily_api_key),
            ('openrouter_api_key', openrouter_api_key),
            ('openrouter_model', openrouter_model),
            ('openrouter_site_url', openrouter_site_url),
            ('openrouter_app_name', openrouter_app_name),
            ('itoca_sai_api_key', itoca_sai_api_key),
            ('itoca_sai_template_id', itoca_sai_template_id),
            ('itoca_sai_base_url', itoca_sai_base_url)
        ]
        for key, value in updates:
            c.execute(
                'INSERT INTO app_settings (key, value) VALUES (?, ?) '
                'ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP',
                (key, value)
            )
        conn.commit()
        conn.close()

        return jsonify({'message': 'Integrações salvas com sucesso.'})
    except Exception as e:
        logger.exception(f'[ERROR] PUT /api/config/integrations: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/update-source', methods=['GET'])
def get_update_source_config():
    try:
        settings_map = _load_app_settings_map(['update_github_owner', 'update_github_repo', 'update_github_token'])
        owner = (settings_map.get('update_github_owner') or DEFAULT_GITHUB_OWNER or '').strip()
        repo = (settings_map.get('update_github_repo') or DEFAULT_GITHUB_REPO or '').strip()
        token = (settings_map.get('update_github_token') or '').strip() or (os.environ.get('TOCA_UPDATE_GITHUB_TOKEN', '') or '').strip()
        return jsonify({
            'current_version': APP_VERSION,
            'github_owner': owner,
            'github_repo': repo,
            'github_token_configured': bool(token),
            'github_token_preview': (token[:7] + '...') if token else '',
            'configured': bool(owner and repo)
        })
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/config/update-source: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/update-source', methods=['PUT'])
def save_update_source_config():
    try:
        data = request.get_json() or {}
        owner = (data.get('github_owner') or '').strip()
        repo = (data.get('github_repo') or '').strip()
        token = (data.get('github_token') or '').strip()

        conn = get_db()
        c = conn.cursor()
        updates = [
            ('update_github_owner', owner),
            ('update_github_repo', repo)
        ]
        # Só grava o token quando um valor é enviado, para não apagá-lo ao salvar owner/repo.
        if token:
            updates.append(('update_github_token', token))
        for key, value in updates:
            c.execute(
                'INSERT INTO app_settings (key, value) VALUES (?, ?) '
                'ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP',
                (key, value)
            )
        conn.commit()
        conn.close()

        return jsonify({'message': 'Fonte de atualização salva com sucesso.'})
    except Exception as e:
        logger.exception(f'[ERROR] PUT /api/config/update-source: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/check-updates', methods=['GET'])
def check_updates():
    try:
        settings_map = _load_app_settings_map(['update_github_owner', 'update_github_repo'])
        owner = (settings_map.get('update_github_owner') or DEFAULT_GITHUB_OWNER or '').strip()
        repo = (settings_map.get('update_github_repo') or DEFAULT_GITHUB_REPO or '').strip()

        if not owner or not repo:
            return jsonify({
                'update_available': False,
                'configured': False,
                'current_version': APP_VERSION,
                'message': 'Configure GitHub Owner e Repositório em Configurações para verificar updates.'
            }), 400

        github_token = _resolve_setting('update_github_token', 'TOCA_UPDATE_GITHUB_TOKEN')
        api_headers = {
            'Accept': 'application/vnd.github+json',
            'User-Agent': 'TocaDoCoelho-Updater'
        }
        if github_token:
            api_headers['Authorization'] = f'Bearer {github_token}'

        api_url = f'https://api.github.com/repos/{owner}/{repo}/releases/latest'
        req = urllib.request.Request(api_url, headers=api_headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode('utf-8'))

        latest_tag = (payload.get('tag_name') or '').strip()
        latest_version = _normalize_version(latest_tag)
        current_version = _normalize_version(APP_VERSION)

        if not latest_version:
            return jsonify({'error': 'Tag da release mais recente está vazia no GitHub.'}), 502

        update_available = _version_key(latest_version) > _version_key(current_version)

        # Localiza o instalador (.exe) anexado como asset da release — usado pela
        # atualização automática para baixar e executar a nova versão.
        installer_url = ''
        installer_name = ''
        installer_size = 0
        for asset in (payload.get('assets') or []):
            asset_name = (asset.get('name') or '').strip()
            if asset_name.lower().endswith('.exe'):
                installer_url = (asset.get('browser_download_url') or '').strip()
                installer_name = asset_name
                installer_size = int(asset.get('size') or 0)
                break

        branch = DEFAULT_GITHUB_BRANCH or 'main'
        commits_ahead = None
        commits_ahead_list = []
        commits_check_ok = False
        commits_check_error = ''
        branch_html_url = f'https://github.com/{owner}/{repo}/tree/{branch}'
        compare_html_url = ''
        try:
            compare_url = f'https://api.github.com/repos/{owner}/{repo}/compare/{latest_tag}...{branch}'
            compare_req = urllib.request.Request(compare_url, headers=api_headers)
            with urllib.request.urlopen(compare_req, timeout=10) as compare_response:
                compare_payload = json.loads(compare_response.read().decode('utf-8'))
            commits_ahead = int(compare_payload.get('ahead_by') or 0)
            compare_html_url = compare_payload.get('html_url') or ''
            for commit_entry in (compare_payload.get('commits') or [])[-10:]:
                sha = (commit_entry.get('sha') or '')[:7]
                message = ((commit_entry.get('commit') or {}).get('message') or '').splitlines()[0]
                commits_ahead_list.append({'sha': sha, 'message': message})
            commits_check_ok = True
        except urllib.error.HTTPError as compare_error:
            if compare_error.code == 403:
                commits_check_error = ('Limite da API do GitHub atingido. Configure um Token do GitHub '
                                       'em Configurações para evitar isso.')
            elif compare_error.code == 401:
                commits_check_error = 'Token do GitHub inválido ou expirado. Revise-o em Configurações.'
            else:
                commits_check_error = f'Falha ao comparar com a branch (HTTP {compare_error.code}).'
            logger.warning('[Update] Falha ao comparar tag %s com branch %s: %s', latest_tag, branch, compare_error)
        except Exception as compare_error:
            commits_check_error = 'Não foi possível verificar os commits da branch (falha de rede ou GitHub indisponível).'
            logger.warning('[Update] Falha ao comparar tag %s com branch %s: %s', latest_tag, branch, compare_error)

        return jsonify({
            'configured': True,
            'github_owner': owner,
            'github_repo': repo,
            'github_branch': branch,
            'current_version': current_version,
            'latest_version': latest_version,
            'latest_tag': latest_tag,
            'update_available': update_available,
            'release_name': payload.get('name') or latest_tag,
            'release_notes': payload.get('body') or '',
            'html_url': payload.get('html_url') or '',
            'published_at': payload.get('published_at'),
            'commits_ahead': commits_ahead,
            'commits_ahead_list': commits_ahead_list,
            'commits_check_ok': commits_check_ok,
            'commits_check_error': commits_check_error,
            'installer_url': installer_url,
            'installer_name': installer_name,
            'installer_size': installer_size,
            'can_auto_install': bool(installer_url),
            'branch_html_url': branch_html_url,
            'compare_html_url': compare_html_url
        })
    except urllib.error.HTTPError as e:
        logger.exception(f'[ERROR] GET /api/config/check-updates (HTTP): {e}')
        if e.code == 404:
            return jsonify({'error': 'Nenhuma release encontrada nesse repositório ou repositório inválido.'}), 404
        if e.code == 401:
            return jsonify({'error': 'Token do GitHub inválido ou expirado. Revise-o em Configurações.'}), 401
        if e.code == 403:
            return jsonify({'error': 'Limite da API do GitHub atingido. Configure um Token do GitHub em Configurações para evitar isso.'}), 429
        return jsonify({'error': f'Falha ao consultar GitHub Releases (HTTP {e.code}).'}), 502
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/config/check-updates: {e}')
        return jsonify({'error': f'Erro ao verificar updates: {e}'}), 500


@app.route('/api/config/startup-update-check', methods=['GET'])
def startup_update_check():
    """Verificação silenciosa de update ao iniciar o app. Respeita o snooze de 5 dias."""
    try:
        settings_map = _load_app_settings_map(['update_github_owner', 'update_github_repo', 'update_snooze_until'])
        snooze_until = (settings_map.get('update_snooze_until') or '').strip()
        if snooze_until:
            try:
                snooze_dt = datetime.fromisoformat(snooze_until)
                if datetime.now() < snooze_dt:
                    return jsonify({'snoozed': True, 'snooze_until': snooze_until})
            except Exception as e:
                logger.debug(f'[startup_update_check] exceção ignorada: {e}')

        owner = (settings_map.get('update_github_owner') or DEFAULT_GITHUB_OWNER or '').strip()
        repo = (settings_map.get('update_github_repo') or DEFAULT_GITHUB_REPO or '').strip()
        if not owner or not repo:
            return jsonify({'update_available': False, 'configured': False})

        github_token = _resolve_setting('update_github_token', 'TOCA_UPDATE_GITHUB_TOKEN')
        api_headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'TocaDoCoelho-Updater'}
        if github_token:
            api_headers['Authorization'] = f'Bearer {github_token}'

        api_url = f'https://api.github.com/repos/{owner}/{repo}/releases/latest'
        req = urllib.request.Request(api_url, headers=api_headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode('utf-8'))

        latest_tag = (payload.get('tag_name') or '').strip()
        latest_version = _normalize_version(latest_tag)
        current_version = _normalize_version(APP_VERSION)

        if not latest_version:
            return jsonify({'update_available': False})

        update_available = _version_key(latest_version) > _version_key(current_version)
        if not update_available:
            return jsonify({'update_available': False, 'current_version': current_version})

        installer_url = ''
        installer_name = ''
        installer_size = 0
        for asset in (payload.get('assets') or []):
            asset_name = (asset.get('name') or '').strip()
            if asset_name.lower().endswith('.exe'):
                installer_url = (asset.get('browser_download_url') or '').strip()
                installer_name = asset_name
                installer_size = int(asset.get('size') or 0)
                break

        return jsonify({
            'update_available': True,
            'current_version': current_version,
            'latest_version': latest_version,
            'latest_tag': latest_tag,
            'release_name': payload.get('name') or latest_tag,
            'release_notes': payload.get('body') or '',
            'html_url': payload.get('html_url') or '',
            'published_at': payload.get('published_at'),
            'installer_url': installer_url,
            'installer_name': installer_name,
            'installer_size': installer_size,
            'can_auto_install': bool(installer_url),
        })
    except Exception as e:
        logger.warning('[startup-update-check] Falha silenciosa: %s', e)
        return jsonify({'update_available': False})


@app.route('/api/config/snooze-update', methods=['POST'])
def snooze_update():
    """Salva snooze de 5 dias para a notificação de update."""
    try:
        snooze_until = (datetime.now() + timedelta(days=5)).isoformat()
        db = get_db()
        db.execute("INSERT OR REPLACE INTO app_settings (key, value, updated_at) VALUES ('update_snooze_until', ?, CURRENT_TIMESTAMP)", (snooze_until,))
        db.commit()
        return jsonify({'ok': True, 'snooze_until': snooze_until})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/config/snooze-update: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/download-update', methods=['POST'])
def download_update():
    try:
        data = request.get_json() or {}
        url = (data.get('installer_url') or '').strip()
        name = (data.get('installer_name') or '').strip()
        if not url or not url.lower().startswith('https://'):
            return jsonify({'error': 'URL do instalador inválida.'}), 400

        task_id = uuid.uuid4().hex
        _bg_task_set(task_id, {'status': 'processing', 'step': 'Iniciando download...', 'progress': 1})
        threading.Thread(target=_download_update_async, args=(task_id, url, name), daemon=True).start()
        return jsonify({'task_id': task_id}), 202
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/config/download-update: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/update-tasks/<task_id>', methods=['GET'])
def get_update_task(task_id):
    return jsonify(_bg_task_get(task_id))


@app.route('/api/config/install-update', methods=['POST'])
def install_update():
    try:
        import subprocess

        data = request.get_json() or {}
        installer_path = (data.get('installer_path') or '').strip()
        if not installer_path:
            return jsonify({'error': 'Caminho do instalador não informado.'}), 400

        installer = Path(installer_path).resolve()
        # Segurança: só executa um .exe que está dentro da pasta de updates.
        if (installer.parent != UPDATE_DOWNLOAD_DIR.resolve()
                or installer.suffix.lower() != '.exe'
                or not installer.is_file()):
            return jsonify({'error': 'Instalador inválido ou não encontrado.'}), 400

        if sys.platform == 'win32':
            # NUNCA usar o verbo 'runas' aqui: o instalador é per-user
            # (RequestExecutionLevel user) e não precisa de elevação. Em contas sem
            # admin, o prompt UAC do 'runas' pedia credenciais de OUTRA conta e o
            # instalador rodava como ela — registro, atalhos e banco iam para o
            # perfil errado (o app "sumia" de instalados e abria com banco vazio).
            import ctypes
            ret = ctypes.windll.shell32.ShellExecuteW(
                None,           # hwnd
                'open',         # verbo — executa como o usuário atual, sem elevação
                str(installer), # executável
                None,           # parâmetros
                None,           # diretório de trabalho (None = diretório do executável)
                1,              # SW_SHOWNORMAL
            )
            # ShellExecuteW retorna > 32 em sucesso
            if ret <= 32:
                raise OSError(f'ShellExecuteW falhou com código {ret}')
        else:
            subprocess.Popen([str(installer)], close_fds=True)

        # Encerra o app logo após responder, liberando os arquivos para o instalador.
        def _shutdown():
            time.sleep(2)
            os._exit(0)
        threading.Thread(target=_shutdown, daemon=True).start()

        return jsonify({
            'message': 'Instalador iniciado. O aplicativo será encerrado para concluir a atualização.'
        }), 202
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/config/install-update: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/startup', methods=['GET'])
def get_startup_config():
    if sys.platform != 'win32':
        return jsonify({'enabled': False, 'supported': False})
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Run',
            0, winreg.KEY_READ
        )
        try:
            winreg.QueryValueEx(key, 'TocaDoCoelho')
            enabled = True
        except FileNotFoundError:
            enabled = False
        finally:
            winreg.CloseKey(key)
        return jsonify({'enabled': enabled, 'supported': True})
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/config/startup: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/startup', methods=['POST'])
def set_startup_config():
    if sys.platform != 'win32':
        return jsonify({'error': 'Não suportado nesta plataforma.'}), 400
    try:
        data = request.get_json() or {}
        enable = bool(data.get('enabled', False))
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Run',
            0, winreg.KEY_SET_VALUE
        )
        if enable:
            exe_path = str(Path(sys.executable).resolve())
            winreg.SetValueEx(key, 'TocaDoCoelho', 0, winreg.REG_SZ, f'"{exe_path}"')
        else:
            try:
                winreg.DeleteValue(key, 'TocaDoCoelho')
            except Exception as e:
                logger.debug(f'[set_startup_config] exceção ignorada: {e}')
        winreg.CloseKey(key)
        return jsonify({'enabled': enable, 'message': 'Configuração salva com sucesso.'})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/config/startup: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/profile', methods=['POST'])
def save_profile_config():
    try:
        full_name = request.form.get('full_name', '').strip()
        nickname = request.form.get('nickname', '').strip()
        position = request.form.get('position', '').strip()
        email = request.form.get('email', '').strip()
        phone = normalize_phone(request.form.get('phone', '').strip())
        boss_name = request.form.get('boss_name', '').strip() or None
        boss_email = request.form.get('boss_email', '').strip() or None

        if not full_name or not nickname or not position or not email or not phone:
            return jsonify({'error': 'Nome completo, apelido, cargo, email e telefone são obrigatórios'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT photo_url FROM user_profile WHERE id = 1')
        row = c.fetchone()
        photo_url = row['photo_url'] if row else None

        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename:
                filename = f'profile-{uuid.uuid4().hex}.jpg'
                filepath = UPLOAD_DIR / filename
                _save_avatar_photo(file, filepath)
                photo_url = f'/uploads/{filename}'

        if not photo_url:
            return jsonify({'error': 'Foto é obrigatória'}), 400

        c.execute('''INSERT INTO user_profile (id, full_name, nickname, position, email, phone, photo_url, boss_name, boss_email, updated_at)
                     VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                     ON CONFLICT(id) DO UPDATE SET
                        full_name = excluded.full_name,
                        nickname = excluded.nickname,
                        position = excluded.position,
                        email = excluded.email,
                        phone = excluded.phone,
                        photo_url = excluded.photo_url,
                        boss_name = excluded.boss_name,
                        boss_email = excluded.boss_email,
                        updated_at = CURRENT_TIMESTAMP''',
                  (full_name, nickname, position, email, phone, photo_url, boss_name, boss_email))
        conn.commit()
        conn.close()

        return jsonify({'message': 'Perfil salvo'})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/config/profile: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/profile', methods=['DELETE'])
def delete_profile_config():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM user_profile WHERE id = 1')
        conn.commit()
        conn.close()
        return jsonify({'message': 'Usuário excluído com sucesso'})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE /api/config/profile: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/templates', methods=['GET'])
def list_message_templates():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM message_templates ORDER BY title COLLATE NOCASE')
        items = [dict_from_row(row) for row in c.fetchall()]
        conn.close()
        return jsonify(items)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/config/templates: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/templates', methods=['POST'])
def create_message_template():
    try:
        data = request.get_json() or {}
        title = (data.get('title') or '').strip()
        description = (data.get('description') or '').strip()
        available_whatsapp = 1 if data.get('available_whatsapp', True) else 0
        available_email = 1 if data.get('available_email', True) else 0
        if not title or not description:
            return jsonify({'error': 'Título e descritivo são obrigatórios'}), 400
        conn = get_db(); c = conn.cursor()
        c.execute('''INSERT INTO message_templates (title, description, available_whatsapp, available_email, updated_at)
                     VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)''', (title, description, available_whatsapp, available_email))
        template_id = c.lastrowid
        conn.commit()
        c.execute('SELECT * FROM message_templates WHERE id = ?', (template_id,))
        item = dict_from_row(c.fetchone())
        conn.close()
        return jsonify(item), 201
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/config/templates: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/templates/<int:template_id>', methods=['PUT'])
def update_message_template(template_id):
    try:
        data = request.get_json() or {}
        title = (data.get('title') or '').strip()
        description = (data.get('description') or '').strip()
        available_whatsapp = 1 if data.get('available_whatsapp', True) else 0
        available_email = 1 if data.get('available_email', True) else 0
        if not title or not description:
            return jsonify({'error': 'Título e descritivo são obrigatórios'}), 400
        conn = get_db(); c = conn.cursor()
        c.execute('''UPDATE message_templates
                     SET title = ?, description = ?, available_whatsapp = ?, available_email = ?, updated_at = CURRENT_TIMESTAMP
                     WHERE id = ?''', (title, description, available_whatsapp, available_email, template_id))
        conn.commit()
        c.execute('SELECT * FROM message_templates WHERE id = ?', (template_id,))
        item = dict_from_row(c.fetchone())
        conn.close()
        return jsonify(item or {'message': 'Atualizado'})
    except Exception as e:
        logger.exception(f'[ERROR] PUT /api/config/templates/{template_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/templates/<int:template_id>', methods=['DELETE'])
def delete_message_template(template_id):
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('DELETE FROM message_templates WHERE id = ?', (template_id,))
        conn.commit(); conn.close()
        return jsonify({'message': 'Modelo removido'})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE /api/config/templates/{template_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/system/config', methods=['GET'])
def get_system_config():
    return jsonify({
        'env': os.environ.get('TOCA_ENV', 'production'),
        'version': APP_VERSION
    })


# ===========================================================================
# Primeiro acesso pós-instalação + aviso de atualização da extensão
# (ajustes pós-roadmap)
# ===========================================================================

def _extension_bundled_version():
    """Versão da extensão AutoToca empacotada com este build (manifest.json)."""
    try:
        manifest_path = Path(app.static_folder) / 'autotoca-extension' / 'autotoca-chrome-extension' / 'manifest.json'
        with open(manifest_path, encoding='utf-8') as f:
            return (json.load(f).get('version') or '').strip()
    except Exception as e:
        logger.debug(f'[Extensao] manifest indisponível: {e}')
        return ''


@app.route('/api/config/first-run', methods=['GET'])
def config_first_run_status():
    """Primeira abertura após INSTALAÇÃO (não update): sem cadastro de usuário
    e sem marca de primeiro acesso — o frontend leva direto para Configurações."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM user_profile')
        has_profile = c.fetchone()[0] > 0
        conn.close()
        seen = bool(_resolve_setting('first_run_seen', ''))
        return jsonify({'first_run': (not has_profile) and (not seen)})
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/config/first-run: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/first-run/seen', methods=['POST'])
def config_first_run_seen():
    try:
        _save_app_setting('first_run_seen', datetime.now().isoformat(timespec='seconds'))
        # Instalação nova: a extensão empacotada já é a atual — não avisar update
        version = _extension_bundled_version()
        if version:
            _save_app_setting('extension_version_seen', version)
        return jsonify({'ok': True})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/config/first-run/seen: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/extension/update-status', methods=['GET'])
def extension_update_status():
    """Após um update do app que trouxe extensão nova, avisa o usuário para
    baixar e reinstalar o plugin do navegador."""
    try:
        current = _extension_bundled_version()
        seen = _resolve_setting('extension_version_seen', '')
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM user_profile')
        has_profile = c.fetchone()[0] > 0
        conn.close()
        first_run = (not has_profile) and (not _resolve_setting('first_run_seen', ''))
        update_available = bool(current) and (seen != current) and not first_run
        # Quando o auto-update local está ativo (Windows + .crx assinado empacotado),
        # o navegador atualiza a extensão sozinho — não há por que pedir download manual.
        auto_update = (os.name == 'nt') and ext_autoupdate.is_available()
        if auto_update:
            update_available = False
        return jsonify({
            'current': current,
            'seen': seen or None,
            'update_available': update_available,
            'auto_update': auto_update,
            'download_url': '/autotoca-extension/autotoca-chrome-extension.zip',
        })
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/extension/update-status: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/ext/updates.xml', methods=['GET'])
def extension_update_manifest():
    """Manifesto Omaha lido pelo Chrome/Edge para auto-atualizar a extensão AutoToca.
    Servido localmente pelo próprio app (ver integrations/ext_autoupdate.py)."""
    try:
        if not ext_autoupdate.is_available():
            return Response('extensão assinada indisponível neste build', status=404)
        crx_url = request.url_root.rstrip('/') + '/ext/' + ext_autoupdate.CRX_FILENAME
        xml = ext_autoupdate.updates_xml(crx_url)
        return Response(xml, mimetype='application/xml')
    except Exception as e:
        logger.exception(f'[ERROR] GET /ext/updates.xml: {e}')
        return Response(str(e), status=500)


@app.route('/ext/autotoca-helper.crx', methods=['GET'])
def extension_crx():
    """Entrega o pacote .crx3 assinado para o navegador instalar/atualizar."""
    try:
        if not ext_autoupdate.CRX_PATH.exists():
            return Response('pacote .crx indisponível', status=404)
        return send_file(
            str(ext_autoupdate.CRX_PATH),
            mimetype='application/x-chrome-extension',
            as_attachment=False,
            download_name=ext_autoupdate.CRX_FILENAME,
        )
    except Exception as e:
        logger.exception(f'[ERROR] GET /ext/autotoca-helper.crx: {e}')
        return Response(str(e), status=500)


@app.route('/api/extension/update-status/seen', methods=['POST'])
def extension_update_seen():
    try:
        version = _extension_bundled_version()
        _save_app_setting('extension_version_seen', version or 'desconhecida')
        return jsonify({'ok': True, 'version': version})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/extension/update-status/seen: {e}')
        return jsonify({'error': str(e)}), 500
