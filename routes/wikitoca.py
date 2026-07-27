# -*- coding: utf-8 -*-
# Rotas do domínio "wikitoca" (Bloco 3 — modularização).
# Este arquivo é executado no namespace de app.py por _load_route_modules():
# tem acesso a todos os helpers/globals de app.py e registra as rotas no
# mesmo objeto Flask `app`, com URLs idênticas às originais.

@app.route('/api/wikitoca/entries', methods=['GET'])
def list_wiki_entries():
    logger.debug('[DEBUG] GET /api/wikitoca/entries chamado')
    try:
        q = (request.args.get('q') or '').strip()
        conn = get_db()
        c = conn.cursor()
        _vw, _vp = visible_where('wiki_entries')
        if q:
            like = f'%{q}%'
            c.execute(
                f'''SELECT * FROM wiki_entries
                   WHERE (title LIKE ? OR content LIKE ? OR category LIKE ? OR tags LIKE ?) AND {_vw}
                   ORDER BY updated_at DESC''',
                (like, like, like, like, *_vp)
            )
        else:
            c.execute(f'SELECT * FROM wiki_entries WHERE {_vw} ORDER BY updated_at DESC', _vp)
        rows = [dict_from_row(r) for r in c.fetchall()]
        conn.close()
        logger.debug(f'[DEBUG] GET /api/wikitoca/entries retornando {len(rows)} registros')
        return jsonify(rows)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/wikitoca/entries: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_ENTRIES_LIST_ERROR', 'Erro ao listar conhecimentos.', details=str(e),
                         hint='Verifique se o banco de dados está acessível.')


@app.route('/api/wikitoca/entries', methods=['POST'])
def create_wiki_entry():
    logger.debug('[DEBUG] POST /api/wikitoca/entries chamado')
    try:
        data = request.get_json(force=True) or {}
        logger.debug(f'[DEBUG] POST /api/wikitoca/entries payload: {data}')
        title = (data.get('title') or '').strip()
        content = (data.get('content') or '').strip()
        category = (data.get('category') or '').strip() or None
        tags = (data.get('tags') or '').strip() or None
        if not title or not content:
            logger.warning('[WARN] POST /api/wikitoca/entries: titulo ou conteudo ausente')
            return api_error(400, 'WIKI_ENTRY_MISSING_FIELDS', 'Título e conteúdo são obrigatórios.')
        conn = get_db()
        c = conn.cursor()
        c.execute(
            '''INSERT INTO wiki_entries (title, category, content, tags, owner_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
            (title, category, content, tags, _acl_owner_for_insert())
        )
        conn.commit()
        entry_id = c.lastrowid
        c.execute('SELECT * FROM wiki_entries WHERE id = ?', (entry_id,))
        entry = dict_from_row(c.fetchone())
        conn.close()
        logger.debug(f'[DEBUG] POST /api/wikitoca/entries criado id={entry_id}')
        return jsonify(entry), 201
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/wikitoca/entries: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_ENTRY_CREATE_ERROR', 'Erro ao criar conhecimento.', details=str(e))


@app.route('/api/wikitoca/entries/<int:entry_id>', methods=['PUT'])
def update_wiki_entry(entry_id):
    logger.debug(f'[DEBUG] PUT /api/wikitoca/entries/{entry_id} chamado')
    try:
        data = request.get_json(force=True) or {}
        title = (data.get('title') or '').strip()
        content = (data.get('content') or '').strip()
        category = (data.get('category') or '').strip() or None
        tags = (data.get('tags') or '').strip() or None
        if not title or not content:
            return api_error(400, 'WIKI_ENTRY_MISSING_FIELDS', 'Título e conteúdo são obrigatórios.')
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM wiki_entries WHERE id = ?', (entry_id,))
        if not c.fetchone() or not can_read('wiki_entries', entry_id, c):
            conn.close()
            logger.warning(f'[WARN] PUT /api/wikitoca/entries/{entry_id}: nao encontrado')
            return api_error(404, 'WIKI_ENTRY_NOT_FOUND', 'Conhecimento não encontrado.')
        if not can_write('wiki_entries', entry_id, c):
            conn.close()
            return api_error(403, 'WIKI_ENTRY_FORBIDDEN', 'Sem permissão para editar este conhecimento.')
        c.execute(
            '''UPDATE wiki_entries
               SET title = ?, category = ?, content = ?, tags = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?''',
            (title, category, content, tags, entry_id)
        )
        conn.commit()
        c.execute('SELECT * FROM wiki_entries WHERE id = ?', (entry_id,))
        entry = dict_from_row(c.fetchone())
        conn.close()
        logger.debug(f'[DEBUG] PUT /api/wikitoca/entries/{entry_id} atualizado')
        return jsonify(entry)
    except Exception as e:
        logger.exception(f'[ERROR] PUT /api/wikitoca/entries/{entry_id}: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_ENTRY_UPDATE_ERROR', 'Erro ao atualizar conhecimento.', details=str(e))


@app.route('/api/wikitoca/entries/<int:entry_id>', methods=['DELETE'])
def delete_wiki_entry(entry_id):
    logger.debug(f'[DEBUG] DELETE /api/wikitoca/entries/{entry_id} chamado')
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM wiki_entries WHERE id = ?', (entry_id,))
        if not c.fetchone() or not can_read('wiki_entries', entry_id, c):
            conn.close()
            return api_error(404, 'WIKI_ENTRY_NOT_FOUND', 'Conhecimento não encontrado.')
        if not can_write('wiki_entries', entry_id, c):
            conn.close()
            return api_error(403, 'WIKI_ENTRY_FORBIDDEN', 'Sem permissão para excluir este conhecimento.')
        c.execute('DELETE FROM wiki_entries WHERE id = ?', (entry_id,))
        conn.commit()
        conn.close()
        logger.debug(f'[DEBUG] DELETE /api/wikitoca/entries/{entry_id} removido')
        return jsonify({'message': 'Conhecimento excluído com sucesso.'})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE /api/wikitoca/entries/{entry_id}: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_ENTRY_DELETE_ERROR', 'Erro ao excluir conhecimento.', details=str(e))


@app.route('/api/wikitoca/documents', methods=['GET'])
def list_wiki_documents():
    logger.debug('[DEBUG] GET /api/wikitoca/documents chamado')
    try:
        q = (request.args.get('q') or '').strip()
        conn = get_db()
        c = conn.cursor()
        _vw, _vp = visible_where('wiki_documents')
        if q:
            like = f'%{q}%'
            c.execute(
                f'''SELECT * FROM wiki_documents
                   WHERE (title LIKE ? OR original_name LIKE ?) AND {_vw}
                   ORDER BY updated_at DESC''',
                (like, like, *_vp)
            )
        else:
            c.execute(f'SELECT * FROM wiki_documents WHERE {_vw} ORDER BY updated_at DESC', _vp)
        rows = [dict_from_row(r) for r in c.fetchall()]
        conn.close()
        logger.debug(f'[DEBUG] GET /api/wikitoca/documents retornando {len(rows)} documentos')
        return jsonify(rows)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/wikitoca/documents: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_DOCS_LIST_ERROR', 'Erro ao listar documentos.', details=str(e))


@app.route('/api/wikitoca/documents', methods=['POST'])
def upload_wiki_documents():
    logger.debug('[DEBUG] POST /api/wikitoca/documents chamado')
    try:
        files = request.files.getlist('files')
        logger.debug(f'[DEBUG] POST /api/wikitoca/documents arquivos recebidos: {[f.filename for f in files]}')
        if not files or all(not f.filename for f in files):
            return api_error(400, 'WIKI_DOC_NO_FILE', 'Nenhum arquivo enviado.')
        title = (request.form.get('title') or '').strip()
        prepared_files = []
        if _auth_enabled():
            for f in files:
                if not f.filename:
                    continue
                try:
                    file_bytes, _ = read_document_upload(
                        f,
                        allowed_kinds=('pdf', 'docx'),
                    )
                except DocumentProcessingError as exc:
                    return api_error(
                        exc.status,
                        exc.code,
                        str(exc),
                        hint=exc.hint,
                    )
                prepared_files.append((f, file_bytes))
        else:
            prepared_files = [(f, None) for f in files if f.filename]

        conn = get_db()
        c = conn.cursor()
        _owner_id = _acl_owner_for_insert()
        created = []
        for f, file_bytes in prepared_files:
            ext = Path(f.filename).suffix.lower()
            if ext not in ALLOWED_WIKI_EXTENSIONS:
                logger.warning(f'[WARN] POST /api/wikitoca/documents: extensao rejeitada: {ext}')
                continue
            original_name = f.filename
            safe_name = secure_filename(f'wiki_{int(datetime.now().timestamp())}_{original_name}')
            save_path = WIKI_UPLOAD_DIR / safe_name
            if file_bytes is None:
                f.save(str(save_path))
            else:
                save_path.write_bytes(file_bytes)
            file_size = save_path.stat().st_size
            file_url = f'/uploads/wikitoca/{safe_name}'
            doc_title = title or original_name
            c.execute(
                '''INSERT INTO wiki_documents (title, file_name, original_name, file_url, file_ext, file_size,
                                              owner_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                (doc_title, safe_name, original_name, file_url, ext, file_size, _owner_id)
            )
            conn.commit()
            doc_id = c.lastrowid
            c.execute('SELECT * FROM wiki_documents WHERE id = ?', (doc_id,))
            created.append(dict_from_row(c.fetchone()))
            logger.debug(f'[DEBUG] POST /api/wikitoca/documents salvo id={doc_id} nome={original_name}')
        conn.close()
        if not created:
            return api_error(400, 'WIKI_DOC_INVALID_TYPE',
                             'Nenhum arquivo válido enviado. Tipos aceitos: PDF, XLS, XLSX, DOC, DOCX.')
        return jsonify(created), 201
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/wikitoca/documents: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_DOC_UPLOAD_ERROR', 'Erro ao enviar documento.', details=str(e))


@app.route('/api/wikitoca/documents/<int:document_id>', methods=['DELETE'])
def delete_wiki_document(document_id):
    logger.debug(f'[DEBUG] DELETE /api/wikitoca/documents/{document_id} chamado')
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM wiki_documents WHERE id = ?', (document_id,))
        row = dict_from_row(c.fetchone())
        if not row or not can_read('wiki_documents', document_id, c):
            conn.close()
            return api_error(404, 'WIKI_DOC_NOT_FOUND', 'Documento não encontrado.')
        if not can_write('wiki_documents', document_id, c):
            conn.close()
            return api_error(403, 'WIKI_DOC_FORBIDDEN', 'Sem permissão para remover este documento.')
        file_path = WIKI_UPLOAD_DIR / row['file_name']
        if file_path.exists():
            file_path.unlink()
        c.execute('DELETE FROM wiki_documents WHERE id = ?', (document_id,))
        conn.commit()
        conn.close()
        logger.debug(f'[DEBUG] DELETE /api/wikitoca/documents/{document_id} removido')
        return jsonify({'message': 'Documento removido com sucesso.'})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE /api/wikitoca/documents/{document_id}: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_DOC_DELETE_ERROR', 'Erro ao remover documento.', details=str(e))


@app.route('/api/wikitoca/documents/export-zip', methods=['GET'])
def export_wiki_documents():
    try:
        from flask import send_file
        import tempfile
        conn = get_db()
        c = conn.cursor()
        _vw, _vp = visible_where('wiki_documents')
        c.execute(f'SELECT * FROM wiki_documents WHERE {_vw} ORDER BY id', _vp)
        rows = [dict_from_row(r) for r in c.fetchall()]
        conn.close()

        temp_dir = tempfile.mkdtemp()
        temp_zip = Path(temp_dir) / 'wikitoca-documentos.zip'
        manifest = []
        with zipfile.ZipFile(str(temp_zip), mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for row in rows:
                file_path = WIKI_UPLOAD_DIR / row['file_name']
                if file_path.exists():
                    zf.write(str(file_path), arcname=f"files/{row['file_name']}")
                manifest.append({
                    'title': row.get('title'),
                    'file_name': row.get('file_name'),
                    'original_name': row.get('original_name'),
                    'file_ext': row.get('file_ext'),
                })
            zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))

        return send_file(
            str(temp_zip),
            as_attachment=True,
            download_name=f'wikitoca-documentos-{datetime.now().strftime("%Y%m%d-%H%M%S")}.zip',
            mimetype='application/zip'
        )
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/wikitoca/documents/export-zip: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_DOC_EXPORT_ERROR', 'Erro ao exportar documentos.', details=str(e))


@app.route('/api/wikitoca/documents/import-zip', methods=['POST'])
def import_wiki_documents():
    try:
        if 'file' not in request.files:
            return api_error(400, 'WIKI_DOC_IMPORT_NO_FILE', 'Nenhum arquivo enviado.')
        file = request.files['file']
        if not file.filename or not file.filename.lower().endswith('.zip'):
            return api_error(400, 'WIKI_DOC_IMPORT_INVALID', 'Envie um arquivo .zip exportado pelo Toca do Coelho.')

        import tempfile
        temp_dir = tempfile.mkdtemp()
        temp_zip_path = Path(temp_dir) / 'import.zip'
        file.save(str(temp_zip_path))

        imported = []
        with zipfile.ZipFile(str(temp_zip_path), mode='r') as zf:
            names = zf.namelist()
            if 'manifest.json' not in names:
                return api_error(400, 'WIKI_DOC_IMPORT_INVALID', 'Arquivo .zip inválido: manifest.json não encontrado.')
            manifest = json.loads(zf.read('manifest.json').decode('utf-8'))

            conn = get_db()
            c = conn.cursor()
            _owner_id = _acl_owner_for_insert()
            for entry in manifest:
                original_name = entry.get('original_name') or entry.get('file_name') or 'documento'
                ext = (entry.get('file_ext') or Path(original_name).suffix.lower())
                if ext not in ALLOWED_WIKI_EXTENSIONS:
                    continue
                src_name = f"files/{entry.get('file_name')}"
                if src_name not in names:
                    continue
                safe_name = secure_filename(f'wiki_{int(datetime.now().timestamp()*1000)}_{original_name}')
                save_path = WIKI_UPLOAD_DIR / safe_name
                with zf.open(src_name) as src, open(save_path, 'wb') as dst:
                    dst.write(src.read())
                file_size = save_path.stat().st_size
                file_url = f'/uploads/wikitoca/{safe_name}'
                doc_title = entry.get('title') or original_name
                c.execute(
                    '''INSERT INTO wiki_documents (title, file_name, original_name, file_url, file_ext, file_size,
                                                  owner_id, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                    (doc_title, safe_name, original_name, file_url, ext, file_size, _owner_id)
                )
                conn.commit()
                doc_id = c.lastrowid
                c.execute('SELECT * FROM wiki_documents WHERE id = ?', (doc_id,))
                imported.append(dict_from_row(c.fetchone()))
            conn.close()

        return jsonify({'imported': len(imported), 'documents': imported}), 201
    except zipfile.BadZipFile:
        return api_error(400, 'WIKI_DOC_IMPORT_INVALID', 'Arquivo .zip inválido ou corrompido.')
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/wikitoca/documents/import-zip: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_DOC_IMPORT_ERROR', 'Erro ao importar documentos.', details=str(e))


@app.route('/api/wikitoca/entries/export-xlsx', methods=['GET'])
def export_wikitoca_xlsx():
    try:
        logger.debug('[DEBUG] GET /api/wikitoca/entries/export-xlsx chamado')
        if not OPENPYXL_AVAILABLE:
            return jsonify({'error': 'Exportação XLSX requer openpyxl instalado'}), 500
        conn = get_db()
        c = conn.cursor()
        _vw, _vp = visible_where('wiki_entries')
        c.execute(f'SELECT title, category, tags, content FROM wiki_entries WHERE {_vw} ORDER BY updated_at DESC', _vp)
        rows = c.fetchall()
        conn.close()
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from io import BytesIO
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Conhecimentos'
        headers = ['Título', 'Categoria', 'Tags', 'Descrição']
        ws.append(headers)
        header_fill = PatternFill(start_color='34D399', end_color='34D399', fill_type='solid')
        for col_idx, _ in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center')
        ws.column_dimensions['A'].width = 40
        ws.column_dimensions['B'].width = 20
        ws.column_dimensions['C'].width = 30
        ws.column_dimensions['D'].width = 60
        for row in rows:
            ws.append([
                row['title'] or '',
                row['category'] or '',
                row['tags'] or '',
                row['content'] or ''
            ])
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        from flask import send_file
        return send_file(
            output,
            as_attachment=True,
            download_name='wikitoca_conhecimentos.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/wikitoca/entries/export-xlsx: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/wikitoca/entries/template-xlsx', methods=['GET'])
def wikitoca_template_xlsx():
    try:
        logger.debug('[DEBUG] GET /api/wikitoca/entries/template-xlsx chamado')
        if not OPENPYXL_AVAILABLE:
            return jsonify({'error': 'Template XLSX requer openpyxl instalado'}), 500
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from io import BytesIO
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Conhecimentos'
        headers = ['Título', 'Categoria', 'Descrição']
        ws.append(headers)
        header_fill = PatternFill(start_color='34D399', end_color='34D399', fill_type='solid')
        for col_idx, _ in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center')
        ws.column_dimensions['A'].width = 40
        ws.column_dimensions['B'].width = 20
        ws.column_dimensions['C'].width = 60
        ws.append(['Exemplo de título', 'Comercial', 'Descreva aqui o conhecimento a ser registrado.'])
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        from flask import send_file
        return send_file(
            output,
            as_attachment=True,
            download_name='wikitoca_template.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/wikitoca/entries/template-xlsx: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/wikitoca/entries/import-xlsx', methods=['POST'])
def import_wikitoca_xlsx():
    try:
        logger.debug('[DEBUG] POST /api/wikitoca/entries/import-xlsx chamado')
        if 'file' not in request.files:
            return jsonify({'error': 'Nenhum arquivo enviado'}), 400
        file = request.files['file']
        if not file.filename or not file.filename.lower().endswith('.xlsx'):
            return jsonify({'error': 'Envie um arquivo .xlsx'}), 400
        if not OPENPYXL_AVAILABLE:
            return jsonify({'error': 'Importação XLSX requer openpyxl instalado'}), 500
        import openpyxl
        import tempfile, os as _os
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name
        try:
            wb = openpyxl.load_workbook(tmp_path, data_only=True)
            ws = wb.active
            rows_data = list(ws.iter_rows(values_only=True))
        finally:
            _os.unlink(tmp_path)
        if not rows_data:
            return jsonify({'error': 'Arquivo vazio'}), 400
        # Detectar colunas pelo cabeçalho
        header = [str(c).strip().lower() if c else '' for c in rows_data[0]]
        def find_col(names):
            for name in names:
                if name in header:
                    return header.index(name)
            return None
        col_title = find_col(['título', 'titulo', 'title'])
        col_cat = find_col(['categoria', 'category'])
        col_desc = find_col(['descrição', 'descricao', 'description', 'conteúdo', 'conteudo', 'content'])
        if col_title is None or col_desc is None:
            return jsonify({'error': 'Colunas obrigatórias não encontradas. O arquivo deve ter colunas Título e Descrição.'}), 400
        # Função de geração de tags (mesma lógica do frontend)
        stopwords = {'a','o','os','as','de','da','do','das','dos','e','é','em','no','na','nos','nas','um','uma','uns','umas','para','por','com','sem','que','se','ao','aos','à','às','ou','como','mais','menos','ja','não','sim'}
        def generate_tags(title, content):
            import re
            text = f'{title or ""} {content or ""}'.lower()
            words = re.findall(r'[a-záàãâéêíóôõúüç0-9-]{3,}', text)
            rank = {}
            for w in words:
                if w in stopwords or w.isdigit():
                    continue
                rank[w] = rank.get(w, 0) + 1
            sorted_words = sorted(rank.items(), key=lambda x: (-x[1], x[0]))
            return ', '.join(w for w, _ in sorted_words[:6])
        conn = get_db()
        c = conn.cursor()
        _owner_id = _acl_owner_for_insert()
        ok = 0
        fail = 0
        errors = []
        for idx, row in enumerate(rows_data[1:], start=2):
            try:
                title = str(row[col_title]).strip() if row[col_title] else ''
                category = str(row[col_cat]).strip() if col_cat is not None and row[col_cat] else ''
                content = str(row[col_desc]).strip() if row[col_desc] else ''
                if not title or not content:
                    fail += 1
                    errors.append(f'Linha {idx}: título ou descrição vazia')
                    continue
                tags = generate_tags(title, content)
                now = datetime.utcnow().isoformat() + 'Z'
                c.execute(
                    'INSERT INTO wiki_entries (title, category, tags, content, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (title, category, tags, content, _owner_id, now, now)
                )
                ok += 1
            except Exception as row_err:
                fail += 1
                errors.append(f'Linha {idx}: {str(row_err)}')
        conn.commit()
        conn.close()
        logger.debug(f'[DEBUG] POST /api/wikitoca/entries/import-xlsx: {ok} importados, {fail} erros')
        return jsonify({'imported': ok, 'failed': fail, 'errors': errors[:10]}), 200
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/wikitoca/entries/import-xlsx: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/uploads/wikitoca/<filename>')
def serve_wikitoca_upload(filename):
    # Documento privado: se houver linha em wiki_documents para este arquivo,
    # só serve a quem pode lê-la (dono/share/admin). Login off → can_read=True
    # (desktop serve igual). Arquivo órfão (sem linha) é servido como antes.
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM wiki_documents WHERE file_name = ?', (filename,))
    row = c.fetchone()
    if row and not can_read('wiki_documents', dict_from_row(row)['id'], c):
        conn.close()
        return api_error(404, 'WIKI_DOC_NOT_FOUND', 'Documento não encontrado.')
    conn.close()
    return send_from_directory(str(WIKI_UPLOAD_DIR), filename)
