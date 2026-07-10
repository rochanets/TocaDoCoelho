# -*- coding: utf-8 -*-
# Rotas do domínio "autotoca" (Bloco 3 — modularização).
# Este arquivo é executado no namespace de app.py por _load_route_modules():
# tem acesso a todos os helpers/globals de app.py e registra as rotas no
# mesmo objeto Flask `app`, com URLs idênticas às originais.

@app.route('/api/autotoca/mala-direta/positions', methods=['GET'])
def get_autotoca_mailing_positions():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT DISTINCT position FROM clients WHERE position IS NOT NULL AND TRIM(position) != "" ORDER BY position COLLATE NOCASE')
        positions = [row['position'] for row in c.fetchall()]
        conn.close()
        return jsonify(positions)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/autotoca/mala-direta/positions: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/mala-direta/areas', methods=['GET'])
def get_autotoca_mailing_areas():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT DISTINCT area_of_activity FROM clients WHERE area_of_activity IS NOT NULL AND TRIM(area_of_activity) != "" ORDER BY area_of_activity COLLATE NOCASE')
        areas = [row['area_of_activity'] for row in c.fetchall()]
        conn.close()
        return jsonify(areas)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/autotoca/mala-direta/areas: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/automapping/cancel', methods=['POST'])
def cancel_automapping():
    try:
        data = request.get_json() or {}
        request_id = (data.get('request_id') or '').strip()
        if not request_id:
            return jsonify({'error': 'request_id é obrigatório'}), 400
        _mark_automapping_cancelled(request_id)
        return jsonify({'message': 'Cancelamento registrado'})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/automapping/cancel: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/automapping', methods=['POST'])
def run_automapping():
    try:
        data = request.get_json() or {}
        company = (data.get('company') or '').strip()
        country = (data.get('country') or '').strip()
        industry = (data.get('industry') or '').strip()
        force = bool(data.get('force'))
        request_id = (data.get('request_id') or '').strip()

        if not company or not country or not industry:
            return jsonify({'error': 'company, country e industry são obrigatórios'}), 400

        if _is_automapping_cancelled(request_id, consume=True):
            return jsonify({'cancelled': True, 'message': 'AutoMapping cancelado pelo usuário.'}), 409

        task_id = uuid.uuid4().hex
        _bg_task_set(task_id, {'status': 'processing', 'step': 'Iniciando...', 'progress': 5})
        threading.Thread(
            target=_automapping_process_async,
            args=(task_id, company, country, industry, force, request_id),
            daemon=True
        ).start()
        return jsonify({'task_id': task_id}), 202

    except Exception as e:
        logger.exception(f'[ERROR] POST /api/automapping: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/automapping/runs/<int:run_id>', methods=['GET'])
def get_automapping_run(run_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM automapping_runs WHERE id = ?', (run_id,))
        run = c.fetchone()
        conn.close()
        if not run:
            return jsonify({'error': 'Execução não encontrada'}), 404
        payload = dict_from_row(run)
        payload['result'] = json.loads(payload['result_json'])
        return jsonify(payload)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/automapping/runs/{run_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/automapping/runs/<int:run_id>', methods=['DELETE'])
def delete_automapping_run(run_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM automapping_runs WHERE id = ?', (run_id,))
        deleted = c.rowcount
        conn.commit()
        conn.close()
        if not deleted:
            return jsonify({'error': 'Execução não encontrada'}), 404
        return jsonify({'message': 'Log de AutoMapping removido com sucesso'})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE /api/automapping/runs/{run_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/automapping/runs', methods=['GET'])
def list_automapping_runs():
    try:
        days = request.args.get('days', '20')
        try:
            days = max(1, min(60, int(days)))
        except Exception:
            days = 20

        conn = get_db()
        c = conn.cursor()
        c.execute('''SELECT id, company, country, industry, result_json, created_at
                     FROM automapping_runs
                     WHERE datetime(created_at) >= datetime('now', ?)
                     ORDER BY datetime(created_at) DESC''', (f'-{days} days',))
        rows = c.fetchall()
        conn.close()

        runs = []
        for row in rows:
            parsed = dict_from_row(row)
            result = json.loads(parsed.get('result_json') or '{}')
            sections = result.get('sections') or {}
            queries = {
                section_key: section_val.get('query_used')
                for section_key, section_val in sections.items()
                if isinstance(section_val, dict) and section_val.get('query_used')
            }
            runs.append({
                'id': parsed.get('id'),
                'company': parsed.get('company'),
                'country': parsed.get('country'),
                'industry': parsed.get('industry'),
                'created_at': parsed.get('created_at'),
                'queries': queries,
                'sections_count': len(queries)
            })

        return jsonify({'days': days, 'runs': runs})
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/automapping/runs: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/accounts', methods=['GET'])
def autotoca_accounts():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id, name FROM accounts ORDER BY name COLLATE NOCASE')
        rows = c.fetchall()
        conn.close()
        accounts = [{'id': row['id'], 'name': row['name']} for row in rows]
        return jsonify([{'id': 0, 'name': 'OUTRO'}] + accounts)
    except Exception as e:
        logger.exception(f'[AutoToca] GET /api/autotoca/accounts: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/upload', methods=['POST'])
def autotoca_upload():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'Nenhum arquivo enviado.'}), 400
        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'Nome de arquivo inválido.'}), 400
        
        # Verificar se deve converter para PDF (parâmetro convert_to_pdf)
        convert_to_pdf = request.form.get('convert_to_pdf', 'false').lower() == 'true'
        original_filename = secure_filename(file.filename)
        
        # Se deve converter para PDF
        if convert_to_pdf and not original_filename.lower().endswith('.pdf'):
            try:
                # Salvar arquivo temporário
                temp_path = AUTOTOCA_UPLOAD_DIR / f"temp_{uuid.uuid4().hex}_{original_filename}"
                file.save(str(temp_path))
                
                # Converter para PDF
                pdf_filename = original_filename.rsplit('.', 1)[0] + '.pdf'
                safe_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}_{pdf_filename}"
                target = AUTOTOCA_UPLOAD_DIR / safe_name
                
                # Se é um arquivo de imagem, converter para PDF
                file_ext = original_filename.rsplit('.', 1)[-1].lower() if '.' in original_filename else ''
                if file_ext in {'jpg', 'jpeg', 'png', 'gif', 'bmp'}:
                    try:
                        from PIL import Image
                        img = Image.open(str(temp_path))
                        if img.mode == 'RGBA':
                            img = img.convert('RGB')
                        img.save(str(target), 'PDF')
                        logger.info(f'[AutoToca] Imagem convertida para PDF: {original_filename} -> {pdf_filename}')
                    except Exception as e:
                        logger.warning(f'[AutoToca] Falha ao converter imagem para PDF: {e}. Usando arquivo original.')
                        target = AUTOTOCA_UPLOAD_DIR / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}_{original_filename}"
                        file.seek(0)
                        file.save(str(target))
                        pdf_filename = original_filename
                elif file_ext in {'docx', 'doc', 'txt', 'html', 'htm'}:
                    try:
                        # Para documentos Word, usar python-docx
                        if file_ext in {'docx', 'doc'} and PYTHON_DOCX_AVAILABLE:
                            from reportlab.lib.pagesizes import letter
                            from reportlab.pdfgen import canvas
                            doc = python_docx.Document(str(temp_path))
                            c = canvas.Canvas(str(target), pagesize=letter)
                            y = 750
                            for para in doc.paragraphs:
                                if para.text.strip():
                                    text = para.text[:100]
                                    c.drawString(50, y, text)
                                    y -= 20
                                    if y < 50:
                                        c.showPage()
                                        y = 750
                            c.save()
                            logger.info(f'[AutoToca] Documento convertido para PDF: {original_filename} -> {pdf_filename}')
                        else:
                            # Fallback: copiar arquivo original
                            shutil.copy2(str(temp_path), str(target))
                    except Exception as e:
                        logger.warning(f'[AutoToca] Falha ao converter documento para PDF: {e}. Usando arquivo original.')
                        shutil.copy2(str(temp_path), str(target))
                else:
                    # Para outros formatos, apenas copiar
                    shutil.copy2(str(temp_path), str(target))
                
                # Remover arquivo temporário
                try:
                    temp_path.unlink()
                except Exception as e:
                    logger.debug(f'[autotoca_upload] exceção ignorada: {e}')
                
                return jsonify({'path': str(target), 'url': f'/uploads/autotoca/{safe_name}', 'name': pdf_filename})
            except Exception as e:
                logger.exception(f'[AutoToca] Erro ao converter arquivo para PDF: {e}')
                # Fallback: salvar arquivo original
                safe_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}_{original_filename}"
                target = AUTOTOCA_UPLOAD_DIR / safe_name
                file.seek(0)
                file.save(str(target))
                return jsonify({'path': str(target), 'url': f'/uploads/autotoca/{safe_name}', 'name': original_filename})
        else:
            # Sem conversão, salvar normalmente
            safe_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}_{original_filename}"
            target = AUTOTOCA_UPLOAD_DIR / safe_name
            file.save(str(target))
            return jsonify({'path': str(target), 'url': f'/uploads/autotoca/{safe_name}', 'name': file.filename})
    except Exception as e:
        logger.exception(f'[AutoToca] POST /api/autotoca/upload: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/account-info', methods=['POST'])
def autotoca_account_info():
    try:
        data = request.get_json(force=True) or {}
        account_name = (data.get('account_name') or '').strip()
        if not account_name:
            return jsonify({'error': 'Conta inválida para busca de dados.'}), 400

        result = _autotoca_account_info_via_llm(account_name)
        return jsonify(result)
    except Exception as e:
        logger.exception(f'[AutoToca] POST /api/autotoca/account-info: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/support-files', methods=['GET'])
def autotoca_support_files():
    try:
        files = []
        for path in sorted(AUTOTOCA_SUPPORT_FILES_DIR.glob('*')):
            if not path.is_file():
                continue
            if path.suffix.lower() != '.pdf':
                continue
            files.append({
                'name': path.name,
                'url': f'/assets/autotoca/chamado-juridico/{urllib.parse.quote(path.name)}'
            })
        return jsonify(files)
    except Exception as e:
        logger.exception(f'[AutoToca] GET /api/autotoca/support-files: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/chamado-juridico/playwright', methods=['POST'])
def autotoca_chamado_juridico_playwright():
    try:
        data = request.get_json(force=True) or {}
        conta = (data.get('conta') or '').strip()
        if not conta:
            return jsonify({'ok': False, 'error': 'Conta é obrigatória.'}), 400
        payload = {'forms_url': data.get('forms_url'), 'target_value': conta}
        try:
            result = _run_autotoca_playwright_fill(payload)
        except Exception as exc:
            logger.exception('[AutoToca] Falha no Playwright')
            result = {'ok': False, 'strategy': 'playwright', 'reason': 'playwright_failed', 'error': str(exc)}
        if not result.get('ok'):
            result['fallback'] = _run_autotoca_selenium_fill(payload)
        return jsonify(result)
    except Exception as e:
        logger.exception(f'[AutoToca] POST /api/autotoca/chamado-juridico/playwright: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/autotoca/linkedin/teste', methods=['POST'])
def autotoca_teste_linkedin():
    try:
        data = request.get_json(force=True) or {}
        name = (data.get('name') or '').strip()
        company = (data.get('company') or '').strip()
        if not name or not company:
            return jsonify({'ok': False, 'error': 'Informe nome e empresa.'}), 400
        return jsonify({'ok': True, 'items': _linkedin_mock_candidates(name, company), 'mode': 'safe_fallback'})
    except Exception as e:
        logger.exception(f'[AutoToca] POST /api/autotoca/linkedin/teste: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/uploads/autotoca/<filename>')
def serve_autotoca_upload(filename):
    return send_from_directory(str(AUTOTOCA_UPLOAD_DIR), filename)
