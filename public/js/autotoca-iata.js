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
                    ? `<span style="font-size:11px; color:#6b7280;">· editada</span>` : '';
                return `
                    <div class="history-item" style="border:1px solid rgba(16,185,129,.25); border-radius:12px; margin-bottom:10px; background:#fff; padding:12px;">
                        <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:10px;">
                            <div style="flex:1; min-width:0; cursor:pointer;" onclick="viewIAtaFull(${rid})">
                                <div style="display:flex; align-items:center; gap:8px; color:#065f46; flex-wrap:wrap;">
                                    <i class="fas fa-file-alt"></i>
                                    <h3 style="margin:0; font-size:15px;">${escapeHtml(record.title || 'Ata sem título')}</h3>
                                    <span style="font-size:12px; color:#6b7280; font-weight:400;">${escapeHtml(quando)}</span>
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
                                <div style="display:flex; flex-direction:column; gap:6px; font-size:13px;">
                                    <label><input type="radio" name="iataBase" value="historico" checked onchange="_iataToggleBase()"> Continuar a partir de uma ata do histórico</label>
                                    <label><input type="radio" name="iataBase" value="upload" onchange="_iataToggleBase()"> Enviar o arquivo da ata anterior</label>
                                    <label><input type="radio" name="iataBase" value="zero" onchange="_iataToggleBase()"> Começar uma ata totalmente nova</label>
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
                                <label style="font-size:13px;"><input type="checkbox" id="iataWithInsights" checked> Incluir insights de negócio (cruzamento com as Soluções STF)</label>
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
