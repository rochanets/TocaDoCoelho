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
        c.execute("SELECT DISTINCT position FROM clients WHERE position IS NOT NULL AND TRIM(position) != '' ORDER BY position COLLATE NOCASE")
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
        c.execute("SELECT DISTINCT area_of_activity FROM clients WHERE area_of_activity IS NOT NULL AND TRIM(area_of_activity) != '' ORDER BY area_of_activity COLLATE NOCASE")
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


# ─────────────────────────────────────────
#  Chamado Jurídico — Robô de preenchimento do Microsoft Forms
#  (Playwright visível: preenche, o usuário revisa/anexa e envia)
# ─────────────────────────────────────────

AUTOTOCA_CHAMADO_JURIDICO_FORMS_URL = (
    'https://forms.office.com/Pages/ResponsePage.aspx'
    '?id=Wua92O09RkOVGGcCBObhhMJ3y60yeQRBuK7vjuaEdIBUQVhXUFFBS01ZVTVDQTlOUktOTTZVVjdVViQlQCN0PWcu'
)

_forms_robot_tasks = {}
_forms_robot_tasks_lock = threading.Lock()


def _forms_robot_task_set(task_id, updates):
    with _forms_robot_tasks_lock:
        task = _forms_robot_tasks.get(task_id, {})
        task.update(updates)
        _forms_robot_tasks[task_id] = task


def _forms_robot_task_get(task_id):
    with _forms_robot_tasks_lock:
        return dict(_forms_robot_tasks.get(task_id) or {})


def _forms_robot_task_cleanup(task_id, delay=300):
    def _cleanup():
        time.sleep(delay)
        with _forms_robot_tasks_lock:
            _forms_robot_tasks.pop(task_id, None)
    threading.Thread(target=_cleanup, daemon=True).start()


# Campos de upload do Chamado Jurídico — chave usada no FormData/no histórico,
# se aceita múltiplos arquivos e se tem arquivo padrão de apoio como fallback
# quando o usuário não anexa nada.
CHAMADO_JURIDICO_FILE_FIELDS = {
    'aditivos_anteriores':        {'multiple': True,  'fallback': False},
    'contrato_anterior':          {'multiple': False, 'fallback': True},
    'minuta_cliente':             {'multiple': False, 'fallback': True},
    'aprovacao_reajuste':         {'multiple': False, 'fallback': True},
    'proposta_comercial_tecnica': {'multiple': False, 'fallback': False},
}

# Sim/Não simples, replicados 1:1 no formulário — chave -> texto da mensagem de validação
# (assinatura_plataforma não entra aqui: usa valores 'cliente'/'stefanini', validado à parte)
CHAMADO_JURIDICO_YES_NO_LABELS = {
    'havera_reajuste': 'se haverá reajuste',
    'houve_reoneracao': 'se houve reoneração',
    'inclui_novos_servicos': 'se inclui novos serviços',
    'e_prorrogacao_vigencia': 'se é prorrogação de vigência',
}


def _chamado_juridico_default_support_file():
    """Primeiro PDF da pasta 'Arquivos de Apoio' — usado como placeholder quando
    o usuário não anexa um arquivo opcional (itens 10, 13 e 15 do formulário)."""
    try:
        pdfs = sorted(AUTOTOCA_SUPPORT_FILES_DIR.glob('*.pdf'))
        return pdfs[0] if pdfs else None
    except Exception:
        return None


def _chamado_juridico_save_uploaded_files(history_id, field_key, file_storages):
    saved = []
    field_dir = CHAMADO_JURIDICO_UPLOAD_DIR / str(history_id) / field_key
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
        saved.append({'stored_path': str(target), 'original_name': f.filename})
    return saved


def _chamado_juridico_copy_history_files(history_id, field_key, entries):
    """Copia arquivos de um histórico anterior para dentro da pasta do novo
    histórico, para que cada execução fique autocontida em disco."""
    field_dir = CHAMADO_JURIDICO_UPLOAD_DIR / str(history_id) / field_key
    field_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for entry in entries:
        src = Path(entry.get('stored_path') or '')
        if not src.exists():
            continue
        target = field_dir / src.name
        counter = 1
        while target.exists():
            target = field_dir / f'{target.stem}_{counter}{target.suffix}'
            counter += 1
        shutil.copyfile(str(src), str(target))
        copied.append({'stored_path': str(target), 'original_name': entry.get('original_name') or src.name})
    return copied


def _forms_robot_build_fields(payload, files_by_field):
    """Monta os campos na ordem de matching (termos mais específicos primeiro).
    `files_by_field` é {field_key: [{'stored_path','original_name'}, ...]}.
    O item 21 do formulário nunca é respondido — nenhum campo o alveja de propósito."""

    def paths(key):
        return [e['stored_path'] for e in (files_by_field.get(key) or []) if e.get('stored_path')]

    def yes_no(key):
        return 'Sim' if (payload.get(key) or '').strip().lower() == 'sim' else 'Não'

    minuta_tipo = (payload.get('minuta_tipo') or '').strip().lower()
    # option_terms é comparado por SUBSTRING LITERAL (via get_by_role do
    # Playwright, que delega ao navegador o nome acessível de cada opção) —
    # ao contrário de 'terms' (usado só para achar a pergunta), aqui não se
    # pode normalizar acento/pontuação, tem que ser um trecho real do texto
    # visível na opção. O formulário real tem 3 opções nessa pergunta —
    # "Minuta padrão Stefanini - sem ajustes" / "- com ajustes do cliente" /
    # "Minuta enviada pelo cliente" — o termo precisa ser específico o
    # bastante para não bater nas duas primeiras ao mesmo tempo.
    minuta_option_terms = (
        ['enviada pelo cliente']
        if minuta_tipo == 'cliente'
        else ['com ajustes do cliente']
    )

    # 'q' é a posição 1-based da pergunta no formulário — usada como fallback
    # quando o texto da pergunta não bate com nenhum termo (ex.: item 15, que
    # replica o arquivo do item 13 mas cuja redação exata não é conhecida).
    # O item 21 nunca aparece aqui de propósito: não deve ser respondido.
    fields = [
        {'key': 'origem', 'label': 'Origem da Solicitação', 'type': 'radio', 'q': 1,
         'terms': ['origem da solicitacao', 'origem'],
         'option_terms': ['Pedroso']},
        {'key': 'empresa_grupo', 'label': 'Empresa do Grupo Stefanini', 'type': 'radio', 'q': 2,
         'terms': ['empresa do grupo stefanini', 'grupo stefanini', 'empresa stefanini'],
         'option_terms': ['STEFANINI CONSULTORIA']},
        {'key': 'conta', 'label': 'Conta', 'type': 'text', 'q': 3,
         'terms': ['nome da conta', 'nome do cliente', 'conta', 'cliente'],
         'value': (payload.get('conta') or '').strip()},
        {'key': 'endereco', 'label': 'Endereço', 'type': 'text', 'q': 4,
         'terms': ['endereco'],
         'value': (payload.get('endereco') or '').strip()},
        {'key': 'minuta_tipo', 'label': 'Minuta/Contrato', 'type': 'radio', 'q': 5,
         'terms': ['minuta', 'contrato original enviado', 'origem da minuta'],
         'option_terms': minuta_option_terms},
        {'key': 'opp_salesforce', 'label': 'Opp Sales Force', 'type': 'text', 'q': 6,
         'terms': ['opp sales force', 'salesforce', 'numero da oportunidade'],
         'value': (payload.get('opp_salesforce') or '').strip() or '00000'},
        {'key': 'data_assinatura', 'label': 'Data de Assinatura do Contrato Original', 'type': 'date', 'q': 7,
         'terms': ['data de assinatura', 'data assinatura', 'assinatura do contrato original'],
         'value': (payload.get('data_assinatura') or '').strip() or date.today().isoformat()},
        {'key': 'aditivos_anteriores', 'label': 'Aditivos anteriores', 'type': 'file', 'q': 8,
         'terms': ['aditivos anteriores'],
         'file_paths': paths('aditivos_anteriores')},
        {'key': 'contrato_anterior', 'label': 'Contrato Anterior', 'type': 'file', 'q': 9,
         'terms': ['contrato anterior'],
         'file_paths': paths('contrato_anterior')},
        {'key': 'minuta_cliente', 'label': 'Há minuta do cliente?', 'type': 'file', 'q': 10,
         'terms': ['ha minuta do cliente', 'minuta do cliente'],
         'file_paths': paths('minuta_cliente')},
        {'key': 'havera_reajuste', 'label': 'Haverá Reajuste?', 'type': 'radio_yes_no', 'q': 11,
         'terms': ['havera reajuste'],
         'value': yes_no('havera_reajuste')},
        {'key': 'valores_reajuste', 'label': 'Descreva os valores de reajuste', 'type': 'text', 'q': 12,
         'terms': ['descreva os valores de reajuste', 'valores de reajuste'],
         'value': (payload.get('valores_reajuste') or '').strip()},
        {'key': 'aprovacao_reajuste', 'label': 'Aprovação de Reajuste Diferente do Contrato', 'type': 'file', 'q': 13,
         'terms': ['aprovacao de reajuste diferente do contrato', 'aprovacao de reajuste'],
         'file_paths': paths('aprovacao_reajuste')},
        {'key': 'houve_reoneracao', 'label': 'Houve reoneração?', 'type': 'radio_yes_no', 'q': 14,
         'terms': ['houve reoneracao', 'reoneracao'],
         'value': yes_no('houve_reoneracao')},
        {'key': 'aprovacao_reajuste_15', 'label': 'Aprovação de Reajuste (item 15)', 'type': 'file', 'q': 15,
         'terms': [],
         'file_paths': paths('aprovacao_reajuste')},
        {'key': 'inclui_novos_servicos', 'label': 'Inclui novos serviços?', 'type': 'radio_yes_no', 'q': 16,
         'terms': ['inclui novos servicos', 'novos servicos'],
         'value': yes_no('inclui_novos_servicos')},
        {'key': 'proposta_comercial_tecnica', 'label': 'Proposta comercial e técnica', 'type': 'file', 'q': 17,
         'terms': ['proposta comercial e tecnica', 'proposta comercial'],
         'file_paths': paths('proposta_comercial_tecnica')},
        {'key': 'e_prorrogacao_vigencia', 'label': 'É prorrogação de vigência?', 'type': 'radio_yes_no', 'q': 18,
         'terms': ['prorrogacao de vigencia', 'prorrogacao'],
         'value': yes_no('e_prorrogacao_vigencia')},
        {'key': 'vigencia_datas', 'label': 'Data inicial e final da vigência', 'type': 'text', 'q': 19,
         'terms': ['data inicial e final da vigencia', 'inicial e final da vigencia'],
         'value': (payload.get('vigencia_datas') or '').strip()},
        {'key': 'assinatura_plataforma', 'label': 'Assinatura pela plataforma Stefanini ou do cliente?',
         'type': 'radio_yes_no', 'q': 20,
         'terms': ['assinatura pela plataforma', 'plataforma stefanini ou do cliente'],
         # No Toca o usuário escolhe "Stefanini" ou "Cliente"; no formulário isso vira
         # Sim (Stefanini) / Não (Cliente) — mapeamento pedido explicitamente.
         'value': 'Sim' if (payload.get('assinatura_plataforma') or '').strip().lower() == 'stefanini' else 'Não'},
        {'key': 'descricao_pedido', 'label': 'Descrição do pedido', 'type': 'text', 'q': 22,
         'terms': ['conte brevemente sobre o que se trata esse pedido', 'brevemente sobre o que se trata'],
         'value': (payload.get('descricao_pedido') or '').strip()},
    ]

    # Item 12 e 19 só existem quando a pergunta condicionante foi "Sim" — não
    # envia nada quando "Não" para não deixar rastro de resposta indevida.
    if yes_no('havera_reajuste') != 'Sim':
        fields = [f for f in fields if f['key'] != 'valores_reajuste']
    if yes_no('e_prorrogacao_vigencia') != 'Sim':
        fields = [f for f in fields if f['key'] != 'vigencia_datas']

    return fields


def _forms_robot_process_async(task_id, history_id, payload, files_by_field):
    from integrations.forms_robot import run_chamado_juridico_robot, FormsRobotError

    def on_progress(pct, step):
        _forms_robot_task_set(task_id, {'progress': pct, 'step': step})

    try:
        result = run_chamado_juridico_robot(
            AUTOTOCA_CHAMADO_JURIDICO_FORMS_URL,
            _forms_robot_build_fields(payload, files_by_field),
            on_progress,
        )
        if result.get('submitted'):
            final_step = 'Chamado Jurídico enviado com sucesso!'
        else:
            final_step = 'Preenchimento concluído — conclua a revisão e o envio na janela do robô.'
        # Log estruturado do resultado — sem isso, o log de debug exportado pelo
        # usuário só mostra os acessos HTTP, sem nenhum detalhe de qual campo
        # falhou e por quê.
        logger.info(
            '[AutoToca][FormsRobot] resultado: submitted=%s filled=%s positional=%s unmatched=%s errors=%s',
            result.get('submitted'), result.get('filled'), result.get('positional'),
            result.get('unmatched'), result.get('errors'),
        )
        _forms_robot_task_set(task_id, {
            'status': 'done', 'progress': 100, 'step': final_step,
            'result': dict(result, history_id=history_id),
        })
    except FormsRobotError as e:
        logger.warning(f'[AutoToca][FormsRobot] {e}')
        _forms_robot_task_set(task_id, {'status': 'error', 'error': str(e)})
    except Exception as e:
        logger.exception('[AutoToca][FormsRobot] Falha inesperada')
        _forms_robot_task_set(task_id, {'status': 'error', 'error': f'Falha inesperada no robô: {e}'})
    finally:
        _forms_robot_task_cleanup(task_id)


@app.route('/api/autotoca/chamado-juridico/robot', methods=['POST'])
def autotoca_chamado_juridico_robot():
    try:
        form = request.form
        payload = {
            'conta': (form.get('conta') or '').strip(),
            'razao_social': (form.get('razao_social') or '').strip(),
            'cnpj': (form.get('cnpj') or '').strip(),
            'endereco': (form.get('endereco') or '').strip(),
            'minuta_tipo': (form.get('minuta_tipo') or '').strip(),
            'opp_salesforce': (form.get('opp_salesforce') or '').strip(),
            'data_assinatura': (form.get('data_assinatura') or '').strip(),
            'havera_reajuste': (form.get('havera_reajuste') or '').strip(),
            'valores_reajuste': (form.get('valores_reajuste') or '').strip(),
            'houve_reoneracao': (form.get('houve_reoneracao') or '').strip(),
            'inclui_novos_servicos': (form.get('inclui_novos_servicos') or '').strip(),
            'e_prorrogacao_vigencia': (form.get('e_prorrogacao_vigencia') or '').strip(),
            'vigencia_datas': (form.get('vigencia_datas') or '').strip(),
            'assinatura_plataforma': (form.get('assinatura_plataforma') or '').strip(),
            'descricao_pedido': (form.get('descricao_pedido') or '').strip(),
        }

        errors = []
        if not payload['conta']:
            errors.append('Conta é obrigatória.')
        if not payload['endereco']:
            errors.append('Endereço é obrigatório.')
        if payload['minuta_tipo'] not in ('cliente', 'stefanini'):
            errors.append('Informe se a Minuta/Contrato é do cliente ou da Stefanini.')
        if payload['assinatura_plataforma'] not in ('cliente', 'stefanini'):
            errors.append('Informe se a assinatura é pela plataforma Stefanini ou do cliente.')
        if not payload['descricao_pedido']:
            errors.append('Descreva brevemente o pedido.')
        for key, label in CHAMADO_JURIDICO_YES_NO_LABELS.items():
            if payload[key].lower() not in ('sim', 'nao', 'não'):
                errors.append(f'Responda {label}.')
        if payload['havera_reajuste'].lower() == 'sim' and not payload['valores_reajuste']:
            errors.append('Descreva os valores de reajuste.')
        if payload['e_prorrogacao_vigencia'].lower() == 'sim' and not payload['vigencia_datas']:
            errors.append('Informe a data inicial e final da vigência.')

        reuse_history_id = (form.get('reuse_history_id') or '').strip()
        reuse_row = None
        if reuse_history_id:
            conn = get_db()
            c = conn.cursor()
            c.execute('SELECT * FROM chamado_juridico_history WHERE id = ?', (reuse_history_id,))
            row = c.fetchone()
            conn.close()
            if row:
                reuse_row = dict_from_row(row)

        reuse_files = json.loads(reuse_row['files_json']) if reuse_row else {}
        # Reaproveitar um arquivo do histórico é opt-in por campo — o usuário
        # precisa clicar explicitamente no anexo antigo para "anexá-lo" de
        # novo. Sem isso, um campo com histórico E um upload novo acabava
        # enviando os dois arquivos ao mesmo tempo para o Forms.
        try:
            reuse_field_keys = set(json.loads(form.get('reuse_fields') or '[]'))
        except Exception:
            reuse_field_keys = set()

        if errors:
            return jsonify({'error': ' '.join(errors)}), 400

        with _forms_robot_tasks_lock:
            busy = any(t.get('status') == 'processing' for t in _forms_robot_tasks.values())
        if busy:
            return jsonify({'error': 'O robô já está em execução. Aguarde ele terminar.'}), 409

        # Cria a linha do histórico já para ter um id — os arquivos ficam
        # organizados em uploads/autotoca/chamado-juridico/<history_id>/<campo>/
        conn = get_db()
        c = conn.cursor()
        c.execute(
            'INSERT INTO chamado_juridico_history (conta, payload_json, files_json) VALUES (?, ?, ?)',
            (payload['conta'], json.dumps(payload, ensure_ascii=False), '{}')
        )
        conn.commit()
        history_id = c.lastrowid

        files_by_field = {}
        for field_key, opts in CHAMADO_JURIDICO_FILE_FIELDS.items():
            uploads = [f for f in request.files.getlist(field_key) if f and f.filename]
            if uploads:
                files_by_field[field_key] = _chamado_juridico_save_uploaded_files(history_id, field_key, uploads)
            elif field_key in reuse_field_keys and reuse_files.get(field_key):
                files_by_field[field_key] = _chamado_juridico_copy_history_files(
                    history_id, field_key, reuse_files[field_key]
                )
            elif opts['fallback']:
                default_file = _chamado_juridico_default_support_file()
                if default_file:
                    files_by_field[field_key] = [{
                        'stored_path': str(default_file), 'original_name': default_file.name,
                    }]

        proposta_files = files_by_field.get('proposta_comercial_tecnica') or []
        proposta_original_name = proposta_files[0]['original_name'] if proposta_files else None

        c.execute(
            'UPDATE chamado_juridico_history SET files_json = ?, proposta_original_name = ? WHERE id = ?',
            (json.dumps(files_by_field, ensure_ascii=False), proposta_original_name, history_id)
        )
        conn.commit()
        conn.close()

        task_id = uuid.uuid4().hex
        _forms_robot_task_set(task_id, {'status': 'processing', 'step': 'Iniciando o robô...', 'progress': 5})
        threading.Thread(
            target=_forms_robot_process_async, args=(task_id, history_id, payload, files_by_field), daemon=True
        ).start()
        return jsonify({'task_id': task_id, 'history_id': history_id}), 202
    except Exception as e:
        logger.exception(f'[AutoToca] POST /api/autotoca/chamado-juridico/robot: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/chamado-juridico/robot/tasks/<task_id>', methods=['GET'])
def autotoca_chamado_juridico_robot_task(task_id):
    task = _forms_robot_task_get(task_id)
    if not task:
        return jsonify({'error': 'Tarefa não encontrada.'}), 404
    return jsonify(task)


def _chamado_juridico_upload_url(stored_path):
    try:
        rel = Path(stored_path).resolve().relative_to(AUTOTOCA_UPLOAD_DIR.resolve())
        return f'/uploads/autotoca/{urllib.parse.quote(str(rel).replace(os.sep, "/"))}'
    except Exception:
        return None


@app.route('/api/autotoca/chamado-juridico/history', methods=['GET'])
def autotoca_chamado_juridico_history_list():
    conn = get_db()
    c = conn.cursor()
    c.execute(
        'SELECT id, conta, proposta_original_name, created_at FROM chamado_juridico_history '
        'ORDER BY created_at DESC LIMIT 50'
    )
    rows = [dict_from_row(r) for r in c.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route('/api/autotoca/chamado-juridico/history/<int:history_id>', methods=['GET'])
def autotoca_chamado_juridico_history_get(history_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM chamado_juridico_history WHERE id = ?', (history_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Histórico não encontrado.'}), 404
    entry = dict_from_row(row)
    files = json.loads(entry.get('files_json') or '{}')
    files_view = {
        key: [{'original_name': e.get('original_name'), 'url': _chamado_juridico_upload_url(e.get('stored_path'))}
              for e in entries]
        for key, entries in files.items()
    }
    return jsonify({
        'id': entry['id'],
        'payload': json.loads(entry.get('payload_json') or '{}'),
        'files': files_view,
    })


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


@app.route('/uploads/autotoca/<path:filename>')
def serve_autotoca_upload(filename):
    return send_from_directory(str(AUTOTOCA_UPLOAD_DIR), filename)
