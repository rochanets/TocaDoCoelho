# -*- coding: utf-8 -*-
# Rotas do domínio "portfolio" (Bloco 3 — modularização).
# Este arquivo é executado no namespace de app.py por _load_route_modules():
# tem acesso a todos os helpers/globals de app.py e registra as rotas no
# mesmo objeto Flask `app`, com URLs idênticas às originais.

@app.route('/api/portfolio/offers', methods=['GET'])
def list_portfolio_offers():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM portfolio_offers ORDER BY datetime(created_at) DESC, id DESC')
        offers = [dict_from_row(row) for row in c.fetchall()]
        for offer in offers:
            c.execute('SELECT * FROM portfolio_offer_items WHERE offer_id = ? ORDER BY sort_order ASC, id ASC', (offer['id'],))
            offer['items'] = [dict_from_row(item) for item in c.fetchall()]
        conn.close()
        return jsonify(offers)
    except Exception as e:
        logger.exception(f'[Portfolio] Erro ao listar ofertas: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/offers/<int:offer_id>', methods=['GET'])
def get_portfolio_offer(offer_id):
    try:
        conn = get_db()
        c = conn.cursor()
        offer = _portfolio_fetch_offer(c, offer_id)
        conn.close()
        if not offer:
            return jsonify({'error': 'Oferta não encontrada.'}), 404
        return jsonify(offer)
    except Exception as e:
        logger.exception(f'[Portfolio] Erro ao buscar oferta {offer_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/offers', methods=['POST'])
def create_portfolio_offer():
    try:
        input_text = (request.form.get('raw_input') or '').strip()
        file_obj = request.files.get('upload_file')

        file_bytes, file_mime, filename = None, None, None
        if file_obj and file_obj.filename:
            file_bytes = file_obj.read()
            file_mime = file_obj.mimetype or ''
            filename = file_obj.filename

        if not input_text and not file_bytes:
            return jsonify({'error': 'Informe um texto ou envie um PDF/imagem para análise.'}), 400

        task_id = uuid.uuid4().hex
        _portfolio_task_set(task_id, {'status': 'processing', 'step': 'Iniciando análise...', 'progress': 10})
        threading.Thread(
            target=_portfolio_process_offer_async,
            args=(task_id, input_text, file_bytes, file_mime, filename),
            daemon=True
        ).start()
        return jsonify({'task_id': task_id}), 202
    except Exception as e:
        logger.exception(f'[Portfolio] Erro ao iniciar tarefa: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/offers/tasks/<task_id>', methods=['GET'])
def get_portfolio_task_status(task_id):
    task = _portfolio_task_get(task_id)
    if not task:
        return jsonify({'status': 'error', 'error': 'Tarefa não encontrada ou expirada.'}), 404
    return jsonify(task)


@app.route('/api/portfolio/offers/<int:offer_id>', methods=['PUT'])
def update_portfolio_offer(offer_id):
    try:
        data = request.get_json() or {}
        title = (data.get('title') or '').strip()
        summary = (data.get('summary') or '').strip()
        if not title:
            return jsonify({'error': 'Título é obrigatório.'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM portfolio_offers WHERE id = ?', (offer_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Oferta não encontrada.'}), 404
        c.execute(
            'UPDATE portfolio_offers SET title = ?, summary = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            (title, summary, offer_id)
        )
        conn.commit()
        offer = _portfolio_fetch_offer(c, offer_id)
        conn.close()
        return jsonify(offer)
    except Exception as e:
        logger.exception(f'[Portfolio] Erro ao atualizar oferta {offer_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/offers/<int:offer_id>', methods=['DELETE'])
def delete_portfolio_offer(offer_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM portfolio_offer_items WHERE offer_id = ?', (offer_id,))
        c.execute('DELETE FROM portfolio_offers WHERE id = ?', (offer_id,))
        if c.rowcount == 0:
            conn.close()
            return jsonify({'error': 'Oferta não encontrada.'}), 404
        conn.commit()
        conn.close()
        return jsonify({'message': 'Oferta removida com sucesso.'})
    except Exception as e:
        logger.exception(f'[Portfolio] Erro ao remover oferta {offer_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/offers/export-json', methods=['GET'])
def export_portfolio_offers():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM portfolio_offers ORDER BY id')
        offers = [dict_from_row(r) for r in c.fetchall()]
        for offer in offers:
            c.execute('SELECT * FROM portfolio_offer_items WHERE offer_id = ? ORDER BY sort_order ASC, id ASC', (offer['id'],))
            offer['items'] = [dict_from_row(r) for r in c.fetchall()]
            offer.pop('id', None)
            for item in offer['items']:
                item.pop('id', None)
                item.pop('offer_id', None)
        conn.close()

        from flask import Response
        payload = json.dumps({'solucoes_stf': offers}, ensure_ascii=False, indent=2)
        return Response(
            payload,
            mimetype='application/json',
            headers={'Content-Disposition': f'attachment; filename=solucoes-stf-{datetime.now().strftime("%Y%m%d-%H%M%S")}.json'}
        )
    except Exception as e:
        logger.exception(f'[Portfolio] Erro ao exportar ofertas: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/offers/import-json', methods=['POST'])
def import_portfolio_offers():
    try:
        data = None
        if 'file' in request.files:
            file = request.files['file']
            if not file.filename:
                return jsonify({'error': 'Nenhum arquivo enviado.'}), 400
            try:
                data = json.loads(file.read().decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return jsonify({'error': 'Arquivo .json inválido ou corrompido.'}), 400
        else:
            data = request.get_json(silent=True)

        if not data:
            return jsonify({'error': 'Nenhum dado enviado para importação.'}), 400

        offers = data.get('solucoes_stf') if isinstance(data, dict) else data
        if not isinstance(offers, list):
            return jsonify({'error': 'Formato inválido. Esperado um pacote exportado do módulo Soluções STF.'}), 400

        conn = get_db()
        c = conn.cursor()
        imported = 0
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            title = (offer.get('title') or '').strip()
            if not title:
                continue
            summary = offer.get('summary') or ''
            raw_input = offer.get('raw_input') or ''
            c.execute(
                'INSERT INTO portfolio_offers (title, summary, raw_input, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)',
                (title, summary, raw_input)
            )
            offer_id = c.lastrowid
            for idx, item in enumerate(offer.get('items') or []):
                if not isinstance(item, dict):
                    continue
                c.execute(
                    '''INSERT INTO portfolio_offer_items (offer_id, pain, solution, sort_order, updated_at)
                       VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                    (offer_id, item.get('pain') or '', item.get('solution') or '', item.get('sort_order', idx))
                )
            imported += 1
        conn.commit()
        conn.close()
        return jsonify({'imported': imported}), 201
    except Exception as e:
        logger.exception(f'[Portfolio] Erro ao importar ofertas: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/offers/<int:offer_id>/items/<int:item_id>', methods=['PUT'])
def update_portfolio_offer_item(offer_id, item_id):
    try:
        data = request.get_json() or {}
        pain = (data.get('pain') or '').strip()
        solution = (data.get('solution') or '').strip()
        sort_order = data.get('sort_order')
        if not pain and not solution:
            return jsonify({'error': 'Informe dor e/ou solução.'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM portfolio_offer_items WHERE id = ? AND offer_id = ?', (item_id, offer_id))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Item não encontrado.'}), 404

        if sort_order is None:
            c.execute(
                '''UPDATE portfolio_offer_items
                   SET pain = ?, solution = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND offer_id = ?''',
                (pain, solution, item_id, offer_id)
            )
        else:
            try:
                sort_order_int = int(sort_order)
            except Exception:
                return jsonify({'error': 'sort_order inválido.'}), 400
            c.execute(
                '''UPDATE portfolio_offer_items
                   SET pain = ?, solution = ?, sort_order = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND offer_id = ?''',
                (pain, solution, sort_order_int, item_id, offer_id)
            )

        conn.commit()
        c.execute('SELECT * FROM portfolio_offer_items WHERE id = ? AND offer_id = ?', (item_id, offer_id))
        item = dict_from_row(c.fetchone())
        conn.close()
        return jsonify(item)
    except Exception as e:
        logger.exception(f'[Portfolio] Erro ao atualizar item {item_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/offers/<int:offer_id>/items', methods=['POST'])
def create_portfolio_offer_item(offer_id):
    try:
        data = request.get_json() or {}
        pain = (data.get('pain') or '').strip()
        solution = (data.get('solution') or '').strip()
        if not pain and not solution:
            return jsonify({'error': 'Informe dor e/ou solução.'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM portfolio_offers WHERE id = ?', (offer_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Oferta não encontrada.'}), 404
        c.execute('SELECT COALESCE(MAX(sort_order), -1) AS max_sort FROM portfolio_offer_items WHERE offer_id = ?', (offer_id,))
        max_sort = (dict_from_row(c.fetchone()) or {}).get('max_sort', -1)
        next_sort = int(max_sort) + 1
        c.execute(
            '''INSERT INTO portfolio_offer_items (offer_id, pain, solution, sort_order, updated_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)''',
            (offer_id, pain, solution, next_sort)
        )
        item_id = c.lastrowid
        conn.commit()
        c.execute('SELECT * FROM portfolio_offer_items WHERE id = ?', (item_id,))
        item = dict_from_row(c.fetchone())
        conn.close()
        return jsonify(item), 201
    except Exception as e:
        logger.exception(f'[Portfolio] Erro ao criar item para oferta {offer_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/offers/<int:offer_id>/items/<int:item_id>', methods=['DELETE'])
def delete_portfolio_offer_item(offer_id, item_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM portfolio_offer_items WHERE id = ? AND offer_id = ?', (item_id, offer_id))
        if c.rowcount == 0:
            conn.close()
            return jsonify({'error': 'Item não encontrado.'}), 404
        conn.commit()
        conn.close()
        return jsonify({'message': 'Item removido com sucesso.'})
    except Exception as e:
        logger.exception(f'[Portfolio] Erro ao remover item {item_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/iata', methods=['GET'])
def list_iata_records():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM iata_records ORDER BY datetime(created_at) DESC, id DESC')
        records = [_iata_record_to_dict(row) for row in c.fetchall()]
        conn.close()
        return jsonify(records)
    except Exception as e:
        logger.exception(f'[iAta] Erro ao listar registros: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/iata/<int:record_id>', methods=['GET'])
def get_iata_record(record_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM iata_records WHERE id = ?', (record_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            return jsonify({'error': 'Registro não encontrado.'}), 404
        return jsonify(_iata_record_to_dict(row))
    except Exception as e:
        logger.exception(f'[iAta] Erro ao buscar registro {record_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/iata', methods=['POST'])
def create_iata_record():
    try:
        file_obj = request.files.get('meeting_file')
        raw_text_input = (request.form.get('raw_text') or '').strip()

        if not file_obj and not raw_text_input:
            return jsonify({'error': 'Envie um arquivo de reunião ou cole o texto.'}), 400

        file_bytes, filename = None, None
        if file_obj and file_obj.filename:
            file_bytes = file_obj.read()
            filename = file_obj.filename

        task_id = uuid.uuid4().hex
        _iata_task_set(task_id, {'status': 'processing', 'step': 'Iniciando...', 'progress': 5})
        threading.Thread(
            target=_iata_process_async,
            args=(task_id, file_bytes, filename, raw_text_input),
            daemon=True
        ).start()
        return jsonify({'task_id': task_id}), 202
    except Exception as e:
        logger.exception(f'[iAta] Erro ao iniciar tarefa: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/iata/tasks/<task_id>', methods=['GET'])
def get_iata_task_status(task_id):
    task = _iata_task_get(task_id)
    if not task:
        return jsonify({'status': 'error', 'error': 'Tarefa não encontrada ou expirada.'}), 404
    return jsonify(task)


@app.route('/api/portfolio/iata/<int:record_id>', methods=['DELETE'])
def delete_iata_record(record_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM iata_records WHERE id = ?', (record_id,))
        if c.rowcount == 0:
            conn.close()
            return jsonify({'error': 'Registro não encontrado.'}), 404
        conn.commit()
        conn.close()
        return jsonify({'message': 'Registro removido com sucesso.'})
    except Exception as e:
        logger.exception(f'[iAta] Erro ao remover registro {record_id}: {e}')
        return jsonify({'error': str(e)}), 500


# ===========================================================================
# Whitespace de ofertas / share of wallet (Bloco 12)
# ===========================================================================

def _ws_normalize(s):
    return re.sub(r'\s+', ' ', (s or '').strip().lower())


def _account_whitespace(c, account_id):
    """Cruza portfolio_offers com account_presences da conta (por nome):
    ofertas presentes vs. nunca entregues/mencionadas."""
    c.execute('SELECT id, title FROM portfolio_offers ORDER BY title COLLATE NOCASE')
    offers = c.fetchall()
    c.execute("""SELECT delivery_name FROM account_presences
                 WHERE account_id = ? AND COALESCE(early_terminated, 0) = 0""", (account_id,))
    presences = [_ws_normalize(r['delivery_name']) for r in c.fetchall()]
    present, missing = [], []
    for offer in offers:
        t = _ws_normalize(offer['title'])
        has = any(t and p and (t in p or p in t) for p in presences)
        (present if has else missing).append({'id': offer['id'], 'title': offer['title']})
    return {'present': present, 'missing': missing,
            'presences': [r for r in presences]}


@app.route('/api/accounts/<int:account_id>/whitespace', methods=['GET'])
def account_whitespace(account_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id, name FROM accounts WHERE id = ?', (account_id,))
        acc = c.fetchone()
        if not acc:
            conn.close()
            return jsonify({'error': 'Conta não encontrada'}), 404
        result = _account_whitespace(c, account_id)
        result['account_id'] = account_id
        result['account_name'] = acc['name']
        conn.close()
        return jsonify(result)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/accounts/{account_id}/whitespace: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/whitespace-matrix', methods=['GET'])
def portfolio_whitespace_matrix():
    """Matriz contas target × ofertas para a view Whitespace do Portfólio."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id, title FROM portfolio_offers ORDER BY title COLLATE NOCASE')
        offers = [dict(r) for r in c.fetchall()]
        c.execute("SELECT id, name FROM accounts WHERE COALESCE(is_target, 0) = 1 ORDER BY name COLLATE NOCASE")
        rows = []
        for acc in c.fetchall():
            ws = _account_whitespace(c, acc['id'])
            present_ids = {o['id'] for o in ws['present']}
            rows.append({'account_id': acc['id'], 'name': acc['name'],
                         'cells': {str(o['id']): (o['id'] in present_ids) for o in offers}})
        conn.close()
        return jsonify({'offers': offers, 'rows': rows})
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/portfolio/whitespace-matrix: {e}')
        return jsonify({'error': str(e)}), 500
