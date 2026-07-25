# -*- coding: utf-8 -*-
# Rotas do domínio "campaigns" (Bloco 3 — modularização).
# Este arquivo é executado no namespace de app.py por _load_route_modules():
# tem acesso a todos os helpers/globals de app.py e registra as rotas no
# mesmo objeto Flask `app`, com URLs idênticas às originais.

@app.route('/api/campaigns/selectable-accounts', methods=['GET'])
def campaign_selectable_accounts():
    try:
        conn = get_db()
        c = conn.cursor()
        _vw, _vp = visible_where('accounts', alias='a')
        c.execute(
            f"""SELECT a.id, a.name, a.logo_url, a.is_target, a.sector,
                      (SELECT COUNT(*) FROM clients cl
                        WHERE lower(trim(cl.company)) = lower(trim(a.name)) AND COALESCE(cl.is_archived,0)=0) AS contact_count
               FROM accounts a WHERE {_vw} ORDER BY a.is_target DESC, a.name""", _vp
        )
        rows = [dict_from_row(r) for r in c.fetchall()]
        conn.close()
        return jsonify(rows)
    except Exception as e:
        logger.exception(f'[Campaign] selectable-accounts: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/campaigns/analyze', methods=['POST'])
def campaign_analyze():
    data = request.get_json() or {}
    challenge = (data.get('challenge_text') or '').strip()
    if not challenge:
        return jsonify({'error': 'Descreva o desafio comercial.'}), 400
    task_id = uuid.uuid4().hex
    _bg_task_set(task_id, {'status': 'processing', 'step': 'Entendendo o desafio...', 'progress': 10})

    def _run():
        try:
            _bg_task_set(task_id, {'step': 'Cruzando com portfólio e contatos...', 'progress': 45})
            result = _campaign_analyze_core(challenge)
            _bg_task_set(task_id, {'step': 'Concluído!', 'progress': 100, 'status': 'done', 'result': result})
        except Exception as e:
            logger.exception(f'[Campaign][analyze] {e}')
            _bg_task_set(task_id, {'status': 'error', 'error': str(e)})
        finally:
            _bg_task_cleanup(task_id)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'task_id': task_id}), 202


@app.route('/api/campaigns/generate', methods=['POST'])
def campaign_generate():
    try:
        data = request.get_json() or {}
        challenge = (data.get('challenge_text') or '').strip()
        if not challenge:
            return jsonify({'error': 'Desafio é obrigatório.'}), 400
        title = (data.get('title') or '').strip() or 'Campanha Ofensiva'
        start_date = (data.get('start_date') or '').strip() or datetime.now().strftime('%Y-%m-%d')
        try:
            capacity = max(1, min(50, int(data.get('weekly_capacity') or 5)))
        except Exception:
            capacity = 5
        mode = (data.get('account_mode') or 'targets').strip()
        raw_account_ids = data.get('account_ids') or []

        conn = get_db()
        c = conn.cursor()
        if mode == 'manual' and raw_account_ids:
            ids = [int(i) for i in raw_account_ids if str(i).isdigit()]
            if ids:  # só contas que o usuário enxerga
                _vw, _vp = visible_where('accounts', alias='a')
                _qs = ','.join('?' * len(ids))
                c.execute(f'SELECT a.id FROM accounts a WHERE a.id IN ({_qs}) AND {_vw}', ids + _vp)
                ids = [r['id'] for r in c.fetchall()]
        else:
            _vw, _vp = visible_where('accounts', alias='a')
            c.execute(f'SELECT a.id FROM accounts a WHERE a.is_target = 1 AND {_vw}', _vp)
            ids = [r['id'] for r in c.fetchall()]
        conn.close()
        if not ids:
            return jsonify({'error': 'Nenhuma conta selecionada. Marque contas como target ou selecione manualmente.'}), 400

        payload = {
            'title': title,
            'challenge_text': challenge,
            'areas': data.get('areas') or [],
            'decisores': data.get('decisores') or [],
            'offer_ids': [int(i) for i in (data.get('offer_ids') or []) if str(i).isdigit()],
            'start_date': start_date,
            'weekly_capacity': capacity,
            'account_ids': ids,
            'llm_source': data.get('llm_source', ''),
            'summary': data.get('summary', '') or data.get('entendimento', ''),
            'portfolio_note': data.get('portfolio_note', ''),
            'owner_id': _acl_owner_for_insert(),  # capturado no request p/ a thread
        }
        task_id = uuid.uuid4().hex
        _bg_task_set(task_id, {'status': 'processing', 'step': 'Montando plano de ação...', 'progress': 15})

        def _run():
            try:
                _bg_task_set(task_id, {'step': 'Classificando contas (A/B/C/D)...', 'progress': 40})

                def _progress(pct, step):
                    _bg_task_set(task_id, {'progress': max(40, min(95, int(pct))), 'step': step})

                cid = _campaign_generate_core(payload, progress_cb=_progress)
                _bg_task_set(task_id, {'step': 'Concluído!', 'progress': 100, 'status': 'done', 'result': {'campaign_id': cid}})
            except Exception as e:
                logger.exception(f'[Campaign][generate] {e}')
                _bg_task_set(task_id, {'status': 'error', 'error': str(e)})
            finally:
                _bg_task_cleanup(task_id)

        threading.Thread(target=_run, daemon=True).start()
        return jsonify({'task_id': task_id}), 202
    except Exception as e:
        logger.exception(f'[Campaign] generate start: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/campaigns', methods=['GET'])
def campaign_list():
    try:
        conn = get_db()
        c = conn.cursor()
        _vw, _vp = visible_where('campaigns')
        c.execute(f'SELECT * FROM campaigns WHERE {_vw} ORDER BY datetime(created_at) DESC, id DESC', _vp)
        camps = [dict_from_row(r) for r in c.fetchall()]
        for camp in camps:
            c.execute('SELECT COUNT(*) AS n FROM campaign_accounts WHERE campaign_id = ?', (camp['id'],))
            camp['accounts_count'] = c.fetchone()['n'] or 0
            c.execute(
                """SELECT COUNT(*) total, SUM(CASE WHEN ca.status='done' THEN 1 ELSE 0 END) done
                   FROM campaign_actions ca
                   JOIN campaign_accounts cc ON cc.id = ca.campaign_account_id
                   WHERE cc.campaign_id = ?""",
                (camp['id'],)
            )
            row = c.fetchone()
            total = row['total'] or 0
            done = row['done'] or 0
            camp['progress'] = round(100 * done / total) if total else 0
            camp['areas'] = json.loads(camp.get('areas_json') or '[]')
        conn.close()
        return jsonify(camps)
    except Exception as e:
        logger.exception(f'[Campaign] list: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/campaigns/<int:cid>', methods=['GET'])
def campaign_detail(cid):
    try:
        conn = get_db()
        c = conn.cursor()
        if not can_read('campaigns', cid, c):
            conn.close()
            return jsonify({'error': 'Campanha não encontrada.'}), 404
        data = _campaign_serialize(c, cid)
        conn.close()
        if not data:
            return jsonify({'error': 'Campanha não encontrada.'}), 404
        return jsonify(data)
    except Exception as e:
        logger.exception(f'[Campaign] detail {cid}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/campaigns/<int:cid>', methods=['PUT'])
def campaign_update(cid):
    try:
        data = request.get_json() or {}
        fields, vals = [], []
        if 'title' in data:
            fields.append('title=?')
            vals.append((data.get('title') or '').strip() or 'Campanha Ofensiva')
        if 'status' in data:
            fields.append('status=?')
            vals.append((data.get('status') or 'Ativo').strip())
        if 'objective_text' in data:
            fields.append('objective_text=?')
            vals.append((data.get('objective_text') or '').strip())
        if not fields:
            return jsonify({'error': 'Nada para atualizar.'}), 400
        fields.append('updated_at=CURRENT_TIMESTAMP')
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM campaigns WHERE id = ?', (cid,))
        if not c.fetchone() or not can_read('campaigns', cid, c):
            conn.close()
            return jsonify({'error': 'Campanha não encontrada.'}), 404
        if not can_write('campaigns', cid, c):
            conn.close()
            return jsonify({'error': 'Sem permissão para editar esta campanha.', 'error_type': 'forbidden'}), 403
        c.execute(f"UPDATE campaigns SET {', '.join(fields)} WHERE id = ?", (*vals, cid))
        conn.commit()
        data = _campaign_serialize(c, cid)
        conn.close()
        return jsonify(data)
    except Exception as e:
        logger.exception(f'[Campaign] update {cid}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/campaigns/<int:cid>', methods=['DELETE'])
def campaign_delete(cid):
    try:
        conn = get_db()
        c = conn.cursor()
        if not can_read('campaigns', cid, c):
            conn.close()
            return jsonify({'error': 'Campanha não encontrada.'}), 404
        if not can_write('campaigns', cid, c):
            conn.close()
            return jsonify({'error': 'Sem permissão para excluir esta campanha.', 'error_type': 'forbidden'}), 403
        c.execute('SELECT id FROM campaign_accounts WHERE campaign_id = ?', (cid,))
        ca_ids = [r['id'] for r in c.fetchall()]
        if ca_ids:
            qs = ','.join('?' * len(ca_ids))
            c.execute(f'SELECT id FROM campaign_actions WHERE campaign_account_id IN ({qs})', ca_ids)
            act_ids = [r['id'] for r in c.fetchall()]
            if act_ids:
                qs2 = ','.join('?' * len(act_ids))
                c.execute(f'DELETE FROM campaign_action_logs WHERE action_id IN ({qs2})', act_ids)
                c.execute(f'DELETE FROM campaign_actions WHERE id IN ({qs2})', act_ids)
            c.execute(f'DELETE FROM campaign_accounts WHERE id IN ({qs})', ca_ids)
        c.execute('DELETE FROM campaigns WHERE id = ?', (cid,))
        deleted = c.rowcount
        conn.commit()
        conn.close()
        if not deleted:
            return jsonify({'error': 'Campanha não encontrada.'}), 404
        return jsonify({'success': True})
    except Exception as e:
        logger.exception(f'[Campaign] delete {cid}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/campaigns/<int:cid>/regenerate', methods=['POST'])
def campaign_regenerate(cid):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM campaigns WHERE id = ?', (cid,))
        exists = c.fetchone()
        _ok_read = can_read('campaigns', cid, c)
        _ok_write = can_write('campaigns', cid, c)
        conn.close()
        if not exists or not _ok_read:
            return jsonify({'error': 'Campanha não encontrada.'}), 404
        if not _ok_write:
            return jsonify({'error': 'Sem permissão para regenerar esta campanha.', 'error_type': 'forbidden'}), 403
        task_id = uuid.uuid4().hex
        _bg_task_set(task_id, {'status': 'processing', 'step': 'Reanalisando portfólio e mapeamento...', 'progress': 25})

        def _run():
            try:
                _bg_task_set(task_id, {'step': 'Reclassificando contas...', 'progress': 40})

                def _progress(pct, step):
                    _bg_task_set(task_id, {'progress': max(40, min(95, int(pct))), 'step': step})

                _campaign_regenerate_core(cid, progress_cb=_progress)
                _bg_task_set(task_id, {'step': 'Concluído!', 'progress': 100, 'status': 'done', 'result': {'campaign_id': cid}})
            except Exception as e:
                logger.exception(f'[Campaign][regenerate] {e}')
                _bg_task_set(task_id, {'status': 'error', 'error': str(e)})
            finally:
                _bg_task_cleanup(task_id)

        threading.Thread(target=_run, daemon=True).start()
        return jsonify({'task_id': task_id}), 202
    except Exception as e:
        logger.exception(f'[Campaign] regenerate start {cid}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/campaigns/actions/<int:aid>', methods=['PATCH'])
def campaign_action_update(aid):
    try:
        data = request.get_json() or {}
        status = (data.get('status') or '').strip()
        if status not in ('pending', 'in_progress', 'done'):
            return jsonify({'error': 'Status inválido.'}), 400
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM campaign_actions WHERE id = ?', (aid,))
        if not c.fetchone() or not can_read('campaign_actions', aid, c):
            conn.close()
            return jsonify({'error': 'Ação não encontrada.'}), 404
        if not can_write('campaign_actions', aid, c):
            conn.close()
            return jsonify({'error': 'Sem permissão para editar esta ação.', 'error_type': 'forbidden'}), 403
        if status == 'done':
            c.execute('UPDATE campaign_actions SET status=?, completed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?', (status, aid))
        else:
            c.execute('UPDATE campaign_actions SET status=?, completed_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?', (status, aid))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'status': status})
    except Exception as e:
        logger.exception(f'[Campaign] action update {aid}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/campaigns/actions/<int:aid>/logs', methods=['POST'])
def campaign_action_log(aid):
    try:
        data = request.get_json() or {}
        text = (data.get('log_text') or '').strip()
        if not text:
            return jsonify({'error': 'Escreva um update.'}), 400
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM campaign_actions WHERE id = ?', (aid,))
        if not c.fetchone() or not can_read('campaign_actions', aid, c):
            conn.close()
            return jsonify({'error': 'Ação não encontrada.'}), 404
        if not can_write('campaign_actions', aid, c):
            conn.close()
            return jsonify({'error': 'Sem permissão para editar esta ação.', 'error_type': 'forbidden'}), 403
        c.execute("INSERT INTO campaign_action_logs (action_id, log_text, log_type) VALUES (?,?, 'user')", (aid, text))
        log_id = c.lastrowid
        c.execute('UPDATE campaign_actions SET updated_at=CURRENT_TIMESTAMP WHERE id=?', (aid,))
        conn.commit()
        c.execute('SELECT * FROM campaign_action_logs WHERE id = ?', (log_id,))
        log = dict_from_row(c.fetchone())
        conn.close()
        return jsonify(log)
    except Exception as e:
        logger.exception(f'[Campaign] action log {aid}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/campaigns/logs/<int:lid>', methods=['PATCH'])
def campaign_log_update(lid):
    try:
        data = request.get_json() or {}
        text = (data.get('log_text') or '').strip()
        if not text:
            return jsonify({'error': 'Escreva um update.'}), 400
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM campaign_action_logs WHERE id = ?', (lid,))
        log = dict_from_row(c.fetchone())
        if not log or not can_read('campaign_action_logs', lid, c):
            conn.close()
            return jsonify({'error': 'Update não encontrado.'}), 404
        if not can_write('campaign_action_logs', lid, c):
            conn.close()
            return jsonify({'error': 'Sem permissão para editar este update.', 'error_type': 'forbidden'}), 403
        if (log.get('log_type') or 'user') != 'user':
            conn.close()
            return jsonify({'error': 'Apenas updates manuais podem ser editados.'}), 400
        c.execute('UPDATE campaign_action_logs SET log_text=? WHERE id=?', (text, lid))
        c.execute('UPDATE campaign_actions SET updated_at=CURRENT_TIMESTAMP WHERE id=?', (log['action_id'],))
        conn.commit()
        c.execute('SELECT * FROM campaign_action_logs WHERE id = ?', (lid,))
        updated = dict_from_row(c.fetchone())
        conn.close()
        return jsonify(updated)
    except Exception as e:
        logger.exception(f'[Campaign] log update {lid}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/campaigns/logs/<int:lid>', methods=['DELETE'])
def campaign_log_delete(lid):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM campaign_action_logs WHERE id = ?', (lid,))
        log = dict_from_row(c.fetchone())
        if not log or not can_read('campaign_action_logs', lid, c):
            conn.close()
            return jsonify({'error': 'Update não encontrado.'}), 404
        if not can_write('campaign_action_logs', lid, c):
            conn.close()
            return jsonify({'error': 'Sem permissão para excluir este update.', 'error_type': 'forbidden'}), 403
        if (log.get('log_type') or 'user') != 'user':
            conn.close()
            return jsonify({'error': 'Apenas updates manuais podem ser excluídos.'}), 400
        c.execute('DELETE FROM campaign_action_logs WHERE id=?', (lid,))
        c.execute('UPDATE campaign_actions SET updated_at=CURRENT_TIMESTAMP WHERE id=?', (log['action_id'],))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        logger.exception(f'[Campaign] log delete {lid}: {e}')
        return jsonify({'error': str(e)}), 500
