        // =====================================================
        // Verificação de conexões (WhatsApp/WAHA e Microsoft 365)
        //
        // 1) Na abertura do sistema, checa em background se a sessão do
        //    WhatsApp está ativa. Se não estiver, abre um pop-up com o QR code
        //    do WAHA (com opções "fechar" e "não perguntar mais").
        // 2) Os mesmos modais ficam disponíveis sob demanda em
        //    Configurações → Integrações de API.
        // =====================================================

        const _connModalIds = { wa: 'waConnectModal', ms: 'ms365ConnectModal' };
        let _waConnPollTimer = null;
        let _waConnOpenedFromStartup = false;
        let _ms365PollTimer = null;

        // ---------- WhatsApp / WAHA ----------

        function _waConnStopPolling() {
            if (_waConnPollTimer) { clearInterval(_waConnPollTimer); _waConnPollTimer = null; }
        }

        function closeWhatsappConnectModal() {
            _waConnStopPolling();
            document.getElementById(_connModalIds.wa)?.remove();
        }

        /**
         * Abre o modal de sincronização do WhatsApp.
         * opts: { startup: true } quando veio da verificação automática — só
         * nesse caso o "não perguntar mais" aparece.
         */
        function openWhatsappConnectModal(opts) {
            const startup = !!(opts && opts.startup);
            _waConnOpenedFromStartup = startup;
            closeWhatsappConnectModal();
            const dontAskRow = startup ? `
                            <label style="display:flex; align-items:center; gap:8px; font-size:12.5px; color:#6b7280; cursor:pointer; user-select:none; margin-right:auto;">
                                <input type="checkbox" id="waConnDontAsk" style="width:16px; height:16px; cursor:pointer; accent-color:#10b981;">
                                Não perguntar mais na abertura do sistema
                            </label>` : '';
            const html = `
                <div class="modal active" id="${_connModalIds.wa}" onclick="if(event.target===this) closeWhatsappConnectModal()">
                    <div class="modal-content" style="max-width:460px;">
                        <div class="modal-header">
                            <h2 class="modal-title"><i class="fab fa-whatsapp" style="color:#25d366;"></i> Conexão do WhatsApp</h2>
                            <button class="modal-close" onclick="closeWhatsappConnectModal()">&#215;</button>
                        </div>
                        <div id="waConnBody" style="min-height:180px;">
                            <div style="text-align:center; padding:28px 0; color:#6b7280; font-size:13.5px;">
                                <i class="fas fa-circle-notch fa-spin" style="font-size:22px; color:#34d399; display:block; margin-bottom:10px;"></i>
                                Verificando a conexão...
                            </div>
                        </div>
                        <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-top:14px; padding-top:12px; border-top:1px solid #e5e7eb;">
                            ${dontAskRow}
                            <button class="btn btn-secondary btn-small" style="margin-left:auto;" onclick="_waConnClose()">Fechar</button>
                        </div>
                    </div>
                </div>`;
            document.body.insertAdjacentHTML('beforeend', html);
            _waConnRefresh();
            _waConnStopPolling();
            _waConnPollTimer = setInterval(_waConnRefresh, 4000);
        }

        /** Fecha respeitando o "não perguntar mais" marcado pelo usuário. */
        async function _waConnClose() {
            const chk = document.getElementById('waConnDontAsk');
            if (chk && chk.checked) {
                try {
                    await fetch(`${API_BASE}/whatsapp/startup-check`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ enabled: false })
                    });
                    showInfo('Ok! O aviso de WhatsApp desconectado não aparecerá mais na abertura. Você pode reativá-lo em Configurações → Integrações de API.');
                } catch (e) { showError('Não foi possível salvar a preferência.'); }
            }
            closeWhatsappConnectModal();
            if (typeof loadConnectionsCard === 'function') loadConnectionsCard();
        }

        async function _waConnRefresh() {
            const body = document.getElementById('waConnBody');
            if (!body) { _waConnStopPolling(); return; }
            let data;
            try {
                data = await (await fetch(`${API_BASE}/whatsapp/qr?start=1`)).json();
            } catch (e) {
                body.innerHTML = _waConnAlertHtml('#fef2f2', '#fca5a5', '#991b1b',
                    'Não foi possível contatar o servidor do Toca do Coelho.');
                return;
            }
            body.innerHTML = _waConnRenderState(data);
            if (data.connected) {
                _waConnStopPolling();
                if (typeof loadConnectionsCard === 'function') loadConnectionsCard();
            }
        }

        function _waConnAlertHtml(bg, border, color, message, extra) {
            return `<div style="background:${bg}; border:1px solid ${border}; border-radius:10px; padding:14px 16px; font-size:13px; color:${color};">
                        ${message}
                    </div>${extra || ''}`;
        }

        function _waConnRenderState(data) {
            const state = data.state || 'error';
            if (data.connected) {
                return _waConnAlertHtml('#ecfdf5', '#6ee7b7', '#065f46',
                    '<i class="fas fa-check-circle" style="margin-right:6px;"></i><strong>WhatsApp conectado!</strong> A sincronização de conversas está disponível.');
            }
            if (state === 'scan_qr' && data.qr) {
                return `
                    <div style="text-align:center;">
                        <p style="color:#374151; font-size:13px; margin-bottom:14px;">Seu WhatsApp <strong>não está conectado</strong>. Escaneie o QR code abaixo para conectar:</p>
                        <div style="display:inline-block; padding:12px; background:#fff; border:2px solid #a7f3d0; border-radius:14px; margin-bottom:12px;">
                            <img src="${data.qr}" alt="QR Code do WhatsApp" style="width:200px; height:200px; display:block;">
                        </div>
                        <div style="font-size:12px; color:#6b7280; margin-bottom:10px;">
                            <i class="fas fa-mobile-alt" style="margin-right:4px;"></i>
                            WhatsApp → Dispositivos conectados → Conectar dispositivo
                        </div>
                        <div style="font-size:13px; color:#059669;">
                            <i class="fas fa-circle-notch fa-spin" style="margin-right:6px;"></i>Aguardando leitura do QR code...
                        </div>
                    </div>`;
            }
            if (state === 'starting' || state === 'scan_qr') {
                return `<div style="text-align:center; padding:22px 0; color:#6b7280; font-size:13.5px;">
                            <i class="fas fa-circle-notch fa-spin" style="font-size:22px; color:#34d399; display:block; margin-bottom:10px;"></i>
                            ${escapeHtml(data.error || 'Conectando ao WhatsApp... aguarde.')}
                        </div>`;
            }
            if (state === 'not_configured') {
                return _waConnAlertHtml('#fff7ed', '#fed7aa', '#9a3412',
                    '<i class="fas fa-info-circle" style="margin-right:6px;"></i>O WhatsApp (WAHA) ainda não foi configurado neste computador.',
                    `<div style="margin-top:12px;"><button class="btn btn-auto-mapping btn-small" onclick="closeWhatsappConnectModal(); openWhatsappSyncModal();"><span class="ai-star-icon">✦</span> Configurar agora</button></div>`);
            }
            return _waConnAlertHtml('#fef2f2', '#fca5a5', '#991b1b',
                `<i class="fas fa-exclamation-triangle" style="margin-right:6px;"></i>${escapeHtml(data.error || 'WhatsApp desconectado.')}`,
                `<div style="margin-top:12px; display:flex; gap:8px; flex-wrap:wrap;">
                    <button class="btn btn-secondary btn-small" onclick="_waConnRefresh()"><i class="fas fa-rotate-right"></i> Tentar novamente</button>
                 </div>`);
        }

        /**
         * Verificação em background na abertura do sistema.
         * Usa /status (que não acorda o Chrome) e só abre o modal — que aí sim
         * inicia a sessão para gerar o QR — quando a sessão está mesmo caída.
         */
        async function checkWhatsappConnectionOnStartup(attempt) {
            attempt = attempt || 0;
            try {
                const pref = await (await fetch(`${API_BASE}/whatsapp/startup-check`)).json();
                if (!pref.enabled) return;

                const st = await (await fetch(`${API_BASE}/whatsapp/status`)).json();
                if (st.connected) return;
                if (!st.configured) return;   // nada configurado: não incomodar no login
                // Cold start do WAHA-lite/Chrome: espera antes de acusar desconexão.
                if (st.state === 'starting' && attempt < 6) {
                    setTimeout(() => checkWhatsappConnectionOnStartup(attempt + 1), 10000);
                    return;
                }
                if (document.getElementById(_connModalIds.wa)) return;
                openWhatsappConnectModal({ startup: true });
            } catch (e) { /* verificação silenciosa — nunca atrapalha a abertura */ }
        }

        // ---------- Microsoft 365 ----------

        function _ms365StopPolling() {
            if (_ms365PollTimer) { clearInterval(_ms365PollTimer); _ms365PollTimer = null; }
        }

        function closeMicrosoft365Modal() {
            _ms365StopPolling();
            document.getElementById(_connModalIds.ms)?.remove();
            if (typeof loadConnectionsCard === 'function') loadConnectionsCard();
        }

        function openMicrosoft365Modal() {
            closeMicrosoft365Modal();
            const html = `
                <div class="modal active" id="${_connModalIds.ms}" onclick="if(event.target===this) closeMicrosoft365Modal()">
                    <div class="modal-content" style="max-width:460px;">
                        <div class="modal-header">
                            <h2 class="modal-title"><i class="fas fa-cloud" style="color:#2563eb;"></i> Conexão Microsoft 365</h2>
                            <button class="modal-close" onclick="closeMicrosoft365Modal()">&#215;</button>
                        </div>
                        <div id="ms365ConnBody" style="min-height:120px;">
                            <div style="text-align:center; padding:24px 0; color:#6b7280; font-size:13.5px;">
                                <i class="fas fa-circle-notch fa-spin" style="font-size:22px; color:#60a5fa; display:block; margin-bottom:10px;"></i>
                                Verificando a conexão...
                            </div>
                        </div>
                        <div style="display:flex; justify-content:flex-end; margin-top:14px; padding-top:12px; border-top:1px solid #e5e7eb;">
                            <button class="btn btn-secondary btn-small" onclick="closeMicrosoft365Modal()">Fechar</button>
                        </div>
                    </div>
                </div>`;
            document.body.insertAdjacentHTML('beforeend', html);
            _ms365Refresh();
        }

        async function _ms365Refresh() {
            const body = document.getElementById('ms365ConnBody');
            if (!body) { _ms365StopPolling(); return; }
            let status = {}, cfg = {};
            try {
                status = await (await fetch(`${API_BASE}/outlook/graph-status`)).json();
                cfg = await (await fetch(`${API_BASE}/outlook/graph-config`)).json();
            } catch (e) {
                body.innerHTML = _waConnAlertHtml('#fef2f2', '#fca5a5', '#991b1b',
                    'Não foi possível verificar a conexão com o Microsoft 365.');
                return;
            }
            if (status.connected) {
                _ms365StopPolling();
                body.innerHTML = _waConnAlertHtml('#eff6ff', '#bfdbfe', '#1e40af',
                    `<i class="fas fa-check-circle" style="margin-right:6px; color:#16a34a;"></i>Conectado como <strong>${escapeHtml(status.email || 'conta Microsoft')}</strong>.`,
                    `<div style="margin-top:12px; display:flex; gap:8px; flex-wrap:wrap;">
                        <button class="btn btn-secondary btn-small" onclick="_ms365Disconnect()"><i class="fas fa-unlink"></i> Desconectar</button>
                     </div>`);
                return;
            }
            const configured = !!cfg.configured;
            const configForm = `
                <div style="margin-top:14px; padding-top:12px; border-top:1px dashed #e5e7eb;">
                    <p style="font-size:12px; color:#6b7280; margin-bottom:8px;">Credenciais do aplicativo Microsoft Entra (Azure AD):</p>
                    <div class="form-group" style="margin-bottom:8px;">
                        <label style="font-size:12px;">Tenant ID</label>
                        <input type="text" id="ms365TenantId" value="${escapeHtml(cfg.tenant_id || '')}" placeholder="common ou GUID do tenant">
                    </div>
                    <div class="form-group" style="margin-bottom:8px;">
                        <label style="font-size:12px;">Client ID</label>
                        <input type="text" id="ms365ClientId" value="${escapeHtml(cfg.client_id || '')}" placeholder="GUID do aplicativo">
                    </div>
                    <button class="btn btn-secondary btn-small" onclick="_ms365SaveConfig()"><i class="fas fa-save"></i> Salvar credenciais</button>
                </div>`;
            body.innerHTML = _waConnAlertHtml('#fff7ed', '#fed7aa', '#9a3412',
                '<i class="fas fa-info-circle" style="margin-right:6px;"></i>Sua conta Microsoft 365 <strong>não está conectada</strong>. Conecte para sincronizar e-mails direto do Outlook, sem plugin.',
                `<div style="margin-top:12px; display:flex; gap:8px; flex-wrap:wrap;">
                    <button class="btn btn-auto-mapping btn-small" onclick="_ms365Connect()" ${configured ? '' : 'disabled title="Informe Tenant ID e Client ID abaixo"'}>
                        <span class="ai-star-icon">✦</span> Conectar Microsoft 365
                    </button>
                 </div>${configForm}`);
        }

        async function _ms365SaveConfig() {
            const tenant_id = document.getElementById('ms365TenantId')?.value.trim();
            const client_id = document.getElementById('ms365ClientId')?.value.trim();
            try {
                const resp = await fetch(`${API_BASE}/outlook/graph-config`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tenant_id, client_id })
                });
                if (!resp.ok) throw new Error('Falha ao salvar.');
                showSuccess('Credenciais do Microsoft 365 salvas.');
                _ms365Refresh();
            } catch (e) { showError(e.message); }
        }

        async function _ms365Connect() {
            await connectMicrosoft365();
            // A autorização acontece na janela do navegador; enquanto ela não
            // volta, o modal fica olhando o status para se atualizar sozinho.
            _ms365StopPolling();
            _ms365PollTimer = setInterval(_ms365Refresh, 3000);
        }

        async function _ms365Disconnect() {
            if (!await uiConfirm('Deseja desconectar a conta Microsoft 365? Será necessário reconectar para sincronizar via Graph.', 'Desconectar')) return;
            await fetch(`${API_BASE}/outlook/graph-disconnect`, { method: 'DELETE' });
            if (typeof loadOutlookGraphStatus === 'function') loadOutlookGraphStatus();
            _ms365Refresh();
        }

        // ---------- Card "Conexões" nas Configurações ----------

        async function loadConnectionsCard() {
            const waEl = document.getElementById('connWhatsappStatus');
            const msEl = document.getElementById('connMicrosoftStatus');
            const chk = document.getElementById('waStartupCheckToggle');
            if (chk) {
                try {
                    const pref = await (await fetch(`${API_BASE}/whatsapp/startup-check`)).json();
                    chk.checked = !!pref.enabled;
                } catch (e) { /* mantém o valor atual */ }
            }
            if (waEl) {
                waEl.innerHTML = _connBadge('#6b7280', 'verificando...');
                try {
                    const st = await (await fetch(`${API_BASE}/whatsapp/status`)).json();
                    if (st.connected) waEl.innerHTML = _connBadge('#059669', 'conectado');
                    else if (!st.configured) waEl.innerHTML = _connBadge('#9ca3af', 'não configurado');
                    else if (st.state === 'starting') waEl.innerHTML = _connBadge('#d97706', 'iniciando...');
                    else waEl.innerHTML = _connBadge('#dc2626', 'desconectado');
                } catch (e) { waEl.innerHTML = _connBadge('#9ca3af', 'indisponível'); }
            }
            if (msEl) {
                msEl.innerHTML = _connBadge('#6b7280', 'verificando...');
                try {
                    const st = await (await fetch(`${API_BASE}/outlook/graph-status`)).json();
                    msEl.innerHTML = st.connected
                        ? _connBadge('#059669', escapeHtml(st.email || 'conectado'))
                        : _connBadge('#dc2626', 'desconectado');
                } catch (e) { msEl.innerHTML = _connBadge('#9ca3af', 'indisponível'); }
            }
        }

        function _connBadge(color, label) {
            return `<span style="display:inline-flex; align-items:center; gap:6px; font-size:12px; font-weight:600; color:${color};">
                        <span style="width:8px; height:8px; border-radius:50%; background:${color}; display:inline-block;"></span>${label}
                    </span>`;
        }

        async function onWaStartupCheckToggle(enabled) {
            try {
                await fetch(`${API_BASE}/whatsapp/startup-check`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled: !!enabled })
                });
                showSuccess(enabled ? 'Aviso de WhatsApp desconectado reativado.' : 'Aviso de WhatsApp desconectado desligado.');
            } catch (e) { showError('Não foi possível salvar a preferência.'); }
        }

        // Atrasa 3s para não competir com os avisos de inicialização
        // (envios perdidos, primeiro acesso, atualização da extensão).
        document.addEventListener('DOMContentLoaded', () => setTimeout(checkWhatsappConnectionOnStartup, 3000));
