        // =====================================================
        // Ações estendidas do Radar do Dia (Bloco 9) — gatilhos com
        // pretexto pronto: rascunho por IA + envio em até 3 cliques.
        // Também usada pelos Blocos 11/12 (job_change, whitespace).
        // =====================================================

        function radarActExtended(id, type, data) {
            document.getElementById('radarDraftModal')?.remove();
            const meta = (_RADAR_TYPES[type] || { icon: '💡', label: type });
            const context = data.manchete
                ? `<div style="font-size:13px; color:#4b5563; margin-bottom:10px;"><b>${escapeHtml(data.manchete)}</b><br>${escapeHtml(data.resumo || '')}</div>`
                : '';
            const jobChangeBar = (type === 'job_change' && data.event_id)
                ? `<div style="margin-bottom:10px;">
                       <button class="btn btn-primary btn-small" onclick="radarJobChangeOpenAccount(${data.event_id}, ${id})">
                           <i class="fas fa-building-circle-check"></i> ${data.potential_new_account ? 'Criar conta' : 'Vincular conta'} + card no Kanban
                       </button>
                   </div>`
                : '';
            const html = `
                <div class="modal active" id="radarDraftModal" onclick="if(event.target===this) this.remove()">
                    <div class="modal-content" style="max-width:600px;">
                        <div class="modal-header">
                            <h2 class="modal-title">${meta.icon} ${escapeHtml(meta.label)}</h2>
                            <button class="modal-close" onclick="document.getElementById('radarDraftModal').remove()">&#215;</button>
                        </div>
                        ${context}
                        ${jobChangeBar}
                        <div class="form-group">
                            <label>Rascunho da mensagem</label>
                            <textarea id="radarDraftBody" rows="7" placeholder="Clique em 'Gerar rascunho' para a IA escrever a partir do gatilho e do histórico do contato."></textarea>
                            <small id="radarDraftClientInfo" style="color:#9ca3af; font-size:11px;"></small>
                        </div>
                        <div style="display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap;">
                            <button class="btn btn-auto-mapping btn-small" id="radarDraftGenBtn" onclick="radarGenerateDraft(${id})"><span class="ai-star-icon">✦</span> Gerar rascunho</button>
                            <div style="display:flex; gap:8px; flex-wrap:wrap;">
                                <button class="btn btn-secondary btn-small" onclick="radarDraftOpenWeb(${id})"><i class="fab fa-whatsapp"></i> Abrir no WhatsApp</button>
                                <button class="btn btn-primary btn-small" onclick="radarDraftSendWaha(${id})"><i class="fas fa-bolt"></i> Enviar via WAHA</button>
                            </div>
                        </div>
                    </div>
                </div>`;
            document.body.insertAdjacentHTML('beforeend', html);
            window._radarDraftClient = null;
            radarGenerateDraft(id);
        }

        async function radarJobChangeOpenAccount(eventId, suggestionId) {
            try {
                const resp = await fetch(`${API_BASE}/job-changes/${eventId}/open-account`, { method: 'POST' });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(payload.error || 'Erro ao criar conta/card.');
                showSuccess('Conta e card de oportunidade prontos no Kanban!');
                await fetch(`${API_BASE}/suggestions/${suggestionId}/complete`, { method: 'POST' }).catch(() => {});
                loadRadarDoDia();
            } catch (e) { showError(e.message); }
        }

        async function radarGenerateDraft(id) {
            const btn = document.getElementById('radarDraftGenBtn');
            const body = document.getElementById('radarDraftBody');
            if (btn) { btn.disabled = true; btn.innerHTML = '<span class="ai-star-icon">✦</span> Gerando... 🐇'; }
            try {
                const resp = await fetch(`${API_BASE}/suggestions/${id}/draft`, { method: 'POST' });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(payload.error || 'Erro ao gerar rascunho.');
                if (body) body.value = payload.draft || '';
                window._radarDraftClient = payload.client || null;
                const info = document.getElementById('radarDraftClientInfo');
                if (info && payload.client) {
                    info.textContent = `Contato: ${payload.client.name}${payload.client.phone ? ' · ' + payload.client.phone : ' · sem telefone cadastrado'}`;
                }
            } catch (e) {
                showError(e.message);
            } finally {
                if (btn) { btn.disabled = false; btn.innerHTML = '<span class="ai-star-icon">✦</span> Gerar rascunho'; }
            }
        }

        async function radarDraftSendWaha(id) {
            const message = (document.getElementById('radarDraftBody')?.value || '').trim();
            const client = window._radarDraftClient;
            if (!message) { showError('Gere ou escreva a mensagem primeiro.'); return; }
            if (!client || !client.phone) { showError('Contato sem telefone cadastrado.'); return; }
            try {
                const resp = await fetch(`${API_BASE}/whatsapp/send`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ client_id: client.id, phone: client.phone, message })
                });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(payload.error || 'Falha no envio via WAHA.');
                document.getElementById('radarDraftModal')?.remove();
                await fetch(`${API_BASE}/suggestions/${id}/complete`, { method: 'POST' }).catch(() => {});
                loadRadarDoDia();
                if (payload.activity_id && typeof showUndoToast === 'function') {
                    showUndoToast('Mensagem enviada — atividade registrada. Desfazer registro?', async () => {
                        try { await fetch(`${API_BASE}/atividades/${payload.activity_id}`, { method: 'DELETE' }); } catch (e) {}
                    });
                } else {
                    showSuccess('Mensagem enviada!');
                }
            } catch (e) { showError(e.message); }
        }

        async function radarDraftOpenWeb(id) {
            const message = (document.getElementById('radarDraftBody')?.value || '').trim();
            const client = window._radarDraftClient;
            if (!message) { showError('Gere ou escreva a mensagem primeiro.'); return; }
            const phone = normalizePhoneForWhatsapp((client && client.phone) || '');
            if (!phone) { showError('Contato sem telefone válido.'); return; }
            window.open(`https://web.whatsapp.com/send?phone=${encodeURIComponent(phone)}&text=${encodeURIComponent(message)}`, '_blank');
            // registra a atividade e conclui a sugestão
            try {
                const fd = new FormData();
                fd.set('client_id', client.id);
                fd.set('contact_type', 'WhatsApp');
                fd.set('information', `Mensagem enviada (gatilho do Radar):\n${message.slice(0, 400)}`);
                const resp = await fetch(`${API_BASE}/atividades`, { method: 'POST', body: fd });
                const payload = await resp.json().catch(() => ({}));
                document.getElementById('radarDraftModal')?.remove();
                await fetch(`${API_BASE}/suggestions/${id}/complete`, { method: 'POST' }).catch(() => {});
                loadRadarDoDia();
                if (payload.id && typeof showUndoToast === 'function') {
                    showUndoToast('Atividade registrada — desfazer', async () => {
                        try { await fetch(`${API_BASE}/atividades/${payload.id}`, { method: 'DELETE' }); } catch (e) {}
                    });
                }
            } catch (e) { /* atividade é melhor esforço aqui */ }
        }
