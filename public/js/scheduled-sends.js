        // =====================================================
        // Envio agendado (WhatsApp/e-mail) + avisos de inicialização:
        // envios perdidos, primeiro acesso pós-instalação e
        // atualização da extensão do navegador.
        // =====================================================

        function _schedDefaultDateTime() {
            const d = new Date(Date.now() + 24 * 60 * 60 * 1000);
            return { date: d.toISOString().slice(0, 10), time: '09:00' };
        }

        /**
         * Abre o modal de agendamento.
         * opts: { channel: 'whatsapp'|'email', items: [{client_id, phone, email_to, subject, message, name}], onScheduled }
         */
        function openScheduleSendModal(opts) {
            const items = (opts.items || []).filter(it => (it.message || '').trim());
            if (!items.length) { showError('Escreva a mensagem antes de agendar.'); return; }
            document.getElementById('scheduleSendModal')?.remove();
            const def = _schedDefaultDateTime();
            const who = items.length === 1
                ? escapeHtml(items[0].name || items[0].email_to || items[0].phone || 'contato')
                : `${items.length} contatos da fila`;
            const chIcon = opts.channel === 'email' ? '📧' : '📱';
            const html = `
                <div class="modal active" id="scheduleSendModal" onclick="if(event.target===this) this.remove()">
                    <div class="modal-content" style="max-width:430px;">
                        <div class="modal-header">
                            <h2 class="modal-title"><i class="fas fa-clock"></i> Agendar envio</h2>
                            <button class="modal-close" onclick="document.getElementById('scheduleSendModal').remove()">&#215;</button>
                        </div>
                        <p style="color:#6b7280; font-size:13px; margin-bottom:12px;">${chIcon} Enviar para <b>${who}</b> na data e horário abaixo. Se o sistema estiver fechado nesse momento, você será avisado no próximo login para decidir se ainda quer enviar.</p>
                        <div style="display:flex; gap:10px;">
                            <div class="form-group" style="flex:1;"><label>Data</label><input type="date" id="schedSendDate" value="${def.date}" min="${new Date().toISOString().slice(0, 10)}"></div>
                            <div class="form-group" style="flex:1;"><label>Horário</label><input type="time" id="schedSendTime" value="${def.time}"></div>
                        </div>
                        <div style="display:flex; justify-content:flex-end; gap:8px;">
                            <button class="btn btn-secondary" onclick="document.getElementById('scheduleSendModal').remove()">Cancelar</button>
                            <button class="btn btn-primary" id="schedSendConfirmBtn"><i class="fas fa-clock"></i> Agendar</button>
                        </div>
                    </div>
                </div>`;
            document.body.insertAdjacentHTML('beforeend', html);
            document.getElementById('schedSendConfirmBtn').addEventListener('click', async () => {
                const date = document.getElementById('schedSendDate')?.value;
                const time = document.getElementById('schedSendTime')?.value;
                if (!date || !time) { showError('Informe data e horário.'); return; }
                try {
                    const resp = await fetch(`${API_BASE}/scheduled-sends`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            scheduled_for: `${date} ${time}`,
                            items: items.map(it => ({ channel: opts.channel, ...it })),
                        })
                    });
                    const payload = await resp.json().catch(() => ({}));
                    if (!resp.ok) throw new Error(payload.error || 'Erro ao agendar envio.');
                    document.getElementById('scheduleSendModal')?.remove();
                    const [y, m, d] = date.split('-');
                    showSuccess(`Envio agendado para ${d}/${m}/${y} às ${time}! ⏰`);
                    if (typeof opts.onScheduled === 'function') opts.onScheduled(payload);
                } catch (e) { showError(e.message); }
            });
        }

        // ---- Atalhos usados pelos modais de envio existentes ----

        function scheduleFromQuickContact(clientId) {
            const message = typeof _quickContactMessage === 'function' ? _quickContactMessage() : null;
            if (!message) return;
            const client = window._quickContactClient || {};
            if (!client.phone) { showError('Este contato não tem telefone cadastrado.'); return; }
            openScheduleSendModal({
                channel: 'whatsapp',
                items: [{ client_id: clientId, phone: client.phone, message, name: client.name }],
                onScheduled: () => document.getElementById('quickContactModal')?.remove(),
            });
        }

        function scheduleFromRadarDraft(suggestionId) {
            const message = (document.getElementById('radarDraftBody')?.value || '').trim();
            const client = window._radarDraftClient;
            if (!message) { showError('Gere ou escreva a mensagem primeiro.'); return; }
            if (!client || !client.phone) { showError('Contato sem telefone cadastrado.'); return; }
            openScheduleSendModal({
                channel: 'whatsapp',
                items: [{ client_id: client.id, phone: client.phone, message, name: client.name }],
                onScheduled: async () => {
                    document.getElementById('radarDraftModal')?.remove();
                    await fetch(`${API_BASE}/suggestions/${suggestionId}/complete`, { method: 'POST' }).catch(() => {});
                    loadRadarDoDia();
                },
            });
        }

        function scheduleFromEmailDraft(clientId) {
            const client = (typeof clients !== 'undefined' && clients.find(c => c.id === clientId)) || {};
            const subject = (document.getElementById('emailDraftSubject')?.value || '').trim();
            const message = (document.getElementById('emailDraftBody')?.value || '').trim();
            if (!message) { showError('Escreva a mensagem antes de agendar.'); return; }
            if (!client.email) { showError('Este contato não tem e-mail cadastrado.'); return; }
            openScheduleSendModal({
                channel: 'email',
                items: [{ client_id: clientId, email_to: client.email, subject, message, name: client.name }],
                onScheduled: () => closeEmailDraftModal(),
            });
        }

        function scheduleMailingViaWaha() {
            const pending = (autoTocaMailingDispatchDrafts || [])
                .filter(d => d.status !== 'sent' && d.phone);
            if (!pending.length) { showInfo('Nenhum contato pendente com telefone.'); return; }
            openScheduleSendModal({
                channel: 'whatsapp',
                items: pending.map(d => ({
                    client_id: d.contact.id, phone: d.phone, message: d.body, name: d.contact.name
                })),
                onScheduled: () => {
                    closeAutoTocaMailingDispatchModal();
                    showInfo('Fila da mala direta agendada — os envios sairão via WAHA no horário marcado.');
                },
            });
        }

        // =====================================================
        // Avisos de inicialização (rodam uma vez por sessão)
        // =====================================================

        async function checkStartupNotices() {
            let firstRun = false;
            // 1) Primeiro acesso após instalação → direto para o cadastro do usuário
            try {
                const fr = await (await fetch(`${API_BASE}/config/first-run`)).json();
                if (fr.first_run) {
                    firstRun = true;
                    switchTab(null, 'configuracoes');
                    setTimeout(() => {
                        document.getElementById('userProfileForm')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        document.querySelector('#userProfileForm input[name="full_name"]')?.focus();
                        showInfo('Bem-vindo à Toca do Coelho! 🐇 Comece preenchendo o seu cadastro de usuário.');
                    }, 600);
                    fetch(`${API_BASE}/config/first-run/seen`, { method: 'POST' }).catch(() => {});
                }
            } catch (e) { /* segue */ }

            // 2) Envios agendados perdidos (sistema estava desligado na hora)
            try {
                const missed = await (await fetch(`${API_BASE}/scheduled-sends/missed`)).json();
                if (Array.isArray(missed) && missed.length) _showMissedSendsModal(missed);
            } catch (e) { /* segue */ }

            // 3) Update trouxe extensão nova → avisar para baixar/reinstalar o plugin
            if (!firstRun) {
                try {
                    const ext = await (await fetch(`${API_BASE}/extension/update-status`)).json();
                    if (ext.update_available) _showExtensionUpdateModal(ext);
                } catch (e) { /* segue */ }
            }
        }

        function _showMissedSendsModal(missed) {
            document.getElementById('missedSendsModal')?.remove();
            const rows = missed.map(m => `
                <div id="missedSendRow_${m.id}" style="display:flex; align-items:center; gap:10px; padding:8px 10px; border:1px solid rgba(245,158,11,.35); border-radius:10px;">
                    <span>${m.channel === 'email' ? '📧' : '📱'}</span>
                    <div style="flex:1; min-width:150px;">
                        <div style="font-weight:600; font-size:13px;">${escapeHtml(m.client_name || m.email_to || m.phone || '-')}</div>
                        <div style="font-size:12px; color:#9ca3af;">agendado para ${escapeHtml(m.scheduled_for)} · ${escapeHtml((m.message || '').slice(0, 70))}...</div>
                    </div>
                    <button class="btn btn-primary btn-small" onclick="missedSendAct(${m.id}, 'send-now')"><i class="fas fa-paper-plane"></i> Enviar agora</button>
                    <button class="btn btn-secondary btn-small" onclick="missedSendAct(${m.id}, 'cancel')">Cancelar</button>
                </div>`).join('');
            const html = `
                <div class="modal active" id="missedSendsModal" onclick="if(event.target===this) this.remove()">
                    <div class="modal-content" style="max-width:620px;">
                        <div class="modal-header">
                            <h2 class="modal-title">⏰ Envios agendados pendentes</h2>
                            <button class="modal-close" onclick="document.getElementById('missedSendsModal').remove()">&#215;</button>
                        </div>
                        <p style="color:#6b7280; font-size:13px; margin-bottom:12px;">O sistema estava fechado no horário destes envios agendados. Você ainda quer enviá-los?</p>
                        <div style="display:flex; flex-direction:column; gap:8px; max-height:55vh; overflow:auto;">${rows}</div>
                        <div style="display:flex; justify-content:flex-end; margin-top:12px;">
                            <button class="btn btn-secondary" onclick="document.getElementById('missedSendsModal').remove()">Decidir depois</button>
                        </div>
                    </div>
                </div>`;
            document.body.insertAdjacentHTML('beforeend', html);
        }

        async function missedSendAct(id, action) {
            try {
                const resp = await fetch(`${API_BASE}/scheduled-sends/${id}/${action}`, { method: 'POST' });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(payload.error || 'Erro ao processar o envio.');
                document.getElementById(`missedSendRow_${id}`)?.remove();
                (action === 'send-now' ? showSuccess : showInfo)(action === 'send-now' ? 'Enviado!' : 'Agendamento cancelado.');
                const modal = document.getElementById('missedSendsModal');
                if (modal && !modal.querySelector('[id^="missedSendRow_"]')) modal.remove();
            } catch (e) { showError(e.message); }
        }

        function _showExtensionUpdateModal(ext) {
            document.getElementById('extensionUpdateModal')?.remove();
            const html = `
                <div class="modal active" id="extensionUpdateModal" onclick="if(event.target===this) this.remove()">
                    <div class="modal-content" style="max-width:480px;">
                        <div class="modal-header">
                            <h2 class="modal-title">🧩 Nova versão da extensão do navegador</h2>
                            <button class="modal-close" onclick="document.getElementById('extensionUpdateModal').remove()">&#215;</button>
                        </div>
                        <p style="color:#4b5563; font-size:13.5px; line-height:1.5; margin-bottom:14px;">
                            Esta atualização do Toca do Coelho inclui uma <b>nova versão (v${escapeHtml(ext.current)})
                            da extensão AutoToca Helper</b> para o navegador${ext.seen ? ` (você usa a v${escapeHtml(ext.seen)})` : ''}.
                            Baixe o arquivo e reinstale o plugin para continuar usando a captura de perfis do LinkedIn
                            (incluindo a detecção automática de mudança de emprego).
                        </p>
                        <div style="display:flex; justify-content:flex-end; gap:8px; flex-wrap:wrap;">
                            <button class="btn btn-secondary btn-small" onclick="document.getElementById('extensionUpdateModal').remove()">Lembrar depois</button>
                            <a class="btn btn-primary btn-small" href="${escapeHtml(ext.download_url)}" download onclick="showInfo('Após baixar: chrome://extensions → Modo do desenvolvedor → arraste o arquivo.')"><i class="fas fa-download"></i> Baixar extensão</a>
                            <button class="btn btn-auto-mapping btn-small" onclick="extensionUpdateMarkSeen()"><i class="fas fa-check"></i> Já instalei</button>
                        </div>
                    </div>
                </div>`;
            document.body.insertAdjacentHTML('beforeend', html);
        }

        async function extensionUpdateMarkSeen() {
            try {
                await fetch(`${API_BASE}/extension/update-status/seen`, { method: 'POST' });
                document.getElementById('extensionUpdateModal')?.remove();
                showSuccess('Extensão marcada como atualizada!');
            } catch (e) { showError('Erro ao registrar.'); }
        }

        document.addEventListener('DOMContentLoaded', () => setTimeout(checkStartupNotices, 1500));
