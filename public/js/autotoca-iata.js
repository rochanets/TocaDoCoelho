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
