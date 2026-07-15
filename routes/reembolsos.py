# -*- coding: utf-8 -*-
# Rotas do submódulo "reembolsos" do AutoToca (Bloco 3 — modularização).
# Este arquivo é executado no namespace de app.py por _load_route_modules():
# tem acesso a todos os helpers/globals de app.py e registra as rotas no
# mesmo objeto Flask `app`.

REEMBOLSO_ROBOT_TASKS = {}
REEMBOLSO_ROBOT_TASKS_LOCK = threading.Lock()


def _reembolso_task_set(task_id, updates):
    with REEMBOLSO_ROBOT_TASKS_LOCK:
        task = REEMBOLSO_ROBOT_TASKS.get(task_id, {})
        task.update(updates)
        REEMBOLSO_ROBOT_TASKS[task_id] = task


def _reembolso_task_get(task_id):
    with REEMBOLSO_ROBOT_TASKS_LOCK:
        return dict(REEMBOLSO_ROBOT_TASKS.get(task_id) or {})


def _reembolso_task_cleanup(task_id, delay=300):
    def _cleanup():
        time.sleep(delay)
        with REEMBOLSO_ROBOT_TASKS_LOCK:
            REEMBOLSO_ROBOT_TASKS.pop(task_id, None)
    threading.Thread(target=_cleanup, daemon=True).start()


@app.route('/api/autotoca/reembolsos/origem-historico', methods=['GET'])
def reembolsos_origem_historico():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT texto FROM reembolso_origem_historico ORDER BY created_at DESC, id DESC LIMIT 30')
        rows = c.fetchall()
        conn.close()
        return jsonify([{'texto': r['texto']} for r in rows])
    except Exception as e:
        logger.exception(f'[Reembolsos] GET /origem-historico: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/reembolsos/conta-endereco/<int:account_id>', methods=['GET'])
def reembolsos_conta_endereco(account_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT endereco FROM account_reembolso_enderecos WHERE account_id = ?', (account_id,))
        row = c.fetchone()
        conn.close()
        return jsonify({'endereco': row['endereco'] if row else None})
    except Exception as e:
        logger.exception(f'[Reembolsos] GET /conta-endereco/{account_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/reembolsos/extract', methods=['POST'])
def reembolsos_extract():
    try:
        if 'file' not in request.files or not request.files['file'].filename:
            return jsonify({'error': 'Nenhum arquivo enviado.'}), 400
        file = request.files['file']
        file_bytes = file.read()
        mime = (file.mimetype or 'image/jpeg').split(';')[0].strip() or 'image/jpeg'
        result = _reembolso_extract_receipt(file_bytes, mime, file.filename or '')
        return jsonify(result)
    except Exception as e:
        logger.exception(f'[Reembolsos] POST /extract: {e}')
        return jsonify({'error': str(e)}), 500


def _reembolso_process_extract_async(task_id, uploads):
    try:
        extracted = []
        total = len(uploads)
        for index, upload in enumerate(uploads, start=1):
            progress = 8 + int(((index - 1) / max(total, 1)) * 82)
            _reembolso_task_set(task_id, {
                'progress': progress,
                'step': f'Analisando comprovante {index} de {total}: {upload["filename"]}',
            })
            result = _reembolso_extract_receipt(
                upload['bytes'], upload['mime'], upload['filename']
            )
            extracted.append({
                'filename': upload['filename'],
                'data': result.get('data'),
                'valor_cents': result.get('valor_cents'),
            })

        summary = _reembolso_aggregate_receipts(extracted)
        summary['items'] = extracted
        _reembolso_task_set(task_id, {
            'status': 'done',
            'progress': 100,
            'step': f'{total} comprovante(s) analisado(s).',
            'result': summary,
        })
    except Exception as e:
        logger.exception('[Reembolsos] Falha na análise assíncrona de comprovantes')
        _reembolso_task_set(task_id, {
            'status': 'error',
            'error': f'Falha ao analisar os comprovantes: {e}',
        })
    finally:
        _reembolso_task_cleanup(task_id)


@app.route('/api/autotoca/reembolsos/extract/tasks', methods=['POST'])
def reembolsos_extract_task_start():
    files = [f for f in request.files.getlist('files') if f and f.filename]
    if not files:
        return jsonify({'error': 'Nenhum arquivo enviado.'}), 400

    uploads = []
    for file in files:
        uploads.append({
            'filename': file.filename,
            'mime': (file.mimetype or 'image/jpeg').split(';')[0].strip() or 'image/jpeg',
            'bytes': file.read(),
        })

    task_id = uuid.uuid4().hex
    _reembolso_task_set(task_id, {
        'status': 'processing',
        'step': 'Preparando os comprovantes...',
        'progress': 5,
    })
    threading.Thread(
        target=_reembolso_process_extract_async,
        args=(task_id, uploads),
        daemon=True,
    ).start()
    return jsonify({'task_id': task_id}), 202


@app.route('/api/autotoca/reembolsos/extract/tasks/<task_id>', methods=['GET'])
def reembolsos_extract_task_status(task_id):
    task = _reembolso_task_get(task_id)
    if not task:
        return jsonify({'error': 'Tarefa não encontrada.'}), 404
    return jsonify(task)


def _reembolso_save_uploaded_files(history_id, field_key, file_storages):
    saved = []
    field_dir = REEMBOLSOS_UPLOAD_DIR / str(history_id) / field_key
    field_dir.mkdir(parents=True, exist_ok=True)
    for f in file_storages:
        if not f or not f.filename:
            continue
        safe_name = secure_filename(f.filename) or f'arquivo_{uuid.uuid4().hex}'
        target = field_dir / safe_name
        counter = 1
        while target.exists():
            target = field_dir / f'{target.stem}_{counter}{target.suffix}'
            counter += 1
        f.save(str(target))
        saved.append(str(target))
    return saved


def _reembolso_process_deslocamento_async(task_id, history_id, payload, file_paths):
    from integrations.reembolso_robot import run_deslocamento_robot, ReembolsoRobotError

    def on_progress(pct, step):
        _reembolso_task_set(task_id, {'progress': pct, 'step': step})

    try:
        result = run_deslocamento_robot(payload, file_paths, on_progress)
        if payload.get('destino') and payload.get('account_id'):
            conn = get_db()
            c = conn.cursor()
            c.execute(
                'INSERT INTO account_reembolso_enderecos (account_id, endereco) VALUES (?, ?) '
                'ON CONFLICT(account_id) DO UPDATE SET endereco = excluded.endereco, updated_at = CURRENT_TIMESTAMP',
                (payload['account_id'], payload['destino'])
            )
            conn.commit()
            conn.close()
        if payload.get('origem'):
            conn = get_db()
            c = conn.cursor()
            c.execute('INSERT OR IGNORE INTO reembolso_origem_historico (texto) VALUES (?)', (payload['origem'],))
            conn.commit()
            conn.close()
        _reembolso_task_set(task_id, {
            'status': 'done', 'progress': 100,
            'step': 'Preenchimento concluído — revise e envie na janela do robô.',
            'result': result,
        })
    except ReembolsoRobotError as e:
        logger.warning(f'[Reembolsos][Robot] {e}')
        _reembolso_task_set(task_id, {'status': 'error', 'error': str(e)})
    except Exception as e:
        logger.exception('[Reembolsos][Robot] Falha inesperada')
        _reembolso_task_set(task_id, {'status': 'error', 'error': f'Falha inesperada no robô: {e}'})
    finally:
        _reembolso_task_cleanup(task_id)


@app.route('/api/autotoca/reembolsos/deslocamento/robot', methods=['POST'])
def reembolsos_deslocamento_robot():
    try:
        form = request.form
        celula_custo = (form.get('celula_custo') or '').strip()
        descricao_despesa = (form.get('descricao_despesa') or '').strip()
        sub_fluxo = (form.get('sub_fluxo') or '').strip()

        errors = []
        if not celula_custo:
            errors.append('Célula custo é obrigatória.')
        if not descricao_despesa:
            errors.append('Descrição da despesa é obrigatória.')
        if sub_fluxo not in ('deslocamento', 'estacionamento'):
            errors.append('sub_fluxo deve ser "deslocamento" ou "estacionamento".')
        if errors:
            return jsonify({'error': ' '.join(errors)}), 400

        payload = {'celula_custo': celula_custo, 'descricao_despesa': descricao_despesa, 'sub_fluxo': sub_fluxo}
        if sub_fluxo == 'deslocamento':
            payload.update({
                'origem': (form.get('origem') or '').strip(),
                'destino': (form.get('destino') or '').strip(),
                'account_id': int(form['account_id']) if form.get('account_id') else None,
                'conta': (form.get('conta') or '').strip(),
                'data_deslocamento': (form.get('data_deslocamento') or '').strip(),
                'tipo_transporte': (form.get('tipo_transporte') or '').strip(),
                'ida_e_volta': (form.get('ida_e_volta') or '').lower() == 'true',
                'pedagio_valor_total': float(form['pedagio_valor_total']) if form.get('pedagio_valor_total') else None,
            })
        else:
            payload.update({
                'quantidade': int(form.get('quantidade') or 0),
                'periodo_inicio': (form.get('periodo_inicio') or '').strip(),
                'periodo_fim': (form.get('periodo_fim') or '').strip(),
                'valor_total': float(form.get('valor_total') or 0),
                'descricao_estacionamento': (form.get('descricao_estacionamento') or '').strip(),
            })

        conn = get_db()
        c = conn.cursor()
        c.execute(
            'INSERT INTO reembolsos_history (tipo, payload_json, files_json) VALUES (?, ?, ?)',
            (f'deslocamento:{sub_fluxo}', json.dumps(payload, ensure_ascii=False), '{}')
        )
        conn.commit()
        history_id = c.lastrowid

        file_paths = {}
        if sub_fluxo == 'deslocamento':
            comprovante_data = [f for f in request.files.getlist('data_deslocamento_comprovante') if f and f.filename]
            file_paths['data_deslocamento_comprovante'] = _reembolso_save_uploaded_files(history_id, 'data_deslocamento_comprovante', comprovante_data)
            pedagio_files = [f for f in request.files.getlist('pedagio_comprovantes') if f and f.filename]
            if payload.get('pedagio_valor_total') and not pedagio_files:
                from integrations.reembolso_robot import gerar_comprovante_corrompido
                corrompido = gerar_comprovante_corrompido(REEMBOLSOS_UPLOAD_DIR / str(history_id) / 'pedagio_comprovantes')
                file_paths['pedagio_comprovantes'] = [str(corrompido)]
            else:
                file_paths['pedagio_comprovantes'] = _reembolso_save_uploaded_files(history_id, 'pedagio_comprovantes', pedagio_files)
        else:
            estac_files = [f for f in request.files.getlist('estacionamento_comprovantes') if f and f.filename]
            file_paths['estacionamento_comprovantes'] = _reembolso_save_uploaded_files(history_id, 'estacionamento_comprovantes', estac_files)

        c.execute('UPDATE reembolsos_history SET files_json = ? WHERE id = ?', (json.dumps(file_paths, ensure_ascii=False), history_id))
        conn.commit()
        conn.close()

        task_id = uuid.uuid4().hex
        _reembolso_task_set(task_id, {'status': 'processing', 'step': 'Iniciando o robô...', 'progress': 5})
        threading.Thread(target=_reembolso_process_deslocamento_async, args=(task_id, history_id, payload, file_paths), daemon=True).start()
        return jsonify({'task_id': task_id, 'history_id': history_id}), 202
    except Exception as e:
        logger.exception(f'[Reembolsos] POST /deslocamento/robot: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/reembolsos/deslocamento/robot/tasks/<task_id>', methods=['GET'])
def reembolsos_deslocamento_robot_task(task_id):
    task = _reembolso_task_get(task_id)
    if not task:
        return jsonify({'error': 'Tarefa não encontrada.'}), 404
    return jsonify(task)


def _reembolso_process_almoco_async(task_id, history_id, payload, comprovantes):
    from integrations.reembolso_robot import run_almoco_robot, ReembolsoRobotError

    def on_progress(pct, step):
        _reembolso_task_set(task_id, {'progress': pct, 'step': step})

    try:
        result = run_almoco_robot(payload, comprovantes, on_progress)
        _reembolso_task_set(task_id, {
            'status': 'done', 'progress': 100,
            'step': 'Preenchimento concluído — revise e envie na janela do robô.',
            'result': result,
        })
    except ReembolsoRobotError as e:
        logger.warning(f'[Reembolsos][Robot] {e}')
        _reembolso_task_set(task_id, {'status': 'error', 'error': str(e)})
    except Exception as e:
        logger.exception('[Reembolsos][Robot] Falha inesperada')
        _reembolso_task_set(task_id, {'status': 'error', 'error': f'Falha inesperada no robô: {e}'})
    finally:
        _reembolso_task_cleanup(task_id)


@app.route('/api/autotoca/reembolsos/almoco/robot', methods=['POST'])
def reembolsos_almoco_robot():
    try:
        form = request.form
        celula_custo = (form.get('celula_custo') or '').strip()
        descricao_despesa = (form.get('descricao_despesa') or '').strip()
        descricao = (form.get('descricao') or '').strip()

        errors = []
        if not celula_custo:
            errors.append('Célula custo é obrigatória.')
        if not descricao_despesa:
            errors.append('Descrição da despesa é obrigatória.')
        if not descricao:
            errors.append('Descrição é obrigatória.')
        comprovante_files = [f for f in request.files.getlist('comprovantes') if f and f.filename]
        if not comprovante_files:
            errors.append('Anexe ao menos um comprovante.')
        if errors:
            return jsonify({'error': ' '.join(errors)}), 400

        payload = {
            'celula_custo': celula_custo,
            'descricao_despesa': descricao_despesa,
            'quantidade': int(form.get('quantidade') or len(comprovante_files)),
            'periodo_inicio': (form.get('periodo_inicio') or '').strip(),
            'periodo_fim': (form.get('periodo_fim') or '').strip(),
            'valor_total': float(form.get('valor_total') or 0),
            'descricao': descricao,
        }

        conn = get_db()
        c = conn.cursor()
        c.execute(
            'INSERT INTO reembolsos_history (tipo, payload_json, files_json) VALUES (?, ?, ?)',
            ('almoco', json.dumps(payload, ensure_ascii=False), '{}')
        )
        conn.commit()
        history_id = c.lastrowid

        comprovantes = _reembolso_save_uploaded_files(history_id, 'comprovantes', comprovante_files)
        c.execute('UPDATE reembolsos_history SET files_json = ? WHERE id = ?', (json.dumps({'comprovantes': comprovantes}, ensure_ascii=False), history_id))
        conn.commit()
        conn.close()

        task_id = uuid.uuid4().hex
        _reembolso_task_set(task_id, {'status': 'processing', 'step': 'Iniciando o robô...', 'progress': 5})
        threading.Thread(target=_reembolso_process_almoco_async, args=(task_id, history_id, payload, comprovantes), daemon=True).start()
        return jsonify({'task_id': task_id, 'history_id': history_id}), 202
    except Exception as e:
        logger.exception(f'[Reembolsos] POST /almoco/robot: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/reembolsos/almoco/robot/tasks/<task_id>', methods=['GET'])
def reembolsos_almoco_robot_task(task_id):
    task = _reembolso_task_get(task_id)
    if not task:
        return jsonify({'error': 'Tarefa não encontrada.'}), 404
    return jsonify(task)
