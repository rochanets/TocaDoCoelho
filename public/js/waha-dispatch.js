        // =====================================================
        // Envio direto via WAHA (Bloco 8) — despacho da Mala Direta sem
        // abrir janelas, com limite diário e intervalo aleatório no backend,
        // + toast "Atividade registrada — desfazer" e Contato Rápido.
        // =====================================================

        function showUndoToast(message, undoFn, seconds = 10) {
            const id = 'undoToast_' + Date.now();
            const html = `
                <div id="${id}" style="position:fixed; bottom:24px; left:50%; transform:translateX(-50%);
                     background:#065f46; color:#fff; padding:10px 16px; border-radius:10px; z-index:99999;
                     display:flex; align-items:center; gap:12px; box-shadow:0 8px 24px rgba(0,0,0,.25); font-size:13.5px;">
                    <span>${escapeHtml(message)}</span>
                    <button style="background:#fff; color:#065f46; border:none; border-radius:8px; padding:4px 12px;
                            font-weight:700; cursor:pointer;" id="${id}_btn">Desfazer</button>
                </div>`;
            document.body.insertAdjacentHTML('beforeend', html);
            const el = document.getElementById(id);
            const timer = setTimeout(() => el?.remove(), seconds * 1000);
            document.getElementById(`${id}_btn`)?.addEventListener('click', async () => {
                clearTimeout(timer);
                el?.remove();
                try { await undoFn(); showSuccess('Ação desfeita.'); } catch (e) { showError('Não foi possível desfazer.'); }
            });
        }

        async function _wahaRefreshQuota() {
            try {
                const q = await (await fetch(`${API_BASE}/whatsapp/send-quota`)).json();
                const el = document.getElementById('mailingWahaQuota');
                if (el && q.limit != null) el.textContent = `cota WAHA: ${q.used_today}/${q.limit} hoje`;
                return q;
            } catch (e) { return null; }
        }

        function _wahaSetDispatchProgress(pct, step) {
            const wrap = document.getElementById('mailingWahaProgress');
            const bar = document.getElementById('mailingWahaProgressBar');
            const stepEl = document.getElementById('mailingWahaProgressStep');
            if (wrap) wrap.style.display = 'block';
            if (bar) bar.style.width = Math.max(5, pct) + '%';
            if (stepEl) stepEl.textContent = step || '';
        }

        function _wahaMarkRow(idx, status, error) {
            const draft = autoTocaMailingDispatchDrafts[idx];
            const statusEl = document.getElementById(`mailingDispatchStatus_${idx}`);
            const wahaBtn = document.getElementById(`mailingWahaBtn_${idx}`);
            const openBtn = document.getElementById(`mailingDispatchBtn_${idx}`);
            if (status === 'sent') {
                if (draft) draft.status = 'sent';
                if (statusEl) { statusEl.textContent = 'Enviado ✓ (WAHA)'; statusEl.style.color = '#059669'; }
                if (wahaBtn) wahaBtn.style.display = 'none';
                if (openBtn) openBtn.style.display = 'none';
            } else if (status === 'blocked') {
                if (statusEl) { statusEl.textContent = 'Limite diário'; statusEl.style.color = '#b45309'; }
            } else if (status === 'error') {
                if (statusEl) { statusEl.textContent = `Falha: ${(error || 'erro').slice(0, 60)}`; statusEl.style.color = '#ef4444'; }
            }
            const sentCount = autoTocaMailingDispatchDrafts.filter(d => d.status === 'sent').length;
            const counterEl = document.getElementById('mailingDispatchCounter');
            if (counterEl) counterEl.textContent = `${sentCount} de ${autoTocaMailingDispatchDrafts.length} enviados`;
        }

        async function dispatchMailingViaWahaOne(idx) {
            const draft = autoTocaMailingDispatchDrafts[idx];
            if (!draft || draft.status === 'sent') return;
            const btn = document.getElementById(`mailingWahaBtn_${idx}`);
            if (btn) btn.disabled = true;
            try {
                const resp = await fetch(`${API_BASE}/whatsapp/send`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ client_id: draft.contact.id, phone: draft.phone, message: draft.body })
                });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(payload.error || 'Falha no envio via WAHA.');
                _wahaMarkRow(idx, 'sent');
                _wahaRefreshQuota();
                if (payload.activity_id) {
                    showUndoToast('Atividade registrada — desfazer', async () => {
                        try { await fetch(`${API_BASE}/atividades/${payload.activity_id}`, { method: 'DELETE' }); } catch (e) {}
                    });
                }
            } catch (e) {
                _wahaMarkRow(idx, 'error', e.message);
                showError(e.message);
                if (btn) btn.disabled = false;
            }
        }

        async function dispatchMailingViaWahaAll() {
            const pending = autoTocaMailingDispatchDrafts
                .map((d, i) => ({ d, i }))
                .filter(x => x.d.status !== 'sent' && x.d.phone);
            if (!pending.length) { showInfo('Nenhum contato pendente com telefone.'); return; }
            const quota = await _wahaRefreshQuota();
            if (quota && quota.remaining !== undefined && quota.remaining < pending.length) {
                const ok = await uiConfirm(
                    `A cota diária permite mais ${quota.remaining} envio(s) hoje e a fila tem ${pending.length}. ` +
                    'Enviar até o limite e deixar o restante para amanhã?', 'Limite diário WAHA');
                if (!ok) return;
            }
            const items = pending.map(x => ({
                client_id: x.d.contact.id, phone: x.d.phone, message: x.d.body, name: x.d.contact.name
            }));
            try {
                const resp = await fetch(`${API_BASE}/whatsapp/send-batch`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ items })
                });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(payload.error || 'Falha ao iniciar o despacho.');
                _wahaSetDispatchProgress(5, 'Iniciando despacho via WAHA...');
                BgTaskManager.register(
                    payload.task_id,
                    `${API_BASE}/whatsapp/tasks/${payload.task_id}`,
                    'Mala Direta via WAHA',
                    typeof _currentTab !== 'undefined' ? _currentTab : 'autotoca',
                    (result) => {
                        const details = (result && result.details) || [];
                        details.forEach((det, j) => {
                            const idx = pending[j] ? pending[j].i : null;
                            if (idx !== null) _wahaMarkRow(idx, det.status, det.error);
                        });
                        const wrap = document.getElementById('mailingWahaProgress');
                        if (wrap) wrap.style.display = 'none';
                        _wahaRefreshQuota();
                        const msg = `Despacho concluído: ${result.sent} enviado(s)` +
                            (result.failed ? `, ${result.failed} falha(s)` : '') +
                            (result.blocked ? `, ${result.blocked} bloqueado(s) pelo limite diário` : '') +
                            '. Atividades registradas automaticamente.';
                        (result.failed || result.blocked ? showError : showSuccess)(msg);
                        try { loadActivities(); loadDashboard(); } catch (e) { /* opcional */ }
                    },
                    (errMsg) => {
                        const wrap = document.getElementById('mailingWahaProgress');
                        if (wrap) wrap.style.display = 'none';
                        showError(errMsg || 'Erro no despacho via WAHA.');
                    },
                    (pct, step) => _wahaSetDispatchProgress(pct, step)
                );
            } catch (e) { showError(e.message); }
        }

        // -----------------------------------------------------
        // Contato rápido no perfil do cliente (Bloco 8, tarefa 6)
        // -----------------------------------------------------

        const _QUICK_CONTACT_TAGS = ['<nome do contato>', '<sobrenome>', '<conta>', '<cargo>', '<area de atuacao>', '<ultima atividade>'];

        function _quickContactMerge(text, client) {
            const first = getAutoTocaContactFirstName(client.name);
            const last = getAutoTocaContactLastName(client.name);
            let lastAct = (client.last_activity_date || '').slice(0, 10);
            if (lastAct) { const [y, m, d] = lastAct.split('-'); lastAct = `${d}/${m}/${y}`; }
            return String(text || '')
                .replaceAll('<nome do contato>', first)
                .replaceAll('<sobrenome>', last)
                .replaceAll('<conta>', client.company || '')
                .replaceAll('<cargo>', client.position || '')
                .replaceAll('<area de atuacao>', client.area_of_activity || '')
                .replaceAll('<ultima atividade>', lastAct || 'nosso último contato')
                // retrocompatibilidade com templates antigos em {chave}
                .replaceAll('{nome}', first)
                .replaceAll('{empresa}', client.company || '')
                .replaceAll('{cargo}', client.position || '')
                .replaceAll('{ultima_atividade}', lastAct || 'nosso último contato');
        }

        async function openQuickContactModal(clientId) {
            const client = (typeof clients !== 'undefined' && clients.find(c => c.id === clientId)) ||
                await (await fetch(`${API_BASE}/clients/${clientId}`)).json();
            let templates = [];
            try {
                templates = await (await fetch(`${API_BASE}/config/templates`)).json();
            } catch (e) { templates = []; }
            const waTemplates = (templates || []).filter(t => Number(t.available_whatsapp) !== 0);
            const options = waTemplates.map(t => `<option value="${t.id}">${escapeHtml(t.title)}</option>`).join('');
            document.getElementById('quickContactModal')?.remove();
            const html = `
                <div class="modal active" id="quickContactModal" onclick="if(event.target===this) this.remove()">
                    <div class="modal-content" style="max-width:560px;">
                        <div class="modal-header">
                            <h2 class="modal-title"><i class="fab fa-whatsapp" style="color:#25d366;"></i> Contato rápido — ${escapeHtml(client.name)}</h2>
                            <button class="modal-close" onclick="document.getElementById('quickContactModal').remove()">&#215;</button>
                        </div>
                        <div class="form-group">
                            <label>Template</label>
                            <select id="quickContactTemplate" class="input-minimal" style="width:100%;" onchange="quickContactApplyTemplate(${clientId})">
                                <option value="">Mensagem livre...</option>${options}
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Mensagem</label>
                            <textarea id="quickContactBody" rows="6" placeholder="Olá <nome do contato>! Tudo bem?"></textarea>
                            <div style="display:flex; flex-wrap:wrap; gap:6px; margin-top:8px;">
                                ${_QUICK_CONTACT_TAGS.map(tag => `<button type="button" class="btn btn-secondary btn-small" onclick="insertMergeTagInto('quickContactBody', '${tag.replace(/'/g, "\\'")}')">${escapeHtml(tag)}</button>`).join('')}
                            </div>
                            <small class="toca-text-muted" style="font-size:11px;">Cada chave é substituída pelo dado real do contato no envio.</small>
                        </div>
                        <div style="display:flex; justify-content:flex-end; gap:8px; flex-wrap:wrap;">
                            <button class="btn btn-secondary" onclick="quickContactOpenWeb(${clientId})" title="Abrir no WhatsApp Web/desktop (contingência)"><i class="fab fa-whatsapp"></i> Abrir no WhatsApp</button>
                            <button class="btn btn-secondary" onclick="scheduleFromQuickContact(${clientId})" title="Agendar o envio para uma data e horário"><i class="fas fa-clock"></i> Agendar</button>
                            <button class="btn btn-auto-mapping" onclick="quickContactSendWaha(${clientId})"><span class="ai-star-icon">✦</span> Enviar via WAHA</button>
                        </div>
                    </div>
                </div>`;
            document.body.insertAdjacentHTML('beforeend', html);
            window._quickContactTemplates = waTemplates;
            window._quickContactClient = client;
        }

        function quickContactApplyTemplate(clientId) {
            const sel = document.getElementById('quickContactTemplate');
            const body = document.getElementById('quickContactBody');
            const tpl = (window._quickContactTemplates || []).find(t => String(t.id) === sel.value);
            if (tpl && body) body.value = _quickContactMerge(tpl.description, window._quickContactClient || {});
        }

        function _quickContactMessage() {
            const raw = (document.getElementById('quickContactBody')?.value || '').trim();
            if (!raw) { showError('Escreva ou escolha uma mensagem.'); return null; }
            return _quickContactMerge(raw, window._quickContactClient || {});
        }

        async function quickContactSendWaha(clientId) {
            const message = _quickContactMessage();
            if (!message) return;
            const client = window._quickContactClient || {};
            if (!client.phone) { showError('Este contato não tem telefone cadastrado.'); return; }
            try {
                const resp = await fetch(`${API_BASE}/whatsapp/send`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ client_id: clientId, phone: client.phone, message })
                });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(payload.error || 'Falha no envio via WAHA.');
                document.getElementById('quickContactModal')?.remove();
                if (payload.activity_id) {
                    showUndoToast('Mensagem enviada — atividade registrada. Desfazer registro?', async () => {
                        try { await fetch(`${API_BASE}/atividades/${payload.activity_id}`, { method: 'DELETE' }); } catch (e) {}
                    });
                } else {
                    showSuccess('Mensagem enviada via WAHA!');
                }
            } catch (e) { showError(e.message); }
        }

        function quickContactOpenWeb(clientId) {
            const message = _quickContactMessage();
            if (!message) return;
            const client = window._quickContactClient || {};
            const phone = normalizePhoneForWhatsapp(client.phone || '');
            if (!phone) { showError('Este contato não tem telefone válido.'); return; }
            const url = `https://web.whatsapp.com/send?phone=${encodeURIComponent(phone)}&text=${encodeURIComponent(message)}`;
            window.open(url, '_blank');
        }
