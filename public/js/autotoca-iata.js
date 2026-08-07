        // ─── iAta (AutoToca) ───────────────────────────────────────────────
        let iataRecords = [];

        async function loadIAta() {
            const container = document.getElementById('iataContent');
            if (!container) return;
            container.innerHTML = '<p style="color:#6b7280;">Carregando histórico de atas...</p>';
            try {
                const response = await fetch(`${API_BASE}/autotoca/iata`);
                const payload = await response.json().catch(() => []);
                if (!response.ok) throw new Error(payload.error || 'Erro ao carregar atas.');
                iataRecords = Array.isArray(payload) ? payload : [];
                renderIAtaHistory(iataRecords);
            } catch (error) {
                container.innerHTML = `<div class="alert alert-error" style="display:block;">${escapeHtml(error.message || 'Erro ao carregar histórico de atas.')}</div>`;
            }
        }

        function renderIAtaHistory(records = []) {
            const container = document.getElementById('iataContent');
            if (!container) return;
            if (!records.length) {
                container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">📋</div><h3>Nenhuma ata gerada</h3><p>Clique em "+ Nova Ata" para gerar a ata de uma reunião com IA.</p></div>`;
                return;
            }
            container.innerHTML = records.map(record => {
                const rid = Number(record.id);
                const quando = [record.meeting_date, record.meeting_time].filter(Boolean).join(' ');
                const aviso = record.reparse_failed
                    ? `<p style="margin:4px 0 0; font-size:12px; color:#b45309;"><i class="fas fa-exclamation-triangle"></i> Estrutura desatualizada após edição manual</p>`
                    : '';
                const editada = record.body_edited
                    ? `<span class="history-meta" style="font-weight:400; opacity:.75;">· editada</span>` : '';
                // Cores vêm das variáveis do tema escolhido pelo usuário
                // (`--t-primary`, `--t-card-border`) e das classes que os
                // outros módulos já usam — nada de verde/cinza cravado, que
                // ficava ilegível em temas escuros como o blue-space.
                return `
                    <div class="history-item" style="margin-bottom:10px;">
                        <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:10px;">
                            <div style="flex:1; min-width:0; cursor:pointer;" onclick="viewIAtaFull(${rid})">
                                <div style="display:flex; align-items:center; gap:8px; color:var(--t-primary); flex-wrap:wrap;">
                                    <i class="fas fa-file-alt"></i>
                                    <h3 style="margin:0; font-size:15px; color:var(--t-primary);">${escapeHtml(record.title || 'Ata sem título')}</h3>
                                    <span class="history-meta" style="margin:0; font-weight:400;">${escapeHtml(quando)}</span>
                                    ${editada}
                                </div>
                                ${aviso}
                            </div>
                            <div style="display:flex; gap:6px; flex-shrink:0;">
                                <button class="btn btn-secondary btn-small" onclick="viewIAtaFull(${rid})" title="Abrir"><i class="fas fa-eye"></i></button>
                                <button class="btn btn-danger btn-small" onclick="deleteIAtaRecord(${rid})" title="Excluir"><i class="fas fa-trash"></i></button>
                            </div>
                        </div>
                    </div>`;
            }).join('');
        }

        async function deleteIAtaRecord(rid) {
            if (!await uiConfirm('Deseja realmente excluir esta ata?', 'Excluir Ata')) return;
            try {
                const response = await fetch(`${API_BASE}/autotoca/iata/${rid}`, { method: 'DELETE' });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.error || 'Erro ao excluir ata.');
                showSuccess('Ata excluída com sucesso.');
                await loadIAta();
            } catch (error) {
                showError(error.message || 'Erro ao excluir ata.');
            }
        }

        // ─── iAta — modal "Nova Ata" (base + progresso) ───────────────────
        function openIAtaModal() {
            const modalId = 'iataNewModal';
            document.getElementById(modalId)?.remove();
            const opcoes = iataRecords.map(r =>
                `<option value="${Number(r.id)}">${escapeHtml(r.title || 'Ata sem título')}${r.meeting_date ? ' — ' + escapeHtml(r.meeting_date) : ''}</option>`
            ).join('');
            const html = `
                <div class="modal active" id="${modalId}">
                    <div class="modal-content" style="max-width:680px;">
                        <div class="modal-header">
                            <h2 class="modal-title"><i class="fas fa-file-alt"></i> Nova Ata — iAta</h2>
                            <button class="modal-close" id="iataModalCloseBtn" onclick="document.getElementById('${modalId}').remove()">&#215;</button>
                        </div>
                        <div id="iataFormArea">
                            <div class="form-group">
                                <label>Base da ata</label>
                                <div style="display:flex; flex-direction:column; gap:8px; font-size:13px;">
                                    ${[['historico', 'Continuar a partir de uma ata do histórico', true],
                                       ['upload', 'Enviar o arquivo da ata anterior', false],
                                       ['zero', 'Começar uma ata totalmente nova', false]].map(([valor, texto, marcado]) => `
                                    <label style="display:flex; align-items:center; gap:8px; cursor:pointer; margin:0;">
                                        <input type="radio" name="iataBase" value="${valor}"${marcado ? ' checked' : ''} onchange="_iataToggleBase()" style="width:auto; margin:0; flex-shrink:0;">
                                        <span>${texto}</span>
                                    </label>`).join('')}
                                </div>
                            </div>
                            <div class="form-group" id="iataBaseHistorico">
                                <label>Ata anterior</label>
                                <select id="iataPreviousSelect">${opcoes || '<option value="">Nenhuma ata salva ainda</option>'}</select>
                            </div>
                            <div class="form-group" id="iataBaseUpload" style="display:none;">
                                <label>Arquivo da ata anterior</label>
                                <input id="iataPreviousFile" type="file" accept=".pdf,.docx,.txt,.vtt,.srt">
                            </div>
                            <hr style="border:none; border-top:1px solid #e5e7eb; margin:16px 0;">
                            <div class="form-group">
                                <label>Arquivo da reunião de agora</label>
                                <input id="iataFileInput" type="file" accept=".pdf,.doc,.docx,.txt,.vtt,.srt,.csv,text/plain,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document">
                                <small style="color:#9ca3af; font-size:11px; display:block; margin-top:4px;">PDF, DOCX, TXT, VTT (Teams), SRT</small>
                            </div>
                            <div class="form-group">
                                <label>OU cole o texto da reunião</label>
                                <textarea id="iataRawTextInput" rows="7" placeholder="Cole aqui a transcrição, notas ou chat da reunião..."></textarea>
                            </div>
                            <div class="form-group">
                                <label style="display:flex; align-items:center; gap:8px; font-size:13px; cursor:pointer; margin:0;">
                                    <input type="checkbox" id="iataWithInsights" style="width:auto; margin:0; flex-shrink:0;">
                                    <span>Incluir insights de negócio (cruzamento com as Soluções STF)</span>
                                </label>
                            </div>
                        </div>
                        <div id="iataProgressArea" style="display:none; padding:20px 4px 12px;">
                            <div style="font-size:13px; color:#6b7280; margin-bottom:12px; text-align:center;" id="iataProgressStep">Iniciando...</div>
                            <div style="position:relative; background:#d1fae5; border-radius:99px; height:12px; overflow:visible; margin:0 16px 6px;">
                                <div id="iataProgressBar" style="position:relative; height:100%; width:5%; background:linear-gradient(90deg,#059669,#10b981,#34d399); border-radius:99px; transition:width .6s ease;">
                                    <img src="/images/coelho-correndo.webp" class="coelho-run" alt="">
                                </div>
                            </div>
                            <div style="display:flex; justify-content:flex-end; padding:0 16px;">
                                <div style="font-size:11px; color:#6b7280;" id="iataProgressPct">5%</div>
                            </div>
                        </div>
                        <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:8px;">
                            <button id="iataCancelBtn" class="btn btn-secondary" onclick="document.getElementById('${modalId}').remove()">Cancelar</button>
                            <button id="iataSubmitBtn" class="btn btn-auto-mapping btn-small" onclick="submitIAta()">
                                <span class="ai-star-icon">✦</span> Gerar Ata com IA
                            </button>
                        </div>
                    </div>
                </div>`;
            document.body.insertAdjacentHTML('beforeend', html);
        }

        function _iataToggleBase() {
            const escolha = document.querySelector('input[name="iataBase"]:checked')?.value;
            document.getElementById('iataBaseHistorico').style.display = escolha === 'historico' ? '' : 'none';
            document.getElementById('iataBaseUpload').style.display = escolha === 'upload' ? '' : 'none';
        }

        function _iataSetProgress(pct, step) {
            const bar = document.getElementById('iataProgressBar');
            const stepEl = document.getElementById('iataProgressStep');
            const pctEl = document.getElementById('iataProgressPct');
            if (bar) bar.style.width = Math.max(5, pct) + '%';
            if (stepEl) stepEl.textContent = step || '';
            if (pctEl) pctEl.textContent = Math.round(pct) + '%';
        }

        // Aviso pendente de mostrar assim que a próxima ata (geração ou edição)
        // for aberta em viewIAtaFull — usado para o `warning` da task de geração
        // (ata anterior sumida/ilegível) e para `positional_matches` de um PUT de
        // corpo: nenhum dos dois pode ficar só num toast de 3s que some sozinho,
        // porque o usuário precisa decidir algo a partir dele (reconferir vínculo,
        // saber que não houve continuidade).
        let _iataPendingWarning = null;

        async function submitIAta() {
            const file = document.getElementById('iataFileInput')?.files?.[0] || null;
            const rawText = (document.getElementById('iataRawTextInput')?.value || '').trim();
            if (!file && !rawText) {
                showError('Envie um arquivo ou cole o texto da reunião.');
                return;
            }
            const base = document.querySelector('input[name="iataBase"]:checked')?.value || 'zero';
            const previousId = document.getElementById('iataPreviousSelect')?.value;
            const previousFile = document.getElementById('iataPreviousFile')?.files?.[0] || null;
            if (base === 'historico' && !previousId) {
                showError('Escolha a ata anterior ou marque "Começar uma ata totalmente nova".');
                return;
            }
            if (base === 'upload' && !previousFile) {
                showError('Envie o arquivo da ata anterior.');
                return;
            }

            const btn = document.getElementById('iataSubmitBtn');
            const cancelBtn = document.getElementById('iataCancelBtn');
            const formArea = document.getElementById('iataFormArea');
            const progressArea = document.getElementById('iataProgressArea');
            if (btn) btn.style.display = 'none';
            if (cancelBtn) cancelBtn.style.display = 'none';
            if (formArea) formArea.style.display = 'none';
            if (progressArea) progressArea.style.display = 'block';
            _iataSetProgress(5, 'Enviando arquivo...');

            try {
                const fd = new FormData();
                if (file) fd.append('meeting_file', file);
                if (rawText) fd.append('raw_text', rawText);
                if (base === 'historico') fd.append('previous_record_id', previousId);
                if (base === 'upload') fd.append('previous_file', previousFile);
                fd.append('with_insights', document.getElementById('iataWithInsights')?.checked ? '1' : '0');

                const response = await fetch(`${API_BASE}/autotoca/iata`, { method: 'POST', body: fd });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.error || 'Erro ao iniciar processamento.');
                const taskId = payload.task_id;
                if (!taskId) throw new Error('Resposta inesperada do servidor.');

                // Botões Minimizar / Cancelar no topo da barra de progresso —
                // mesmo padrão da sincronização de e-mail/WhatsApp: minimizar
                // fecha o modal e o BgTaskManager segue acompanhando no
                // indicador flutuante; ao concluir, a ata abre sozinha (ou
                // fica na lista de concluídas se o usuário trocou de aba).
                _attachBgTaskControls(
                    progressArea, taskId,
                    () => document.getElementById('iataNewModal')?.remove(),
                    () => {
                        // Cancelar: devolve o formulário preenchido para o
                        // usuário ajustar e tentar de novo, em vez de fechar.
                        if (btn) btn.style.display = '';
                        if (cancelBtn) cancelBtn.style.display = '';
                        if (formArea) formArea.style.display = '';
                        if (progressArea) progressArea.style.display = 'none';
                    }
                );

                BgTaskManager.register(
                    taskId,
                    `${API_BASE}/autotoca/iata/tasks/${taskId}`,
                    'Gerando Ata com IA',
                    (typeof _currentTab !== 'undefined' ? _currentTab : 'autotoca'),
                    (record, status) => {
                        document.getElementById('iataNewModal')?.remove();
                        showSuccess('Ata gerada com sucesso!');
                        // `status.warning` cobre a ata anterior escolhida (histórico ou
                        // arquivo) que sumiu/não pôde ser lida — o backend termina com
                        // sucesso mesmo assim, mas sem isto o usuário acharia que teve
                        // continuidade com a ata anterior quando não teve.
                        _iataPendingWarning = (status && status.warning) || null;
                        loadIAta().then(() => { if (record && record.id) viewIAtaFull(record.id); });
                    },
                    (errMsg) => {
                        showError(errMsg || 'Erro ao processar reunião com IA.');
                        if (btn) btn.style.display = '';
                        if (cancelBtn) cancelBtn.style.display = '';
                        if (formArea) formArea.style.display = '';
                        if (progressArea) progressArea.style.display = 'none';
                    },
                    (pct, step) => _iataSetProgress(pct, step)
                );
            } catch (error) {
                showError(error.message || 'Erro ao processar reunião com IA.');
                if (btn) btn.style.display = '';
                if (cancelBtn) cancelBtn.style.display = '';
                if (formArea) formArea.style.display = '';
                if (progressArea) progressArea.style.display = 'none';
            }
        }

        // ─── iAta — visualização, edição e envio por e-mail ────────────────
        let _iataCurrent = null;

        async function viewIAtaFull(rid) {
            document.getElementById('iataViewModal')?.remove();
            try {
                const response = await fetch(`${API_BASE}/autotoca/iata/${rid}`);
                const record = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(record.error || 'Erro ao abrir a ata.');
                _iataCurrent = record;
                document.body.insertAdjacentHTML('beforeend', _renderIAtaViewModal(record));
            } catch (error) {
                showError(error.message || 'Erro ao abrir a ata.');
            }
        }

        // Atas geradas antes desta feature (`format_version` 1) não têm
        // `body_markdown` nem hierarquia: o conteúdo vive em `ata_json`, no
        // formato antigo (summary/key_points/decisions/next_steps/...). O
        // visualizador que lia esse formato saiu junto com o módulo velho, e
        // sem o de baixo o usuário abriria um registro histórico real e veria
        // um editor em branco. São dados dele: exibimos como somente leitura,
        // sem reescrever nada no banco.
        function _iataEhLegada(record) {
            const temCorpoNovo = (record.body_markdown || '').trim().length > 0;
            const temHierarquia = (record.managers || []).length > 0;
            return !temCorpoNovo && !temHierarquia
                && !!record.ata_json && Object.keys(record.ata_json).length > 0;
        }

        function _renderIAtaLegada(record) {
            const a = record.ata_json || {};
            const partes = [];
            const bloco = (titulo, conteudo) => {
                if (!conteudo) return;
                partes.push(`<div style="margin-bottom:14px;"><div style="font-weight:600; color:#065f46; font-size:13px; margin-bottom:4px;">${escapeHtml(titulo)}</div>${conteudo}</div>`);
            };
            const paragrafo = txt => (String(txt || '').trim()
                ? `<div style="font-size:13px; line-height:1.6; color:#374151; white-space:pre-wrap;">${escapeHtml(String(txt).trim())}</div>` : '');
            const lista = itens => {
                const li = (itens || []).map(i => {
                    const txt = (i && typeof i === 'object')
                        ? [i.action, i.responsible, i.deadline].filter(Boolean).join(' — ')
                        : String(i || '');
                    return txt.trim() ? `<li style="margin:2px 0;">${escapeHtml(txt.trim())}</li>` : '';
                }).join('');
                return li ? `<ul style="margin:4px 0; padding-left:20px; font-size:13px; line-height:1.6; color:#374151;">${li}</ul>` : '';
            };

            const quando = [a.meeting_date || record.meeting_date, a.meeting_time || record.meeting_time]
                .filter(Boolean).join(' ');
            const participantes = (a.participants || record.participants || [])
                .map(p => (p && typeof p === 'object') ? [p.name, p.role].filter(Boolean).join(' (') + (p.role ? ')' : '') : String(p || ''))
                .filter(Boolean).join(', ');

            bloco('Data e horário', paragrafo(quando));
            bloco('Local', paragrafo(a.location));
            bloco('Tema', paragrafo(a.topic || record.topic));
            bloco('Participantes', paragrafo(participantes));
            bloco('Objetivo', paragrafo(a.objective));
            bloco('Resumo', paragrafo(a.summary));
            bloco('Pauta', lista(a.agenda));
            bloco('Pontos-chave', lista(a.key_points));
            bloco('Decisões', lista(a.decisions));
            bloco('Próximos passos', lista(a.next_steps));
            bloco('Observações', paragrafo(a.observations));

            const insights = (record.insights_json && record.insights_json.insights) || [];
            bloco('Insights de negócio', lista(insights.map(i =>
                [i.pain, i.matched_offer || 'sem solução mapeada', i.observation].filter(Boolean).join(' → '))));

            return `
                <div style="background:#f9fafb; border:1px solid #e5e7eb; border-radius:8px; padding:10px 12px; margin-bottom:12px; font-size:12px; color:#4b5563;">
                    <i class="fas fa-clock-rotate-left"></i> Ata em formato antigo, anterior ao modelo de Gerente Comercial → Conta → Oportunidade. Exibida somente para leitura — não é possível editar nem enviar por e-mail.
                </div>
                <div style="border:1px solid #e5e7eb; border-radius:8px; padding:14px; max-height:60vh; overflow:auto; background:#fff;">
                    ${partes.join('') || '<div style="font-size:13px; color:#6b7280;">Esta ata não tem conteúdo registrado.</div>'}
                </div>`;
        }

        function _renderIAtaViewModal(record) {
            const aviso = record.reparse_failed
                ? `<div style="background:#fef2f2; border:1px solid #fecaca; border-radius:8px; padding:10px 12px; margin-bottom:12px; font-size:12px; color:#991b1b;"><i class="fas fa-exclamation-triangle"></i> O texto foi salvo, mas a estrutura não pôde ser atualizada — a próxima ata pode não carregar os status corretamente.</div>`
                : '';
            // Aviso de continuidade perdida (ata anterior sumida/ilegível) ou de
            // casamento por posição num PUT anterior — mostrado uma única vez.
            const avisoPendente = _iataPendingWarning
                ? `<div style="background:#fffbeb; border:1px solid #fcd34d; border-radius:8px; padding:10px 12px; margin-bottom:12px; font-size:12px; color:#92400e;"><i class="fas fa-exclamation-triangle"></i> ${escapeHtml(_iataPendingWarning)}</div>`
                : '';
            _iataPendingWarning = null;
            const contas = (record.managers || []).flatMap(m => (m.accounts || []).map(a => ({ manager: m.name, ...a })));
            const revisao = contas.filter(a => a.account_id && !a.match_confirmed).map(a => `
                <div style="display:flex; align-items:center; gap:8px; font-size:12px; margin:4px 0; flex-wrap:wrap;">
                    <span>Conta <strong>${escapeHtml(a.name)}</strong> → sugerida como conta do CRM (${escapeHtml(a.match_confidence || '')})</span>
                    <button class="btn btn-secondary btn-small" onclick="confirmIAtaAccount(${Number(record.id)}, ${Number(a.id)}, ${Number(a.account_id)})">Confirmar</button>
                    <button class="btn btn-secondary btn-small" onclick="confirmIAtaAccount(${Number(record.id)}, ${Number(a.id)}, null)">Descartar</button>
                </div>`).join('');
            return `
                <div class="modal active" id="iataViewModal">
                    <div class="modal-content" style="max-width:860px;">
                        <div class="modal-header">
                            <h2 class="modal-title"><i class="fas fa-file-alt"></i> ${escapeHtml(record.title || 'Ata')}</h2>
                            <button class="modal-close" onclick="document.getElementById('iataViewModal').remove()">&#215;</button>
                        </div>
                        ${avisoPendente}
                        ${aviso}
                        ${revisao ? `<div style="background:#fffbeb; border:1px solid #fcd34d; border-radius:8px; padding:10px; margin-bottom:12px;"><div style="font-weight:600; font-size:13px; color:#92400e; margin-bottom:4px;">Contas sugeridas pela IA — confirme o vínculo</div>${revisao}</div>` : ''}
                        ${_iataEhLegada(record) ? _renderIAtaLegada(record) : `
                        <textarea id="iataBodyEditor" rows="22" style="width:100%; font-family:Consolas,monospace; font-size:13px; line-height:1.5;">${escapeHtml(record.body_markdown || '')}</textarea>`}
                        <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:12px;">
                            <button class="btn btn-secondary" onclick="document.getElementById('iataViewModal').remove()">Fechar</button>
                            ${_iataEhLegada(record) ? '' : `
                            <button class="btn btn-secondary" onclick="saveIAtaBody(${Number(record.id)})"><i class="fas fa-save"></i> Salvar texto</button>
                            <button class="btn btn-auto-mapping btn-small" onclick="openIAtaEmailModal(${Number(record.id)})"><span class="ai-star-icon">✦</span> Enviar por e-mail</button>`}
                        </div>
                    </div>
                </div>`;
        }

        async function confirmIAtaAccount(rid, iataAccountId, accountId) {
            try {
                const response = await fetch(`${API_BASE}/autotoca/iata/${rid}/accounts/${iataAccountId}/link`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ account_id: accountId })
                });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.error || 'Erro ao vincular a conta.');
                showSuccess('Vínculo atualizado.');
                await viewIAtaFull(rid);
            } catch (error) {
                showError(error.message || 'Erro ao vincular a conta.');
            }
        }

        async function saveIAtaBody(rid) {
            const body = document.getElementById('iataBodyEditor')?.value || '';
            if (!body.trim()) { showError('A ata não pode ficar vazia.'); return; }
            try {
                const response = await fetch(`${API_BASE}/autotoca/iata/${rid}/body`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ body_markdown: body })
                });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.error || 'Erro ao salvar a ata.');

                if (payload.reparse_failed) {
                    showError('Texto salvo, mas a estrutura não pôde ser atualizada. A próxima ata pode não carregar os status corretamente.');
                } else {
                    showSuccess('Ata atualizada.');
                }

                // `positional_matches`: itens cujo vínculo foi rebaixado de confirmado
                // para sugestão porque o usuário renomeou algo no texto — o backend
                // inteiro foi desenhado para não deixar isso silencioso (mesmo
                // princípio do `positional` do robô de formulário), então isto vira
                // o aviso mostrado ao reabrir a ata logo abaixo.
                const pm = payload.positional_matches || {};
                const avisos = [];
                (pm.accounts || []).forEach(a => avisos.push(
                    `Conta "${a.name}" (antes "${a.previous_name}") foi casada por posição — o vínculo com o CRM voltou a ser sugestão, confira.`));
                (pm.opportunities || []).forEach(o => avisos.push(
                    `Oportunidade "${o.name}" da conta "${o.account}" (antes "${o.previous_name}") foi casada por posição — confira o histórico dela.`));
                // `lost`: a conta antiga tinha vínculo CONFIRMADO por você e não
                // foi possível reencontrá-la no texto novo. Perder uma decisão
                // humana em silêncio é o pior desfecho possível aqui.
                (pm.lost || []).forEach(l => avisos.push(
                    `A conta "${l.name}"${l.manager ? ` (gerente ${l.manager})` : ''} tinha vínculo confirmado com o CRM e não foi reencontrada no texto editado — o vínculo se perdeu e precisa ser refeito.`));
                _iataPendingWarning = avisos.length ? avisos.join(' ') : null;

                await loadIAta();
                await viewIAtaFull(rid);
            } catch (error) {
                showError(error.message || 'Erro ao salvar a ata.');
            }
        }

        async function openIAtaEmailModal(rid) {
            document.getElementById('iataEmailModal')?.remove();
            let preview = { subject: '', html: '' };
            try {
                const response = await fetch(`${API_BASE}/autotoca/iata/${rid}/email/preview`);
                preview = await response.json().catch(() => ({}));
                // 422 = ata sem estrutura para montar o e-mail (legada, ou re-parse
                // sem sucesso ainda) — o backend já manda uma mensagem explicativa em
                // `error`; não precisa (nem deve) virar um erro cru na tela.
                if (!response.ok) throw new Error(preview.error || 'Não foi possível montar o preview do e-mail.');
            } catch (error) {
                showError(error.message || 'Erro ao gerar o preview do e-mail.');
                return;
            }
            // `stale`: a hierarquia está desatualizada em relação ao texto (último
            // re-parse falhou) — o preview.html abaixo ainda é HTML MONTADO PELO
            // BACKEND a partir dessa hierarquia, então é inserido direto (sem
            // escapeHtml), senão as tags viram texto visível na tela.
            const avisoStale = preview.stale
                ? `<div style="background:#fffbeb; border:1px solid #fcd34d; border-radius:8px; padding:10px 12px; margin-bottom:12px; font-size:12px; color:#92400e;"><i class="fas fa-exclamation-triangle"></i> ${escapeHtml(preview.warning || 'A estrutura desta ata está desatualizada; o e-mail pode não refletir o texto atual.')}</div>`
                : '';
            document.body.insertAdjacentHTML('beforeend', `
                <div class="modal active" id="iataEmailModal">
                    <div class="modal-content" style="max-width:820px;">
                        <div class="modal-header">
                            <h2 class="modal-title"><i class="fas fa-envelope"></i> Enviar ata por e-mail</h2>
                            <button class="modal-close" onclick="document.getElementById('iataEmailModal').remove()">&#215;</button>
                        </div>
                        ${avisoStale}
                        <div class="form-group">
                            <label>Destinatários (separados por vírgula ou ponto e vírgula)</label>
                            <input id="iataEmailTo" type="text" placeholder="fulano@empresa.com, ciclano@empresa.com">
                        </div>
                        <div class="form-group">
                            <label>Assunto</label>
                            <input id="iataEmailSubject" type="text" value="${escapeHtml(preview.subject || '')}" readonly style="background:#f3f4f6; color:#6b7280;">
                        </div>
                        <div class="form-group">
                            <label>Preview</label>
                            <div style="border:1px solid #e5e7eb; border-radius:8px; padding:12px; max-height:320px; overflow:auto; background:#fff;">${preview.html || ''}</div>
                        </div>
                        <div style="display:flex; justify-content:flex-end; gap:8px;">
                            <button class="btn btn-secondary" onclick="document.getElementById('iataEmailModal').remove()">Cancelar</button>
                            <button class="btn btn-auto-mapping btn-small" onclick="sendIAtaEmail(${Number(rid)})"><span class="ai-star-icon">✦</span> Enviar</button>
                        </div>
                    </div>
                </div>`);
        }

        async function sendIAtaEmail(rid) {
            const input = document.getElementById('iataEmailTo');
            const destinos = (input?.value || '').split(/[,;]/).map(s => s.trim()).filter(Boolean);
            if (!destinos.length) { showError('Informe ao menos um destinatário.'); return; }
            if (!await uiConfirm(`Enviar a ata para ${destinos.length} destinatário(s)?`, 'Enviar Ata')) return;
            await _iataSendEmailAttempt(rid, destinos, input, false);
        }

        // `confirmStale`: true só depois que o usuário confirmou explicitamente,
        // pelo diálogo abaixo, que quer enviar mesmo com a estrutura desatualizada
        // (409 do backend). Nunca setado como default, mesmo quando o preview já
        // mostrou o aviso — a confirmação é sempre no momento do envio.
        async function _iataSendEmailAttempt(rid, destinos, input, confirmStale) {
            try {
                const response = await fetch(`${API_BASE}/autotoca/iata/${rid}/email`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ to: destinos, confirm_stale: confirmStale })
                });
                const payload = await response.json().catch(() => ({}));

                if (response.status === 409) {
                    const seguir = await uiConfirm(
                        payload.error || 'A estrutura desta ata está desatualizada em relação ao texto. '
                            + 'O e-mail sairia com a estrutura anterior. Enviar mesmo assim?',
                        'Estrutura desatualizada');
                    if (seguir) await _iataSendEmailAttempt(rid, destinos, input, true);
                    return;
                }
                if (!response.ok) {
                    // 400 (sem destinatário), 404 (ata sumiu) ou 422 (sem estrutura
                    // para montar o e-mail) — todos com mensagem explicativa do backend.
                    throw new Error(payload.error || 'Erro ao enviar a ata.');
                }

                const falhas = (payload.results || []).filter(r => !r.ok);
                if (falhas.length) {
                    showError('Falha para: ' + falhas.map(f => `${f.to} (${f.error})`).join('; '));
                    // Deixa só quem falhou no campo: reenviar com a lista inteira
                    // duplicaria o e-mail de quem já recebeu com sucesso.
                    if (input) input.value = falhas.map(f => f.to).join(', ');
                } else {
                    showSuccess('Ata enviada.');
                    document.getElementById('iataEmailModal')?.remove();
                }
            } catch (error) {
                showError(error.message || 'Erro ao enviar a ata.');
            }
        }
