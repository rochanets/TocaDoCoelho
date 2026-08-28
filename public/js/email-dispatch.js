        // =====================================================
        // Envio direto de e-mail pela conta Microsoft conectada (OAuth/Graph).
        // Complementa o modo legado "Abrir no Outlook" (deeplink do Outlook
        // Web, uma janela por contato) no despacho da Mala Direta: com a conta
        // conectada, a fila inteira sai de uma vez pela própria caixa do
        // usuário, sem janelas e sem bloqueador de pop-up no caminho.
        // =====================================================

        // Estado da última verificação, para os botões saberem se podem enviar
        // sem repetir a chamada de status a cada clique.
        let _mailingOutlookState = { connected: false, email: '', checked: false };

        function _mailingOutlookSetAvailability(connected) {
            const batchBtn = document.getElementById('mailingOutlookBatchBtn');
            if (batchBtn) batchBtn.disabled = !connected;
            (autoTocaMailingDispatchDrafts || []).forEach((d, i) => {
                const btn = document.getElementById(`mailingOauthBtn_${i}`);
                if (btn) btn.disabled = !connected;
            });
        }

        /** Consulta a conexão Microsoft e reflete o resultado no cabeçalho do
         *  modal de despacho. Sem conta conectada, os botões de envio direto
         *  ficam desabilitados e sobra o caminho "Abrir no Outlook". */
        async function _mailingOutlookRefreshStatus() {
            const el = document.getElementById('mailingOutlookStatus');
            try {
                const status = await (await fetch(`${API_BASE}/outlook/graph-status`)).json();
                _mailingOutlookState = {
                    connected: !!status.connected,
                    email: status.email || '',
                    checked: true
                };
                _mailingOutlookSetAvailability(status.connected);
                if (!el) return _mailingOutlookState;
                if (status.connected) {
                    el.style.color = '#059669';
                    el.textContent = status.email
                        ? `enviando como ${status.email}`
                        : 'conta Microsoft conectada';
                } else {
                    el.style.color = '#b45309';
                    el.innerHTML = `conta Microsoft não conectada — ` +
                        `<a href="javascript:void(0)" onclick="_mailingOutlookConnect(${status.needs_consent ? 'true' : 'false'})" ` +
                        `style="color:#047857; font-weight:600;">conectar</a>`;
                }
            } catch (e) {
                _mailingOutlookState = { connected: false, email: '', checked: true };
                _mailingOutlookSetAvailability(false);
                if (el) { el.style.color = '#b45309'; el.textContent = 'não foi possível verificar a conta Microsoft'; }
            }
            return _mailingOutlookState;
        }

        /** Abre o OAuth e revalida quando a janela de autorização fecha. */
        async function _mailingOutlookConnect(forceConsent) {
            if (typeof connectMicrosoft365 !== 'function') return;
            await connectMicrosoft365(!!forceConsent);
            const el = document.getElementById('mailingOutlookStatus');
            if (el) { el.style.color = '#6b7280'; el.textContent = 'aguardando a autorização...'; }
            // O retorno do OAuth acontece em outra janela; algumas checagens
            // espaçadas evitam obrigar o usuário a reabrir o modal.
            for (let i = 0; i < 10; i++) {
                await new Promise(r => setTimeout(r, 3000));
                if (!document.getElementById('mailingOutlookStatus')) return;
                const st = await _mailingOutlookRefreshStatus();
                if (st.connected) { showSuccess('Conta Microsoft conectada — já dá para enviar a fila.'); return; }
            }
        }

        async function dispatchMailingViaOutlookOne(idx) {
            const draft = autoTocaMailingDispatchDrafts[idx];
            if (!draft || draft.status === 'sent') return;
            const btn = document.getElementById(`mailingOauthBtn_${idx}`);
            if (btn) btn.disabled = true;
            try {
                const resp = await fetch(`${API_BASE}/outlook/send`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        client_id: draft.contact.id,
                        to: draft.contact.email,
                        subject: draft.subject,
                        message: draft.body
                    })
                });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) {
                    if (payload.needs_auth) _mailingOutlookRefreshStatus();
                    throw new Error(payload.error || 'Falha ao enviar pelo Outlook.');
                }
                _mailingMarkDispatchRow(idx, 'sent', null, 'Outlook');
                tocaDebug('mala-direta.oauth-one', 'E-mail enviado via Graph', {
                    idx, contact_id: draft.contact.id, to: draft.contact.email
                });
                if (payload.activity_id) {
                    showUndoToast('Atividade registrada — desfazer', async () => {
                        try { await fetch(`${API_BASE}/atividades/${payload.activity_id}`, { method: 'DELETE' }); } catch (e) {}
                    });
                }
            } catch (e) {
                _mailingMarkDispatchRow(idx, 'error', e.message, 'Outlook');
                showError(e.message);
                if (btn) btn.disabled = false;
            }
        }

        async function dispatchMailingViaOutlookAll() {
            const pending = (autoTocaMailingDispatchDrafts || [])
                .map((d, i) => ({ d, i }))
                .filter(x => x.d.status !== 'sent' && String(x.d.contact.email || '').trim());
            if (!pending.length) { showInfo('Nenhum contato pendente com e-mail.'); return; }

            const st = _mailingOutlookState.checked ? _mailingOutlookState : await _mailingOutlookRefreshStatus();
            if (!st.connected) {
                showError('Conecte sua conta Microsoft 365 para enviar a fila pelo Outlook.');
                return;
            }

            // O disparo é irreversível: confirma quantos e-mails saem e de qual caixa.
            const ok = await uiConfirm(
                `Enviar ${pending.length} e-mail(s) agora pela conta ${st.email || 'Microsoft conectada'}? ` +
                'As mensagens saem direto da sua caixa e as atividades são registradas automaticamente.',
                'Enviar mala direta'
            );
            if (!ok) return;

            const items = pending.map(x => ({
                client_id: x.d.contact.id,
                to: x.d.contact.email,
                subject: x.d.subject,
                message: x.d.body,
                name: x.d.contact.name
            }));

            try {
                const resp = await fetch(`${API_BASE}/outlook/send-batch`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ items })
                });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) {
                    if (payload.needs_auth) _mailingOutlookRefreshStatus();
                    throw new Error(payload.error || 'Falha ao iniciar o despacho.');
                }
                _mailingSetDispatchProgress(5, 'Iniciando despacho pelo Outlook...');
                BgTaskManager.register(
                    payload.task_id,
                    `${API_BASE}/outlook/send-tasks/${payload.task_id}`,
                    'Mala Direta via Outlook',
                    typeof _currentTab !== 'undefined' ? _currentTab : 'autotoca',
                    (result) => {
                        const details = (result && result.details) || [];
                        details.forEach((det, j) => {
                            const idx = pending[j] ? pending[j].i : null;
                            if (idx !== null) _mailingMarkDispatchRow(idx, det.status, det.error, 'Outlook');
                        });
                        _mailingHideDispatchProgress();
                        if (result.blocked) _mailingOutlookRefreshStatus();
                        const msg = `Despacho concluído: ${result.sent} e-mail(s) enviado(s)` +
                            (result.failed ? `, ${result.failed} falha(s)` : '') +
                            (result.blocked ? `, ${result.blocked} não enviado(s) — conta Microsoft desconectada` : '') +
                            '. Atividades registradas automaticamente.';
                        (result.failed || result.blocked ? showError : showSuccess)(msg);
                        try { loadActivities(); loadDashboard(); } catch (e) { /* opcional */ }
                    },
                    (errMsg) => {
                        _mailingHideDispatchProgress();
                        showError(errMsg || 'Erro no despacho pelo Outlook.');
                    },
                    (pct, step) => _mailingSetDispatchProgress(pct, step)
                );
            } catch (e) { showError(e.message); }
        }
