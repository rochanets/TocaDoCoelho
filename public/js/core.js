        const API_BASE = '/api';
        let systemConfig = { env: 'production' };

        // =====================================================
        // BgTaskManager — gerenciador global de tarefas em background
        // Mantém polling de tasks mesmo após o usuário mudar de aba.
        // Exibe patinhas de coelho enquanto processa; exclamação verde quando conclui.
        // =====================================================
        const BgTaskManager = (() => {
            const _tasks = {};          // taskId -> taskInfo
            const _done  = [];          // tarefas concluídas enquanto usuário estava em outra aba
            let _pollTimer = null;

            function _indicator()   { return document.getElementById('bgTaskIndicator'); }
            function _doneList()    { return document.getElementById('bgTaskDoneList'); }

            function _activeTasks() {
                return Object.values(_tasks).filter(t => !t._done);
            }

            let _renderedState = null; // 'active' | 'done' | null

            function _render() {
                const ind = _indicator();
                if (!ind) return;
                const activeCount = _activeTasks().length;
                const doneCount   = _done.length;

                if (activeCount > 0) {
                    const first = _activeTasks()[0];
                    const label = _esc(first.step || first.title);
                    if (_renderedState !== 'active') {
                        // Build DOM once; subsequent calls only update the label
                        ind.className = 'bg-active';
                        ind.innerHTML = `
                            <div class="bgi-label">${label}</div>
                            <div class="bgi-video-wrap" title="Processando em background...">
                                <img src="/images/coelho-correndo.webp" alt="">
                            </div>`;
                        _renderedState = 'active';
                    } else {
                        // Only update the label text — do NOT touch the video element
                        const lbl = ind.querySelector('.bgi-label');
                        if (lbl && lbl.textContent !== label) lbl.textContent = label;
                    }
                } else if (doneCount > 0) {
                    if (_renderedState !== 'done') {
                        ind.className = 'bg-done';
                        ind.innerHTML = `
                            <div class="bgi-done-btn" title="Clique para ver resultados">
                                <span>✓</span>
                                ${doneCount > 1 ? `<div class="bgi-done-badge">${doneCount}</div>` : ''}
                            </div>`;
                        _renderedState = 'done';
                    } else {
                        // Update badge count without replacing the animated button
                        const btn = ind.querySelector('.bgi-done-btn');
                        if (btn) {
                            let badge = btn.querySelector('.bgi-done-badge');
                            if (doneCount > 1) {
                                if (!badge) { badge = document.createElement('div'); badge.className = 'bgi-done-badge'; btn.appendChild(badge); }
                                badge.textContent = doneCount;
                            } else if (badge) {
                                badge.remove();
                            }
                        }
                    }
                } else {
                    ind.className = '';
                    ind.style.display = 'none';
                    _renderedState = null;
                    _closeDoneList();
                    return;
                }
                ind.style.display = 'flex';
            }

            function _esc(s) {
                return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
            }

            function _closeDoneList() {
                const dl = _doneList();
                if (dl) { dl.className = ''; dl.innerHTML = ''; }
            }

            function _openDoneList() {
                const dl = _doneList();
                if (!dl) return;
                if (!_done.length) { _closeDoneList(); return; }
                let html = `<div class="bgtdl-header">Tarefas concluídas</div>`;
                _done.forEach((t, idx) => {
                    html += `<div class="bgtdl-item" onclick="BgTaskManager.claimTask(${idx})">
                        <div class="bgtdl-item-icon">✅</div>
                        <div>
                            <div class="bgtdl-item-title">${_esc(t.title)}</div>
                            <div class="bgtdl-item-sub">Clique para ver o resultado</div>
                        </div>
                    </div>`;
                });
                dl.innerHTML = html;
                dl.className = 'open';
            }

            async function _poll() {
                const active = _activeTasks();
                if (!active.length) return;

                for (const task of active) {
                    try {
                        const resp = await fetch(task.pollUrl);
                        if (!resp.ok) continue;
                        const status = await resp.json().catch(() => ({}));

                        // Atualiza step/progress na task
                        if (status.step)     task.step     = status.step;
                        if (status.progress) task.progress = status.progress;

                        // Repassa progresso para o inline progress (se o DOM ainda existir)
                        if (task.progressFn) {
                            try { task.progressFn(status.progress || 0, status.step || ''); } catch(e) {}
                        }

                        if (status.status === 'done') {
                            task._done = true;
                            const onSourceTab = (typeof _currentTab !== 'undefined') && _currentTab === task.sourceTab;
                            if (onSourceTab && task.onComplete) {
                                try { task.onComplete(status.result !== undefined ? status.result : status); } catch(e) {}
                                delete _tasks[task.taskId];
                            } else {
                                _done.push({ ...task, _result: status.result !== undefined ? status.result : status });
                                delete _tasks[task.taskId];
                            }
                            _render();
                        } else if (status.status === 'error' || status.status === 'cancelled') {
                            task._done = true;
                            if (task.onError) {
                                try { task.onError(status.error || 'Erro desconhecido.'); } catch(e) {}
                            }
                            delete _tasks[task.taskId];
                            _render();
                        }
                    } catch(e) { /* network hiccup, retry next tick */ }
                }
                _render();
            }

            function _startPoll() {
                if (_pollTimer) return;
                _pollTimer = setInterval(_poll, 800);
            }

            function _stopPollIfIdle() {
                if (_activeTasks().length === 0 && !_done.length) {
                    clearInterval(_pollTimer);
                    _pollTimer = null;
                }
            }

            // Public API
            function register(taskId, pollUrl, title, sourceTab, onComplete, onError, progressFn) {
                _tasks[taskId] = { taskId, pollUrl, title, sourceTab, onComplete, onError, progressFn, step: 'Iniciando...', progress: 5, _done: false };
                _startPoll();
                _render();
            }

            function onIndicatorClick() {
                const dl = _doneList();
                if (!dl) return;
                if (_done.length === 0) return;
                if (dl.className === 'open') { _closeDoneList(); return; }
                _openDoneList();
            }

            function claimTask(idx) {
                const task = _done[idx];
                if (!task) return;
                _done.splice(idx, 1);
                _closeDoneList();
                _render();
                // Navega de volta para a aba de origem
                if (task.sourceTab && typeof switchTab === 'function') {
                    switchTab(null, task.sourceTab);
                }
                // Chama o callback de conclusão com o resultado armazenado
                if (task.onComplete) {
                    setTimeout(() => {
                        try { task.onComplete(task._result); } catch(e) {}
                    }, 350);
                }
                _stopPollIfIdle();
            }

            // Permite que funções inline atualizem o progressFn de uma task em andamento
            function setProgressFn(taskId, fn) {
                if (_tasks[taskId]) _tasks[taskId].progressFn = fn;
            }

            // Minimiza: task continua rodando no background, apenas a UI inline é escondida
            function minimize(taskId) {
                if (_tasks[taskId]) _tasks[taskId].progressFn = null;
                _render();
            }

            // Cancela: remove do polling (backend continua, mas ninguém ouve)
            function cancel(taskId) {
                delete _tasks[taskId];
                _render();
                _stopPollIfIdle();
            }

            return { register, onIndicatorClick, claimTask, setProgressFn, minimize, cancel };
        })();

        // Helper: injeta botões Minimizar / Cancelar no topo de uma área de progresso
        function _attachBgTaskControls(progressEl, taskId, onMinimize, onCancel) {
            if (!progressEl) return;
            const existing = progressEl.querySelector('.bg-task-actions');
            if (existing) existing.remove();
            const div = document.createElement('div');
            div.className = 'bg-task-actions';
            const btnMin = document.createElement('button');
            btnMin.className = 'btn btn-secondary btn-small';
            btnMin.innerHTML = '<i class="fas fa-compress-alt" style="margin-right:4px;"></i>Minimizar';
            btnMin.onclick = () => { BgTaskManager.minimize(taskId); if (onMinimize) onMinimize(); };
            const btnCnl = document.createElement('button');
            btnCnl.className = 'btn btn-danger btn-small';
            btnCnl.innerHTML = '<i class="fas fa-times" style="margin-right:4px;"></i>Cancelar';
            btnCnl.onclick = () => { BgTaskManager.cancel(taskId); if (onCancel) onCancel(); };
            div.appendChild(btnMin);
            div.appendChild(btnCnl);
            progressEl.insertAdjacentElement('afterbegin', div);
        }

        // =====================================================
        // Logs de Depuração — buffer do cliente + sincronização opcional
        // Uso: tocaDebug('tag', 'mensagem', { dadosExtras })
        // - sempre guarda em window._tocaDebugBuffer (máx. 1000 entradas)
        // - se o modo debug está ligado, imprime no console e envia batches ao backend
        // =====================================================
        const TOCA_DEBUG_BUFFER_MAX = 1000;
        const TOCA_DEBUG_SYNC_DEBOUNCE_MS = 1500;
        window._tocaDebugBuffer = window._tocaDebugBuffer || [];
        let _tocaDebugEnabled = false;
        let _tocaDebugSyncTimer = null;
        let _tocaDebugSyncQueue = [];
        try {
            _tocaDebugEnabled = localStorage.getItem('toca.debug.enabled') === '1';
        } catch (e) { /* ignore */ }

        function isTocaDebugEnabled() { return !!_tocaDebugEnabled; }

        function setTocaDebugEnabled(enabled) {
            _tocaDebugEnabled = !!enabled;
            try { localStorage.setItem('toca.debug.enabled', _tocaDebugEnabled ? '1' : '0'); } catch (e) {}
            tocaDebug('debug.toggle', `Debug mode ${_tocaDebugEnabled ? 'ativado' : 'desativado'}`);
        }

        function tocaDebug(tag, message, data) {
            try {
                const entry = {
                    ts: new Date().toISOString(),
                    tag: String(tag || 'debug'),
                    message: String(message || ''),
                    data: data === undefined ? null : data
                };
                window._tocaDebugBuffer.push(entry);
                if (window._tocaDebugBuffer.length > TOCA_DEBUG_BUFFER_MAX) {
                    window._tocaDebugBuffer.splice(0, window._tocaDebugBuffer.length - TOCA_DEBUG_BUFFER_MAX);
                }
                if (_tocaDebugEnabled) {
                    try { console.log(`[toca:${entry.tag}]`, entry.message, entry.data ?? ''); } catch (e) {}
                    _tocaDebugSyncQueue.push(entry);
                    if (!_tocaDebugSyncTimer) {
                        _tocaDebugSyncTimer = setTimeout(_tocaDebugFlushSync, TOCA_DEBUG_SYNC_DEBOUNCE_MS);
                    }
                }
            } catch (e) { /* nunca deixar o logger derrubar a app */ }
        }

        async function _tocaDebugFlushSync() {
            _tocaDebugSyncTimer = null;
            if (!_tocaDebugSyncQueue.length) return;
            const batch = _tocaDebugSyncQueue.splice(0, _tocaDebugSyncQueue.length);
            try {
                await fetch(`${API_BASE}/config/logs/client`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ entries: batch })
                });
            } catch (e) { /* servidor indisponível: mantemos só o buffer local */ }
        }

        window.addEventListener('error', (ev) => {
            if (!_tocaDebugEnabled) return;
            tocaDebug('window.error', ev.message || 'Uncaught error', {
                source: ev.filename,
                line: ev.lineno,
                col: ev.colno
            });
        });
        window.addEventListener('unhandledrejection', (ev) => {
            if (!_tocaDebugEnabled) return;
            tocaDebug('promise.rejection', String(ev.reason || 'Unhandled rejection'));
        });

        async function loadSystemConfig() {
            try {
                const response = await fetch(`${API_BASE}/system/config`);
                if (!response.ok) return;
                systemConfig = await response.json();
                const versionEl = document.getElementById('sidebarVersion');
                if (versionEl && systemConfig.version) {
                    versionEl.textContent = `Versão ${systemConfig.version}`;
                }
                if ((systemConfig.env || '').toLowerCase() === 'beta') {
                    const logoContainer = document.querySelector('.sidebar-logo');
                    if (logoContainer && !logoContainer.querySelector('.beta-badge')) {
                        const betaBadge = document.createElement('span');
                        betaBadge.className = 'beta-badge';
                        betaBadge.textContent = 'BETA';
                        logoContainer.appendChild(betaBadge);
                    }
                }
            } catch (error) {
                console.error('Erro ao carregar config do sistema', error);
            }
        }
        let currentEditingClientId = null;
        let currentEditingActivityId = null;
        let clients = [];
        let activities = [];
        let statusConfig = { universal: { green_days: 7, yellow_days: 14 }, rules: [] };
        let userProfile = null;
        let integrationConfig = {
            tavily_configured: false,
            tavily_key_preview: '',
            openrouter_configured: false,
            openrouter_key_preview: '',
            openrouter_model: 'stepfun/step-3.5-flash:free',
            openrouter_site_url: 'http://localhost',
            openrouter_app_name: 'TocaDoCoelho'
        };
        let updateSourceConfig = {
            current_version: '',
            github_owner: '',
            github_repo: '',
            configured: false
        };
        let cachedPositions = [];
        let currentGroupModalContext = null;
        let selectedCompanyForActivity = '';
        let positionGroupings = [];
        let _orgMapOpenContext = null; // { company, position } quando aberto pelo + do mapeamento organizacional
        let wikiEntriesSortOrder = "az";
        let autoPicGoogleTab = null;
        let autoPicSlots = [null, null, null];
        let autoPicActiveSlot = 0;
        let kanbanColumns = [];
        let kanbanCards = [];
        let kanbanAccounts = [];
        let kanbanContacts = [];
        let kanbanDragState = { movedAt: 0, snapshot: null, sorting: false, rollbackCount: 0, requestInFlight: false };
        let kanbanSortableInstances = new Map();
        let _gestaoContaCurrentSubTab = 'accounts';
        let autoTocaMailingClients = [];
        let autoTocaMailingPositions = [];
        let autoTocaMailingAreas = [];
        let autoTocaMailingSelection = [];
        let _autoTocaMailingPreviewFiltered = [];

        // Tab switching
        // Rastreia a aba ativa anterior para detectar saída do iToca
        let _currentTab = 'dashboard';
        const TOPBAR_MODULE_COPY = {
            home: { title: 'Home', subtitle: 'Dashboard executivo de relacionamento com clientes.' },
            dashboard: { title: 'Dashboard', subtitle: 'Visão geral dos seus contatos e status de relacionamento' },
            iata: { title: 'iToca', subtitle: 'Seu assistente ligeirinho para apoiar sua operação comercial.' },
            wikitoca: { title: 'WikiToca', subtitle: 'Base de conhecimento e documentos da operação.' },
            kanban: { title: 'Kanban', subtitle: 'Acompanhamento visual de cards e prioridades.' },
            'gestao-conta': { title: 'Gestão de Conta', subtitle: 'Visão estratégica e mapeamento de contas.' },
            portfolio: { title: 'Portifólio', subtitle: 'Indicadores e visão consolidada do portifólio.' },
            autotoca: { title: 'AutoToca', subtitle: 'Automações e assistentes para tarefas comerciais.' },
            atividades: { title: 'Atividades', subtitle: 'Registro e acompanhamento de interações.' },
            agenda: { title: 'Agenda', subtitle: 'Compromissos, eventos e planejamento semanal.' },
            clientes: { title: 'Gestão de Contatos', subtitle: 'Cadastro e manutenção de contatos estratégicos.' },
            reports: { title: 'Reports', subtitle: 'Relatórios executivos e análise de relacionamento.' },
            configuracoes: { title: 'Configurações', subtitle: 'Parâmetros do sistema e integrações.' }
        };

        function updateTopbarModuleHeader(tabName) {
            const container = document.getElementById('topbarModuleTitle');
            if (!container) return;
            const copy = TOPBAR_MODULE_COPY[tabName] || TOPBAR_MODULE_COPY.dashboard;
            container.innerHTML = `<h1>${escapeHtml(copy.title)}</h1><p>${escapeHtml(copy.subtitle)}</p>`;
        }

        function updateTopbarSettingsState(tabName) {
            const settingsBtn = document.getElementById('topbarSettingsButton');
            if (!settingsBtn) return;
            const isActive = tabName === 'configuracoes';
            settingsBtn.classList.toggle('active', isActive);
            settingsBtn.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        }

        function ensureAutoTocaPresence() {
            const nav = document.querySelector('.sidebar-nav');
            if (!nav) return;

            let btn = nav.querySelector('.nav-item[onclick*="\'autotoca\'"]');
            const tab = document.getElementById('autotoca');

            if (!btn) {
                const atividadesBtn = nav.querySelector('.nav-item[onclick*="\'atividades\'"]');
                const html = `<button class="nav-item" onclick="switchTab(event, 'autotoca')"><i class="fas fa-wand-magic-sparkles"></i><span>AutoToca</span></button>`;
                if (atividadesBtn) atividadesBtn.insertAdjacentHTML('beforebegin', html);
                else nav.insertAdjacentHTML('beforeend', html);
                btn = nav.querySelector('.nav-item[onclick*="\'autotoca\'"]');
            }

            if (!tab) {
                const main = document.querySelector('.main-content');
                if (main) {
                    main.insertAdjacentHTML('beforeend', `
                        <div id="autotoca" class="tab-content">
                            <div class="page-header"><h1>AutoToca</h1><p>Módulo restaurado automaticamente. Recarregue a aplicação.</p></div>
                        </div>
                    `);
                }
            }
        }

        function switchTab(ev, tabName) {
            const previousTab = _currentTab;
            let requestedGestaoContaSubTab = null;

            if (tabName === 'mapeamento') {
                tabName = 'gestao-conta';
                requestedGestaoContaSubTab = 'environment';
            } else if (tabName === 'mapeamento-organizacional') {
                tabName = 'gestao-conta';
                requestedGestaoContaSubTab = 'org';
            }

            const targetTab = document.getElementById(tabName);
            if (!targetTab) {
                showError(`A aba "${tabName}" não foi encontrada. Tente recarregar a aplicação.`);
                return;
            }

            document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
            document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));

            targetTab.classList.add('active');
            _currentTab = tabName;
            updateTopbarModuleHeader(tabName);
            updateTopbarSettingsState(tabName);

            const mainContent = document.querySelector('.main-content');
            if (mainContent) mainContent.classList.toggle('iata-mode', tabName === 'iata');

            if (ev && ev.target && ev.target.closest('.nav-item')) {
                ev.target.closest('.nav-item').classList.add('active');
            } else {
                const btn = document.querySelector(`.nav-item[onclick*="'${tabName}'"]`);
                if (btn) btn.classList.add('active');
            }

            // Ao sair do iToca: salva a sessão no histórico e limpa o chat
            if (previousTab === 'iata' && tabName !== 'iata') {
                _itocaSaveSessionAndClear();
            }

            if (previousTab === 'autotoca' && tabName !== 'autotoca') {
                _addinStopPolling();
                if (typeof _cjResetForm === 'function') _cjResetForm();
            }

            if (tabName === 'home') loadHome();
            else if (tabName === 'dashboard') loadDashboard();
            else if (tabName === 'iata') {
                // Reativa input caso tenha ficado travado por um processo anterior
                const iataEl = document.getElementById('iataText');
                const iataBtn = document.getElementById('iataAskBtn');
                if (iataEl) { iataEl.disabled = false; }
                if (iataBtn) { iataBtn.disabled = false; }
                clearITocaChat();
                loadITocaHistory();
                loadITocaBaseStatus();
            }
            else if (tabName === 'clientes') loadClients();
            else if (tabName === 'atividades') { loadActivities(); }
            else if (tabName === 'autotoca') { loadAutoToca(); loadReports(); _addinStartPolling(); _initOutlookAddinManifestUrl(); }
            else if (tabName === 'agenda') loadAgenda();
            else if (tabName === 'kanban') loadKanban();
            else if (tabName === 'gestao-conta') switchGestaoContaSubmodule(requestedGestaoContaSubTab || _gestaoContaCurrentSubTab || 'accounts');
            else if (tabName === 'portfolio') loadPortfolio();
            else if (tabName === 'campanha') loadCampanha();
            else if (tabName === 'wikitoca') loadWikiTocaData();
            else if (tabName === 'configuracoes') loadSettings();
        }

        function switchGestaoContaSubmodule(subTab = 'accounts') {
            const allowed = new Set(['accounts', 'environment', 'org', 'planning']);
            const next = allowed.has(subTab) ? subTab : 'accounts';
            _gestaoContaCurrentSubTab = next;

            const tabs = [
                { key: 'accounts', panelId: 'gestaoContaSubPanel_accounts', btnId: 'gestaoContaSubBtn_accounts', loader: loadAccounts, activeClass: 'btn-auto-mapping', inactiveClass: 'btn-secondary' },
                { key: 'environment', panelId: 'gestaoContaSubPanel_environment', btnId: 'gestaoContaSubBtn_environment', loader: loadMapeamento, activeClass: 'btn-auto-mapping', inactiveClass: 'btn-secondary' },
                { key: 'org', panelId: 'gestaoContaSubPanel_org', btnId: 'gestaoContaSubBtn_org', loader: loadOrganizationalMapping, activeClass: 'btn-auto-mapping', inactiveClass: 'btn-secondary' },
                { key: 'planning', panelId: 'gestaoContaSubPanel_planning', btnId: 'gestaoContaSubBtn_planning', loader: initAccountPlanning, activeClass: 'btn-auto-mapping', inactiveClass: 'btn-secondary' }
            ];

            tabs.forEach(item => {
                const panel = document.getElementById(item.panelId);
                const btn = document.getElementById(item.btnId);
                const isActive = item.key === next;
                if (panel) {
                    panel.style.display = isActive ? '' : 'none';
                    panel.classList.toggle('active-sub', isActive);
                }
                if (btn) {
                    btn.classList.toggle(item.activeClass, isActive);
                    btn.classList.toggle(item.inactiveClass, !isActive);
                }
            });

            const active = tabs.find(item => item.key === next);
            if (active?.loader) active.loader();
        }

        async function loadSettings() {
            setupSettingsCards();
            await Promise.all([loadStatusConfig(), loadUserProfile(), loadPositions(), loadPositionGroupings(), loadMessageTemplates(), loadUiConfig(), loadIntegrationConfig(), loadUpdateSourceConfig(), loadStartupConfig(), loadThemeConfig()]);
            loadDebugLogsConfig();
            renderSettings();
        }

        // ── Microsoft Graph OAuth ─────────────────────────────────────────────

        async function loadOutlookGraphStatus() {
            try {
                const res = await fetch(`${API_BASE}/outlook/graph-status`);
                const data = await res.json();
                const statusArea = document.getElementById('graphStatusArea');
                const connectedArea = document.getElementById('graphConnectedArea');
                const emailEl = document.getElementById('graphConnectedEmail');
                const graphSyncBtn = document.getElementById('outlookGraphSyncBtn');
                const hint = document.getElementById('outlookSyncHint');
                if (data.connected) {
                    if (statusArea) statusArea.style.display = 'none';
                    if (connectedArea) connectedArea.style.display = '';
                    if (emailEl) emailEl.textContent = data.email || 'conta conectada';
                    if (graphSyncBtn) graphSyncBtn.style.display = '';
                    if (hint) hint.style.display = 'none';
                } else {
                    if (statusArea) statusArea.style.display = '';
                    if (connectedArea) connectedArea.style.display = 'none';
                    if (graphSyncBtn) graphSyncBtn.style.display = 'none';
                    if (hint) hint.style.display = '';
                }
            } catch (e) { /* silently ignore */ }
        }

        async function connectMicrosoft365() {
            const res = await fetch(`${API_BASE}/outlook/oauth/start`).catch(() => null);
            if (!res || !res.ok) {
                const err = res ? (await res.json()).error : 'Erro de rede';
                await uiConfirm(err || 'Verifique as credenciais nas Configurações.', 'Falha ao conectar');
                return;
            }
            const data = await res.json();
            if (!data.auth_url) {
                await uiConfirm(data.error || 'Configure Tenant ID e Client ID antes de conectar.', 'Configuração ausente');
                showGraphConfigForm();
                return;
            }
            window.open(data.auth_url, '_blank', 'width=520,height=640,noopener');
        }

        async function disconnectMicrosoft365() {
            if (!await uiConfirm('Deseja desconectar a conta Microsoft 365? Será necessário reconectar para sincronizar via Graph.', 'Desconectar')) return;
            await fetch(`${API_BASE}/outlook/graph-disconnect`, {method: 'DELETE'});
            loadOutlookGraphStatus();
        }

        async function syncOutlookGraph(daysOverride) {
            const days = parseInt(daysOverride || document.getElementById('outlookSyncDays')?.value || '30');
            const statusEl = document.getElementById('outlookImportStatus');
            const btn = document.getElementById('outlookGraphSyncBtn');
            if (btn) { btn.disabled = true; btn.innerHTML = '<span class="ai-star-icon">✦</span> Lendo emails...'; }
            if (statusEl) statusEl.innerHTML = '<span style="color:#2563eb;">Conectando ao Microsoft 365...</span>';
            const evtSource = new EventSource(`${API_BASE}/outlook/sync-stream-graph?days=${days}`);
            evtSource.onmessage = e => {
                const d = JSON.parse(e.data);
                if (d.phase === 'connecting' || d.phase === 'reading') {
                    if (statusEl) statusEl.innerHTML = `<span style="color:#2563eb;">${d.message}</span>`;
                } else if (d.phase === 'done') {
                    evtSource.close();
                    if (btn) { btn.disabled = false; btn.innerHTML = '<span class="ai-star-icon">✦</span> Sync Microsoft 365'; }
                    if (statusEl) statusEl.innerHTML = '';
                    _openOutlookReviewModal(d);
                } else if (d.phase === 'error') {
                    evtSource.close();
                    if (btn) { btn.disabled = false; btn.innerHTML = '<span class="ai-star-icon">✦</span> Sync Microsoft 365'; }
                    if (statusEl) statusEl.innerHTML = `<span style="color:#dc2626;">${d.message}</span>`;
                    if (d.error_type === 'oauth_authentication') {
                        loadOutlookGraphStatus();
                    }
                }
            };
            evtSource.onerror = () => {
                evtSource.close();
                if (btn) { btn.disabled = false; btn.innerHTML = '<span class="ai-star-icon">✦</span> Sync Microsoft 365'; }
                if (statusEl) statusEl.innerHTML = '<span style="color:#dc2626;">Conexão perdida. Tente novamente.</span>';
            };
        }

        // Navega até o painel de Sync Outlook do AutoToca
        function _gotoSyncOutlookPanel() {
            try {
                switchTab(null, 'autotoca');
                toggleAutoTocaAutomation('sync-outlook');
            } catch (e) { /* ignore */ }
        }

        // Trata mensagens vindas da janela popup de conexão (outlook-connected.html)
        function _handleOutlookPopupMessage(payload) {
            if (!payload || !payload.action) return;
            if (payload.action === 'connected') {
                loadOutlookGraphStatus();
                const statusArea = document.getElementById('autotocaExtensionStatus');
                if (statusArea) {
                    statusArea.style.display = '';
                    statusArea.textContent = 'Microsoft 365 conectado com sucesso! Use o botão "Sync Microsoft 365" para importar emails.';
                    setTimeout(() => { statusArea.style.display = 'none'; }, 6000);
                }
            } else if (payload.action === 'start-sync') {
                const sel = document.getElementById('outlookSyncDays');
                if (sel && payload.days) sel.value = String(payload.days);
                _gotoSyncOutlookPanel();
                setTimeout(() => syncOutlookGraph(payload.days), 250);
            }
        }

        (function _initOutlookPopupBridge() {
            // Canal moderno (mesma origem) entre o popup de conexão e a janela principal
            try {
                const ch = new BroadcastChannel('toca-outlook');
                ch.onmessage = (e) => _handleOutlookPopupMessage(e.data);
            } catch (e) { /* navegador sem BroadcastChannel — usa fallback abaixo */ }

            // Fallback via localStorage (dispara em outras janelas da mesma origem)
            window.addEventListener('storage', (e) => {
                if (e.key === 'toca-outlook-msg' && e.newValue) {
                    try { _handleOutlookPopupMessage(JSON.parse(e.newValue)); } catch (_) {}
                }
            });

            // Compatibilidade: se algum fluxo antigo cair em /?graph_error
            const params = new URLSearchParams(window.location.search);
            if (params.has('graph_error')) {
                const err = params.get('graph_error');
                history.replaceState(null, '', window.location.pathname);
                setTimeout(() => uiConfirm(decodeURIComponent(err), 'Erro na autenticação Microsoft 365'), 300);
            }
        })();

        async function loadStartupConfig() {
            try {
                const res = await fetch('/api/config/startup');
                const data = await res.json();
                const card = document.getElementById('startupSettingsCard');
                const toggle = document.getElementById('startupToggle');
                const label = document.getElementById('startupToggleLabel');
                if (!toggle) return;
                if (!data.supported) {
                    if (card) card.style.display = 'none';
                    return;
                }
                toggle.checked = data.enabled;
                toggle.disabled = false;
                if (label) label.textContent = data.enabled ? 'Ativado' : 'Desativado';
            } catch (e) {
                console.error('Erro ao carregar config de inicialização:', e);
            }
        }

        async function setStartupConfig(enabled) {
            const toggle = document.getElementById('startupToggle');
            const label = document.getElementById('startupToggleLabel');
            const status = document.getElementById('startupSettingStatus');
            if (toggle) toggle.disabled = true;
            try {
                const res = await fetch('/api/config/startup', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({enabled})
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Erro desconhecido');
                if (label) label.textContent = enabled ? 'Ativado' : 'Desativado';
                if (status) {
                    status.textContent = enabled ? 'O app será iniciado automaticamente com o Windows.' : 'Inicialização automática desativada.';
                    setTimeout(() => { status.textContent = ''; }, 3000);
                }
            } catch (e) {
                if (toggle) toggle.checked = !enabled;
                if (label) label.textContent = !enabled ? 'Ativado' : 'Desativado';
                if (status) status.textContent = 'Erro ao salvar: ' + e.message;
            } finally {
                if (toggle) toggle.disabled = false;
            }
        }

        // =====================================================
        // Painel "Logs de Depuração" em Configurações
        // =====================================================
        function loadDebugLogsConfig() {
            const toggle = document.getElementById('debugLogsEnabledToggle');
            const label = document.getElementById('debugLogsEnabledLabel');
            if (toggle) toggle.checked = isTocaDebugEnabled();
            if (label) label.textContent = isTocaDebugEnabled() ? 'Ativado' : 'Desativado';
        }

        function onDebugLogsToggle(enabled) {
            setTocaDebugEnabled(!!enabled);
            const label = document.getElementById('debugLogsEnabledLabel');
            if (label) label.textContent = enabled ? 'Ativado' : 'Desativado';
            if (enabled) showSuccess('Modo depuração ativado. Eventos serão capturados a partir de agora.');
            else showInfo('Modo depuração desativado.');
        }

        async function refreshDebugLogsViewer() {
            const viewer = document.getElementById('debugLogsViewer');
            const meta = document.getElementById('debugLogsMeta');
            if (!viewer) return;
            viewer.textContent = 'Carregando logs do servidor...';
            try {
                // Antes de buscar, força um flush do buffer local para que o viewer
                // já mostre os eventos mais recentes do cliente que ainda não foram enviados.
                if (isTocaDebugEnabled()) {
                    try { await _tocaDebugFlushSync(); } catch (e) {}
                }
                const response = await fetch(`${API_BASE}/config/logs?limit=500`);
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);

                const serverLines = Array.isArray(data.lines) ? data.lines : [];
                const clientBuffer = (window._tocaDebugBuffer || []).map(e => {
                    const payload = e.data == null ? '' : ` data=${JSON.stringify(e.data)}`;
                    return `[${e.ts}] [CLIENT] [${e.tag}] ${e.message}${payload}`;
                });

                const combined = [
                    '===== SERVIDOR (últimas ' + serverLines.length + ' linhas) =====',
                    ...serverLines,
                    '',
                    '===== CLIENTE (buffer local — ' + clientBuffer.length + ' entradas) =====',
                    ...clientBuffer
                ];
                viewer.textContent = combined.join('\n');
                viewer.scrollTop = viewer.scrollHeight;

                if (meta) {
                    const sizeKb = data.size ? (data.size / 1024).toFixed(1) : '0.0';
                    meta.textContent = `Servidor: ${data.total_lines || 0} linhas (${sizeKb} KB) • Cliente: ${clientBuffer.length} entradas`;
                }
            } catch (e) {
                viewer.textContent = 'Erro ao carregar logs: ' + (e.message || e);
                if (meta) meta.textContent = '';
            }
        }

        function downloadDebugLogs() {
            const viewer = document.getElementById('debugLogsViewer');
            const content = viewer ? viewer.textContent : '';
            if (!content || content.startsWith('Clique em "Atualizar"')) {
                showInfo('Clique em "Atualizar" primeiro para carregar os logs.');
                return;
            }
            try {
                const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                const stamp = new Date().toISOString().replace(/[:.]/g, '-');
                a.href = url;
                a.download = `toca-debug-logs-${stamp}.txt`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                setTimeout(() => URL.revokeObjectURL(url), 1000);
                tocaDebug('debug.download', 'Logs baixados', { bytes: content.length });
            } catch (e) {
                showError('Falha ao gerar o arquivo: ' + (e.message || e));
            }
        }

        function clearClientDebugBuffer() {
            const count = (window._tocaDebugBuffer || []).length;
            window._tocaDebugBuffer = [];
            _tocaDebugSyncQueue = [];
            showSuccess(`Buffer do cliente limpo (${count} entradas removidas).`);
            refreshDebugLogsViewer();
        }

        let _outlookEventSource = null;
        let _outlookPendingActivities = [];

        let _outlookAllClients = [];

        async function syncOutlookEmails() {
            const btn = document.getElementById('outlookSyncBtn');
            const days = parseInt(document.getElementById('outlookSyncDays')?.value || '30');
            const statusEl = document.getElementById('outlookImportStatus');

            if (btn) btn.disabled = true;
            if (statusEl) statusEl.innerHTML = '';

            // Diagnóstico rápido antes de iniciar
            try {
                const diag = await fetch('/api/outlook/diagnose').then(r => r.json());
                if (!diag.can_sync) {
                    const problems = (diag.checks || []).filter(c => !c.ok).map(c => c.detail).join(' | ');
                    if (statusEl) statusEl.innerHTML = `<span style="color:#f59e0b;">⚠ ${escapeHtml(problems || 'Outlook não configurado.')}</span>`;
                    if (btn) btn.disabled = false;
                    return;
                }
                _outlookAllClients = diag.all_clients || [];
                if (diag.clients_with_email === 0 && statusEl) {
                    statusEl.innerHTML = `<span style="color:#f59e0b;">⚠ Nenhum cliente tem email cadastrado — o match pode retornar zero resultados. Cadastre emails nos clientes primeiro.</span>`;
                }
            } catch (_) {}

            // Abrir modal de progresso
            const modal = document.getElementById('outlookProgressModal');
            if (modal) modal.style.display = 'flex';
            _setOutlookProgress('Conectando ao Outlook...', '');

            // Fechar stream anterior se existir
            if (_outlookEventSource) { _outlookEventSource.close(); _outlookEventSource = null; }

            _outlookEventSource = new EventSource(`/api/outlook/sync-stream?days=${days}`);

            _outlookEventSource.onmessage = (e) => {
                try {
                    const data = JSON.parse(e.data);
                    if (data.phase === 'connecting') {
                        _setOutlookProgress(data.message, '');
                    } else if (data.phase === 'reading') {
                        _setOutlookProgress(data.message, data.count ? `${data.count} email(s) lidos até agora` : '');
                    } else if (data.phase === 'matching') {
                        _setOutlookProgress(data.message, `${data.count} emails no total`);
                    } else if (data.phase === 'done') {
                        _outlookEventSource.close(); _outlookEventSource = null;
                        _closeOutlookProgressModal();
                        if (btn) btn.disabled = false;
                        if (data.all_clients) _outlookAllClients = data.all_clients;
                        _openOutlookReviewModal(data);
                    } else if (data.phase === 'error') {
                        _outlookEventSource.close(); _outlookEventSource = null;
                        _closeOutlookProgressModal();
                        if (btn) btn.disabled = false;
                        if (statusEl) statusEl.innerHTML = `<span style="color:#ef4444;">Erro: ${escapeHtml(data.message)}</span>`;
                    }
                } catch (_) {}
            };

            _outlookEventSource.onerror = () => {
                if (_outlookEventSource) { _outlookEventSource.close(); _outlookEventSource = null; }
                _closeOutlookProgressModal();
                if (btn) btn.disabled = false;
                if (statusEl) statusEl.innerHTML = '<span style="color:#ef4444;">Erro na conexão com o servidor. Tente novamente.</span>';
            };
        }

        function _setOutlookProgress(msg, count) {
            const m = document.getElementById('outlookProgressMsg');
            const c = document.getElementById('outlookProgressCount');
            if (m) m.textContent = msg;
            if (c) c.textContent = count || '';
        }

        function _closeOutlookProgressModal() {
            const modal = document.getElementById('outlookProgressModal');
            if (modal) modal.style.display = 'none';
        }

        function cancelOutlookSync() {
            if (_outlookEventSource) { _outlookEventSource.close(); _outlookEventSource = null; }
            _closeOutlookProgressModal();
            const btn = document.getElementById('outlookSyncBtn');
            if (btn) btn.disabled = false;
        }

        let _outlookUnmatchedItems = [];
        let _outlookCurrentTab = 'matched';

        function _outlookTab(tab) {
            _outlookCurrentTab = tab;
            const m = document.getElementById('outlookTabMatched');
            const u = document.getElementById('outlookTabUnmatched');
            const mb = document.getElementById('outlookTabMatchedBtn');
            const ub = document.getElementById('outlookTabUnmatchedBtn');
            const activeStyle = 'color:#10b981;border-bottom:2px solid #10b981;font-weight:600;';
            const inactiveStyle = 'color:#9ca3af;border-bottom:2px solid transparent;font-weight:500;';
            if (tab === 'matched') {
                if (m) m.style.display = '';
                if (u) u.style.display = 'none';
                if (mb) mb.style.cssText = mb.style.cssText.replace(/color:[^;]+;/, '').replace(/border-bottom:[^;]+;/, '').replace(/font-weight:[^;]+;/, '') + activeStyle;
                if (ub) ub.style.cssText = ub.style.cssText.replace(/color:[^;]+;/, '').replace(/border-bottom:[^;]+;/, '').replace(/font-weight:[^;]+;/, '') + inactiveStyle;
            } else {
                if (m) m.style.display = 'none';
                if (u) u.style.display = '';
                if (mb) mb.style.cssText = mb.style.cssText.replace(/color:[^;]+;/, '').replace(/border-bottom:[^;]+;/, '').replace(/font-weight:[^;]+;/, '') + inactiveStyle;
                if (ub) ub.style.cssText = ub.style.cssText.replace(/color:[^;]+;/, '').replace(/border-bottom:[^;]+;/, '').replace(/font-weight:[^;]+;/, '') + activeStyle;
            }
        }

        function _outlookRenderItem(act, i) {
            const dt = new Date(act.date);
            const dateStr = isNaN(dt) ? act.date : dt.toLocaleDateString('pt-BR');
            const dirIcon = act.direction === 'received' ? '←' : '→';
            const preview = (act.body_preview || '').slice(0, 180);
            const initial = (act.client_name || '?')[0].toUpperCase();
            const avatar = act.client_photo_url
                ? `<img src="${escapeHtml(act.client_photo_url)}" class="outlook-review-avatar" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'"><span class="outlook-review-avatar-placeholder" style="display:none;">${escapeHtml(initial)}</span>`
                : `<span class="outlook-review-avatar-placeholder">${escapeHtml(initial)}</span>`;
            return `<div class="outlook-review-item">
                <input type="checkbox" class="outlook-item-check" data-index="${i}" checked onchange="_updateOutlookConfirmBtn()" style="margin-top:10px;cursor:pointer;accent-color:#10b981;">
                ${avatar}
                <div class="outlook-review-body">
                    <div class="outlook-review-header">
                        <span class="outlook-review-name">${escapeHtml(act.client_name)}</span>
                        <span class="outlook-review-date">${escapeHtml(dateStr)}</span>
                        <span class="outlook-review-dir">${dirIcon} ${escapeHtml(act.counterpart_label)}: ${escapeHtml(act.counterpart_name)}</span>
                    </div>
                    <div class="outlook-review-subject">${escapeHtml(act.subject || '(sem assunto)')}${(act.email_count > 1) ? ` <span style="font-size:11px;font-weight:600;color:#2563eb;background:#eff6ff;border:1px solid #bfdbfe;border-radius:99px;padding:1px 7px;margin-left:4px;">🧵 ${act.email_count} emails</span>` : ''}</div>
                    ${preview ? `<div class="outlook-review-preview">${escapeHtml(preview)}</div>` : ''}
                </div>
            </div>`;
        }

        function _outlookRenderUnmatched(item, i) {
            const dt = new Date(item.date);
            const dateStr = isNaN(dt) ? item.date : dt.toLocaleDateString('pt-BR');
            const dirIcon = item.direction === 'received' ? '←' : '→';
            const preview = (item.body_preview || '').slice(0, 140);
            const clientOptions = (_outlookAllClients || []).map(c =>
                `<option value="${c.id}">${escapeHtml(c.name)}${c.company ? ' — ' + escapeHtml(c.company) : ''}</option>`
            ).join('');
            return `<div class="outlook-review-item" style="border-left:3px solid #fbbf24;padding-left:8px;">
                <input type="checkbox" class="outlook-unmatched-check" data-uindex="${i}" onchange="_updateOutlookConfirmBtn()" style="margin-top:10px;cursor:pointer;accent-color:#f59e0b;">
                <div class="outlook-review-body" style="flex:1;">
                    <div class="outlook-review-header">
                        <span style="font-size:12px;color:#92400e;background:#fef3c7;padding:2px 6px;border-radius:4px;">⚠ Sem cliente</span>
                        <span class="outlook-review-date">${escapeHtml(dateStr)}</span>
                        <span class="outlook-review-dir">${dirIcon} ${escapeHtml(item.counterpart_label)}: ${escapeHtml(item.counterpart_name)} &lt;${escapeHtml(item.counterpart_email)}&gt;</span>
                    </div>
                    <div class="outlook-review-subject">${escapeHtml(item.subject || '(sem assunto)')}</div>
                    ${preview ? `<div class="outlook-review-preview">${escapeHtml(preview)}</div>` : ''}
                    <div style="margin-top:6px;">
                        <select class="outlook-unmatched-client" data-uindex="${i}" style="font-size:12px;padding:3px 6px;border-radius:5px;border:1px solid #d1fae5;width:100%;max-width:340px;">
                            <option value="">— Selecionar cliente para importar —</option>
                            ${clientOptions}
                        </select>
                    </div>
                </div>
            </div>`;
        }

        function _openOutlookReviewModal(data) {
            _outlookPendingActivities = data.activities || [];
            _outlookUnmatchedItems = data.unmatched || [];
            if (data.all_clients) _outlookAllClients = data.all_clients;
            const modal = document.getElementById('outlookReviewModal');
            const summary = document.getElementById('outlookReviewSummary');
            const list = document.getElementById('outlookReviewList');
            const unmatchedList = document.getElementById('outlookUnmatchedList');
            const selectAll = document.getElementById('outlookSelectAll');
            const statusEl = document.getElementById('outlookImportStatus');

            if (statusEl) statusEl.innerHTML = '';
            if (selectAll) selectAll.checked = true;

            if (!_outlookPendingActivities.length && !_outlookUnmatchedItems.length) {
                if (statusEl) statusEl.innerHTML = `<span style="color:#6b7280;">${escapeHtml(data.message || 'Nenhum email encontrado.')}</span>`;
                return;
            }

            if (summary) summary.textContent = `${data.total_read || 0} email(s) lidos · ${_outlookPendingActivities.length} com cliente encontrado`;

            const matchedCount = document.getElementById('outlookTabMatchedCount');
            const unmatchedCount = document.getElementById('outlookTabUnmatchedCount');
            if (matchedCount) matchedCount.textContent = `(${_outlookPendingActivities.length})`;
            if (unmatchedCount) unmatchedCount.textContent = `(${_outlookUnmatchedItems.length})`;

            if (list) list.innerHTML = _outlookPendingActivities.map((act, i) => _outlookRenderItem(act, i)).join('') || '<p style="color:#9ca3af;font-size:13px;padding:8px;">Nenhum email com cliente correspondente.</p>';
            if (unmatchedList) unmatchedList.innerHTML = _outlookUnmatchedItems.map((item, i) => _outlookRenderUnmatched(item, i)).join('') || '<p style="color:#9ca3af;font-size:13px;padding:8px;">Nenhum email sem correspondência.</p>';

            _outlookTab('matched');
            _updateOutlookConfirmBtn();
            if (modal) modal.style.display = 'flex';
        }

        function _updateOutlookConfirmBtn() {
            const matched = Array.from(document.querySelectorAll('.outlook-item-check')).filter(c => c.checked).length;
            const unmatchedWithClient = Array.from(document.querySelectorAll('.outlook-unmatched-check')).filter(chk => {
                if (!chk.checked) return false;
                const idx = chk.dataset.uindex;
                const sel = document.querySelector(`.outlook-unmatched-client[data-uindex="${idx}"]`);
                return sel && sel.value;
            }).length;
            const total = matched + unmatchedWithClient;
            const label = document.getElementById('outlookConfirmLabel');
            const btn = document.getElementById('outlookConfirmBtn');
            if (label) label.textContent = `Importar ${total} atividade${total !== 1 ? 's' : ''}`;
            if (btn) btn.disabled = total === 0;
        }

        function toggleAllOutlookItems(checked) {
            document.querySelectorAll('.outlook-item-check').forEach(c => c.checked = checked);
            _updateOutlookConfirmBtn();
        }

        function closeOutlookReview() {
            const modal = document.getElementById('outlookReviewModal');
            if (modal) modal.style.display = 'none';
            _outlookPendingActivities = [];
            _outlookUnmatchedItems = [];
        }

        // ── Importação — minimizar/restaurar e resultado detalhado ───────────
        let _outlookImportMinimized = false;

        function _minimizeOutlookImport() {
            document.getElementById('outlookImportProgressModal').style.display = 'none';
            const mini = document.getElementById('outlookImportMini');
            if (mini) { mini.style.display = 'flex'; }
            _outlookImportMinimized = true;
        }

        function _restoreOutlookImport() {
            document.getElementById('outlookImportProgressModal').style.display = 'flex';
            const mini = document.getElementById('outlookImportMini');
            if (mini) mini.style.display = 'none';
            _outlookImportMinimized = false;
        }

        function _hideOutlookImportUI() {
            document.getElementById('outlookImportProgressModal').style.display = 'none';
            const mini = document.getElementById('outlookImportMini');
            if (mini) mini.style.display = 'none';
            _outlookImportMinimized = false;
        }

        function closeOutlookImportResult() {
            const modal = document.getElementById('outlookImportResultModal');
            if (modal) modal.style.display = 'none';
        }

        function _showOutlookImportResult(result) {
            const modal = document.getElementById('outlookImportResultModal');
            const msgEl = document.getElementById('outlookImportResultMsg');
            const bodyEl = document.getElementById('outlookImportResultBody');
            if (!modal || !msgEl || !bodyEl) return;

            msgEl.textContent = result.message || '';

            const imported = result.imported_items || [];
            const skipped = result.skipped_items || [];
            let html = '';

            if (imported.length) {
                html += `<div style="margin-bottom:14px;">
                    <div style="font-size:12px;font-weight:700;color:#065f46;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;">
                        ✓ Registradas (${imported.length})
                    </div>
                    <div style="display:flex;flex-direction:column;gap:4px;">`;
                for (const it of imported) {
                    html += `<div style="display:flex;gap:8px;font-size:13px;padding:6px 10px;background:#f0fdf4;border-radius:6px;align-items:flex-start;">
                        <span style="color:#10b981;flex-shrink:0;">✓</span>
                        <span><strong>${escapeHtml(it.client_name)}</strong> — ${escapeHtml(it.subject)}${it.date ? ` <span style="color:#9ca3af;">(${it.date})</span>` : ''}</span>
                    </div>`;
                }
                html += `</div></div>`;
            }

            if (skipped.length) {
                html += `<div>
                    <div style="font-size:12px;font-weight:700;color:#92400e;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;">
                        ↩ Ignoradas — já existiam (${skipped.length})
                    </div>
                    <div style="display:flex;flex-direction:column;gap:4px;">`;
                for (const it of skipped) {
                    html += `<div style="display:flex;gap:8px;font-size:13px;padding:6px 10px;background:#fffbeb;border-radius:6px;align-items:flex-start;">
                        <span style="color:#d97706;flex-shrink:0;">↩</span>
                        <span><strong>${escapeHtml(it.client_name)}</strong> — ${escapeHtml(it.subject)}</span>
                    </div>`;
                }
                html += `</div></div>`;
            }

            bodyEl.innerHTML = html;
            modal.style.display = 'flex';
        }

        function closeOutlookSuggestions() {
            const modal = document.getElementById('outlookSuggestionsModal');
            if (modal) modal.style.display = 'none';
        }

        let _outlookPendingSuggestions = null;

        function _openSuggestionsModal(result) {
            const modal = document.getElementById('outlookSuggestionsModal');
            const body = document.getElementById('outlookSuggestionsBody');
            const msg = document.getElementById('outlookSuggestImportMsg');
            if (!modal || !body) return;

            const statusSugs = result.status_suggestions || [];
            const kanbanSugs = result.kanban_suggestions || [];
            if (!statusSugs.length && !kanbanSugs.length) return;

            _outlookPendingSuggestions = result;
            if (msg) msg.textContent = result.message || '';

            let html = '';
            if (statusSugs.length) {
                html += `<div style="margin-bottom:16px;"><h4 style="font-size:13px;font-weight:600;color:#374151;margin:0 0 8px;">Atualização de relacionamento</h4>`;
                statusSugs.forEach((s, i) => {
                    const cur = s.current_stage ? s.current_stage : '(não definido)';
                    html += `<div style="display:flex;align-items:flex-start;gap:10px;padding:8px 10px;background:#f9fafb;border-radius:6px;margin-bottom:6px;">
                        <input type="checkbox" class="outlook-stage-check" data-idx="${i}" checked style="margin-top:2px;accent-color:#10b981;">
                        <div style="font-size:13px;">
                            <strong>${escapeHtml(s.client_name)}</strong>:
                            <span style="color:#6b7280;">${escapeHtml(cur)}</span>
                            → <span style="color:#065f46;font-weight:600;">${escapeHtml(s.suggested_label)}</span>
                            <div style="color:#9ca3af;font-size:12px;margin-top:2px;">${escapeHtml(s.reason)}</div>
                        </div>
                    </div>`;
                });
                html += '</div>';
            }
            if (kanbanSugs.length) {
                html += `<div><h4 style="font-size:13px;font-weight:600;color:#374151;margin:0 0 8px;">Mover cards no Kanban</h4>`;
                kanbanSugs.forEach((k, i) => {
                    html += `<div style="display:flex;align-items:flex-start;gap:10px;padding:8px 10px;background:#f9fafb;border-radius:6px;margin-bottom:6px;">
                        <input type="checkbox" class="outlook-kanban-check" data-idx="${i}" checked style="margin-top:2px;accent-color:#10b981;">
                        <div style="font-size:13px;">
                            <strong>${escapeHtml(k.card_title)}</strong>:
                            <span style="color:#6b7280;">${escapeHtml(k.current_column)}</span>
                            → <span style="color:#065f46;font-weight:600;">${escapeHtml(k.suggested_column)}</span>
                            <div style="color:#9ca3af;font-size:12px;margin-top:2px;">${escapeHtml(k.reason)}</div>
                        </div>
                    </div>`;
                });
                html += '</div>';
            }
            body.innerHTML = html;
            modal.style.display = 'flex';
        }

        async function applyOutlookSuggestions() {
            if (!_outlookPendingSuggestions) return;
            const statusSugs = _outlookPendingSuggestions.status_suggestions || [];
            const kanbanSugs = _outlookPendingSuggestions.kanban_suggestions || [];

            const statusUpdates = Array.from(document.querySelectorAll('.outlook-stage-check'))
                .filter(c => c.checked)
                .map(c => {
                    const s = statusSugs[parseInt(c.dataset.idx)];
                    return s ? {client_id: s.client_id, stage: s.suggested_stage} : null;
                }).filter(Boolean);

            const kanbanMoves = Array.from(document.querySelectorAll('.outlook-kanban-check'))
                .filter(c => c.checked)
                .map(c => {
                    const k = kanbanSugs[parseInt(c.dataset.idx)];
                    return k ? {card_id: k.card_id, column_id: k.suggested_column_id} : null;
                }).filter(Boolean);

            const btn = document.getElementById('outlookApplySuggestBtn');
            const applyStatus = document.getElementById('outlookApplySuggestStatus');
            if (btn) btn.disabled = true;
            try {
                const res = await fetch('/api/outlook/apply-suggestions', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({status_updates: statusUpdates, kanban_moves: kanbanMoves})
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Erro');
                if (applyStatus) applyStatus.innerHTML = `<span style="color:#10b981;">✓ ${escapeHtml(data.message)}</span>`;
                setTimeout(closeOutlookSuggestions, 1500);
            } catch (e) {
                if (applyStatus) applyStatus.innerHTML = `<span style="color:#ef4444;">Erro: ${escapeHtml(e.message)}</span>`;
                if (btn) btn.disabled = false;
            }
        }

        async function confirmOutlookImport() {
            const matchedChecks = Array.from(document.querySelectorAll('.outlook-item-check'));
            const selectedMatched = matchedChecks
                .filter(c => c.checked)
                .map(c => _outlookPendingActivities[parseInt(c.dataset.index)])
                .filter(Boolean);

            const unmatchedChecks = Array.from(document.querySelectorAll('.outlook-unmatched-check'));
            const selectedUnmatched = unmatchedChecks
                .filter(chk => chk.checked)
                .map(chk => {
                    const idx = chk.dataset.uindex;
                    const sel = document.querySelector(`.outlook-unmatched-client[data-uindex="${idx}"]`);
                    const clientId = sel ? parseInt(sel.value) : 0;
                    if (!clientId) return null;
                    const item = _outlookUnmatchedItems[parseInt(idx)];
                    if (!item) return null;
                    return Object.assign({}, item, {client_id: clientId});
                }).filter(Boolean);

            const allSelected = [...selectedMatched, ...selectedUnmatched];
            if (!allSelected.length) return;

            closeOutlookReview();

            // Mostrar modal de progresso de import
            const importFill = document.getElementById('outlookImportFill');
            const importStep = document.getElementById('outlookImportStep');
            const importMiniStep = document.getElementById('outlookImportMiniStep');
            _outlookImportMinimized = false;
            document.getElementById('outlookImportProgressModal').style.display = 'flex';
            document.getElementById('outlookImportMini').style.display = 'none';
            if (importFill) importFill.style.width = '5%';
            if (importStep) importStep.textContent = 'Iniciando...';

            try {
                const res = await fetch('/api/outlook/confirm-import', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({activities: allSelected})
                });
                const startData = await res.json();
                if (!res.ok) throw new Error(startData.error || 'Erro ao iniciar');

                const taskId = startData.task_id;

                // Polling
                await new Promise((resolve, reject) => {
                    const poll = setInterval(async () => {
                        try {
                            const statusRes = await fetch(`/api/outlook/confirm-tasks/${taskId}`);
                            const taskData = await statusRes.json();
                            if (importFill) importFill.style.width = `${taskData.progress || 5}%`;
                            if (importStep) importStep.textContent = taskData.step || '';
                            if (importMiniStep) importMiniStep.textContent = taskData.step || 'Importando...';
                            if (taskData.status === 'done') {
                                clearInterval(poll);
                                resolve(taskData.result);
                            } else if (taskData.status === 'error') {
                                clearInterval(poll);
                                reject(new Error(taskData.step || 'Erro desconhecido'));
                            }
                        } catch (pollErr) {
                            clearInterval(poll);
                            reject(pollErr);
                        }
                    }, 800);
                }).then(result => {
                    _hideOutlookImportUI();
                    const statusEl = document.getElementById('outlookImportStatus');
                    if (statusEl) statusEl.innerHTML = `<span style="color:#10b981;">✓ ${escapeHtml(result.message || '')}</span>`;
                    loadActivities();
                    _showOutlookImportResult(result);
                    if ((result.status_suggestions || []).length || (result.kanban_suggestions || []).length) {
                        _openSuggestionsModal(result);
                    }
                }).catch(err => {
                    _hideOutlookImportUI();
                    const statusEl = document.getElementById('outlookImportStatus');
                    if (statusEl) statusEl.innerHTML = `<span style="color:#ef4444;">Erro: ${escapeHtml(err.message)}</span>`;
                });
            } catch (e) {
                _hideOutlookImportUI();
                const statusEl = document.getElementById('outlookImportStatus');
                if (statusEl) statusEl.innerHTML = `<span style="color:#ef4444;">Erro: ${escapeHtml(e.message)}</span>`;
            }
        }

        // ── Outlook Add-in (task pane) ─────────────────────────────────────

        let _addinPollTimer = null;

        function _addinSetCaptureVisible(visible) {
            const btn = document.getElementById('outlookAddinCaptureBtn');
            if (btn) btn.style.display = visible ? '' : 'none';
        }

        async function _addinCheckPending(silent = true) {
            try {
                const res = await fetch('/api/outlook/addon-pending');
                const data = await res.json();
                _addinSetCaptureVisible(data.has_data);
                return data;
            } catch (_) {
                return { has_data: false };
            }
        }

        async function captureOutlookAddin() {
            const data = await _addinCheckPending(false);
            if (!data.has_data) {
                _addinSetCaptureVisible(false);
                const statusEl = document.getElementById('outlookImportStatus');
                if (statusEl) statusEl.innerHTML = '<span style="color:#9ca3af;">Nenhum dado pendente do add-in. Exporte emails pelo Outlook primeiro.</span>';
                return;
            }
            // Clear the pending flag on server so next check returns nothing
            fetch('/api/outlook/addon-pending', { method: 'DELETE' }).catch(() => {});
            _addinSetCaptureVisible(false);
            _openOutlookReviewModal(data);
        }

        // Poll for pending add-in data every 20s while the activities tab is active
        function _addinStartPolling() {
            _addinStopPolling();
            _addinCheckPending();
            _addinPollTimer = setInterval(() => _addinCheckPending(), 20000);
        }

        function _addinStopPolling() {
            if (_addinPollTimer) { clearInterval(_addinPollTimer); _addinPollTimer = null; }
        }

        function setupSettingsCards() {
            const grid = document.querySelector('#configuracoes .settings-grid');
            if (!grid) return;

            grid.querySelectorAll('.settings-card').forEach((card) => {
                if (card.dataset.collapsibleReady === '1') return;
                const title = card.querySelector('h3');
                if (!title) return;

                card.classList.add('settings-collapsible');
                title.classList.add('settings-card-title');

                const body = document.createElement('div');
                body.className = 'settings-card-body';
                while (title.nextSibling) {
                    body.appendChild(title.nextSibling);
                }
                card.appendChild(body);

                // Todas as seções iniciam fechadas
                card.classList.add('settings-collapsed');
                title.addEventListener('click', () => {
                    const shouldOpen = card.classList.contains('settings-collapsed');
                    grid.querySelectorAll('.settings-collapsible').forEach(otherCard => {
                        otherCard.classList.add('settings-collapsed');
                    });
                    if (shouldOpen) {
                        card.classList.remove('settings-collapsed');
                    }
                });

                card.dataset.collapsibleReady = '1';
            });
        }

        const AUTOTOCA_EXTENSION_PING_EVENT = 'autotoca-extension-pong';
        const AUTOTOCA_EXTENSION_REQUEST_EVENT = 'autotoca-extension-ping';
        const AUTOTOCA_EXTENSION_COMMAND_EVENT = 'autotoca-extension-command';
        const AUTOTOCA_EXTENSION_RESULT_EVENT = 'autotoca-extension-result';
        let autoTocaExtensionInstalled = false;
        let autoTocaExtensionLastSeenAt = null;

        function _autoTocaGetExtensionNoticeEl() {
            return document.getElementById('autotocaExtensionNotice');
        }

        function _autoTocaGetExtensionStatusEl() {
            return document.getElementById('autotocaExtensionStatus');
        }

        function _autoTocaGetChamadoFormEl() {
            return document.getElementById('autotocaChamadoForm');
        }

        function _autoTocaSetAutomationEnabled(enabled) {
            const form = _autoTocaGetChamadoFormEl();
            const button = document.getElementById('autotocaSubmitBtn');
            if (!form) return;
            const fields = form.querySelectorAll('input, select, textarea, button');
            fields.forEach(field => {
                if (field.id === 'autotocaSubmitBtn') return;
                if (field.type === 'hidden') return;
                field.disabled = !enabled;
            });
            if (button) {
                button.disabled = !enabled;
                button.title = enabled ? '' : 'Instale e ative a extensão do AutoToca para usar esta automação.';
            }
        }

        function renderAutoTocaExtensionState() {
            const notice = _autoTocaGetExtensionNoticeEl();
            const status = _autoTocaGetExtensionStatusEl();
            const text = document.getElementById('autotocaExtensionNoticeText');
            if (notice) notice.style.display = 'none';
            if (status) status.style.display = 'none';
            if (text) {
                text.textContent = 'O fluxo do Formulário Jurídico agora usa somente a automação interna iniciada pelo botão Executar Automação.';
            }
            _autoTocaSetAutomationEnabled(true);
        }

        function handleAutoTocaExtensionPong(event) {
            const detail = event?.detail || {};
            autoTocaExtensionInstalled = true;
            autoTocaExtensionLastSeenAt = new Date().toLocaleTimeString('pt-BR');
            window.__AUTOTOCA_EXTENSION_INFO__ = detail;
            renderAutoTocaExtensionState();
        }

        function handleAutoTocaExtensionResult(event) {
            const detail = event?.detail || {};
            window.__AUTOTOCA_EXTENSION_LAST_RESULT__ = detail;
            if (detail.command === 'store_payload' && detail.ok) {
                _autoTocaAppendLog('Extensão confirmou o recebimento do payload do Chamado Jurídico.', 'success');
                return;
            }
            if (detail.command === 'fill_current_forms' || detail.command === 'ping_forms_autofill') {
                const appliedCount = Array.isArray(detail.results) ? detail.results.filter(item => item.applied).length : 0;
                if (detail.ok) {
                    _autoTocaAppendLog(`Extensão preencheu ${appliedCount} campo(s) no Microsoft Forms.`, 'success');
                    showSuccess(`Forms preenchido automaticamente pela extensão (${appliedCount} campo(s)). Revise e envie.`);
                } else if (detail.reason === 'missing_payload') {
                    _autoTocaAppendLog('A extensão abriu o Forms, mas não encontrou payload salvo para preencher.', 'warning');
                } else if (detail.reason === 'not_forms_page' || detail.reason === 'unavailable') {
                    _autoTocaAppendLog('A extensão está ativa, aguardando a aba do Microsoft Forms carregar completamente.', 'info');
                } else {
                    _autoTocaAppendLog(detail.message || 'A extensão não conseguiu preencher automaticamente os campos nesta tentativa.', 'warning');
                }
            }
        }

        async function checkAutoTocaExtension(showFeedback = false) {
            autoTocaExtensionInstalled = false;
            renderAutoTocaExtensionState();
            window.dispatchEvent(new CustomEvent(AUTOTOCA_EXTENSION_REQUEST_EVENT, {
                detail: {
                    source: 'autotoca-web',
                    timestamp: Date.now(),
                }
            }));
            await new Promise(resolve => setTimeout(resolve, 900));
            if (!autoTocaExtensionInstalled && showFeedback) {
                await openSystemDialog({
                    title: 'Extensão não detectada',
                    message: 'A extensão do AutoToca ainda não foi detectada. Se acabou de instalar, recarregue esta página (F5) e tente novamente. Se ainda não instalou, clique em “Como instalar”.',
                    showCancel: false,
                });
            }
            renderAutoTocaExtensionState();
            return autoTocaExtensionInstalled;
        }

        async function showAutoTocaExtensionInstallGuide() {
            await openSystemDialog({
                title: 'Como instalar a extensão do AutoToca',
                message: [
                    '1. Clique em “Baixar Extensão”.',
                    '2. Extraia o arquivo ZIP em uma pasta do seu computador.',
                    '3. Abra chrome://extensions no Google Chrome.',
                    '4. Ative o “Modo do desenvolvedor” (canto superior direito).',
                    '5. Clique em “Carregar sem compactação”.',
                    '6. Selecione a pasta extraída da extensão.',
                    '⚠️ 7. IMPORTANTE: Recarregue esta página (F5) após instalar.',
                    '8. Clique em “Verificar novamente”.',
                ].join('\n'),
                showCancel: false,
            });
        }

        async function loadAutoToca() {
            loadOutlookGraphStatus();
            const response = await fetch(`${API_BASE}/autotoca/accounts`);
            const select = document.getElementById('autotocaConta');
            if (response.ok && select) {
                const list = await response.json();
                const options = list.map(a => `<option value="${escapeHtml(a.name)}">${escapeHtml(a.name)}</option>`);
                options.push('<option value="OUTRO">OUTROS</option>');
                select.innerHTML = options.join('');
                select.onchange = () => {
                    document.getElementById('autotocaContaOutroWrap').style.display = select.value === 'OUTRO' ? 'block' : 'none';
                    const rs = document.getElementById('autotocaRazaoSocial');
                    const cnpj = document.getElementById('autotocaCnpj');
                    if (rs) rs.value = '';
                    if (cnpj) cnpj.value = '';
                };
            }
            const extensionNotice = document.getElementById('autotocaExtensionNotice');
            const extensionStatus = document.getElementById('autotocaExtensionStatus');
            if (extensionNotice) extensionNotice.style.display = 'none';
            if (extensionStatus) extensionStatus.style.display = 'none';
            await loadAutoTocaSupportFiles();
            await loadAutoTocaMailingData();
            _cjRenderFileFields();
            await loadChamadoJuridicoHistory();
        }

        // Todos os botões de módulo do AutoToca (inclui o WhatsApp Update, que abre modal em vez de painel inline)
        const AUTOTOCA_MODULE_BUTTON_IDS = [
            'autoTocaBtn_chamado-juridico',
            'autoTocaBtn_mala-direta',
            'autoTocaBtn_whatsapp-update',
            'autoTocaBtn_sync-outlook'
        ];

        function resetAutoTocaModuleButtons() {
            AUTOTOCA_MODULE_BUTTON_IDS.forEach(id => {
                const btn = document.getElementById(id);
                if (btn) {
                    btn.classList.remove('btn-auto-mapping');
                    btn.classList.add('btn-secondary');
                }
            });
        }

        function setActiveAutoTocaModuleButton(id) {
            resetAutoTocaModuleButtons();
            const btn = document.getElementById(id);
            if (btn) {
                btn.classList.remove('btn-secondary');
                btn.classList.add('btn-auto-mapping');
            }
        }

        function toggleAutoTocaAutomation(key) {
            const panels = {
                'chamado-juridico': 'autoTocaChamadoJuridico',
                'mala-direta': 'autoTocaMalaDireta',
                'sync-outlook': 'autoTocaSyncOutlook',
                'reembolsos': 'autoTocaReembolsos'
            };
            const buttons = {
                'chamado-juridico': 'autoTocaBtn_chamado-juridico',
                'mala-direta': 'autoTocaBtn_mala-direta',
                'sync-outlook': 'autoTocaBtn_sync-outlook',
                'reembolsos': 'autoTocaBtn_reembolsos'
            };
            const targetId = panels[key];
            if (!targetId) return;
            const target = document.getElementById(targetId);
            if (!target) return;
            const chamadoWasVisible = document.getElementById('autoTocaChamadoJuridico')?.style.display === 'block';
            // Fecha também os painéis de Reports
            ['reportsPanel_preparar-reuniao', 'reportsPanel_relationship-report'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.style.display = 'none';
            });
            ['reportsBtn_preparar-reuniao', 'reportsBtn_relationship-report'].forEach(id => {
                const b = document.getElementById(id);
                if (b) { b.classList.remove('btn-auto-mapping'); b.classList.add('btn-secondary'); }
            });
            const isOpening = target.style.display === 'none';
            // Fecha todos os painéis
            Object.entries(panels).forEach(([, id]) => {
                const el = document.getElementById(id);
                if (el) el.style.display = 'none';
            });
            // Sair do Chamado Jurídico (fechar ou trocar de módulo) limpa o formulário
            if (chamadoWasVisible && !(isOpening && key === 'chamado-juridico') && typeof _cjResetForm === 'function') {
                _cjResetForm();
            }
            resetAutoTocaModuleButtons();
            // Abre o selecionado (toggle)
            if (isOpening) {
                target.style.display = 'block';
                setActiveAutoTocaModuleButton(buttons[key]);
                if (key === 'reembolsos') { loadReembContas(); loadReembOrigemHistorico(); }
            }
        }

        function toggleReportsPanel(key) {
            const panels = {
                'preparar-reuniao': 'reportsPanel_preparar-reuniao',
                'relationship-report': 'reportsPanel_relationship-report'
            };
            const buttons = {
                'preparar-reuniao': 'reportsBtn_preparar-reuniao',
                'relationship-report': 'reportsBtn_relationship-report'
            };
            const targetId = panels[key];
            if (!targetId) return;
            const target = document.getElementById(targetId);
            if (!target) return;
            // Fecha também os painéis de automação do AutoToca
            const chamadoWasVisible = document.getElementById('autoTocaChamadoJuridico')?.style.display === 'block';
            ['autoTocaChamadoJuridico', 'autoTocaMalaDireta', 'autoTocaSyncOutlook'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.style.display = 'none';
            });
            if (chamadoWasVisible && typeof _cjResetForm === 'function') _cjResetForm();
            resetAutoTocaModuleButtons();
            const isOpening = target.style.display === 'none';
            // Fecha todos os painéis
            Object.entries(panels).forEach(([panelKey, id]) => {
                const el = document.getElementById(id);
                if (el) el.style.display = 'none';
                const btn = document.getElementById(buttons[panelKey]);
                if (btn) {
                    btn.classList.remove('btn-auto-mapping');
                    btn.classList.add('btn-secondary');
                }
            });
            // Abre o selecionado (toggle)
            if (isOpening) {
                target.style.display = 'block';
                const activeBtn = document.getElementById(buttons[key]);
                if (activeBtn) {
                    activeBtn.classList.remove('btn-secondary');
                    activeBtn.classList.add('btn-auto-mapping');
                }
            }
        }

        async function loadAutoTocaMailingData() {
            try {
                const [clientsResp, positionsResp, areasResp] = await Promise.all([
                    fetch(`${API_BASE}/clients`),
                    fetch(`${API_BASE}/autotoca/mala-direta/positions`),
                    fetch(`${API_BASE}/autotoca/mala-direta/areas`)
                ]);

                autoTocaMailingClients = clientsResp.ok ? await clientsResp.json() : [];
                autoTocaMailingPositions = positionsResp.ok ? await positionsResp.json() : [];
                autoTocaMailingAreas = areasResp.ok ? await areasResp.json() : [];
                onAutoTocaMailingModeChange();
            } catch (error) {
                autoTocaMailingClients = [];
                autoTocaMailingPositions = [];
                autoTocaMailingAreas = [];
            }
        }

        function onAutoTocaMailingModeChange() {
            const modeEl = document.getElementById('atMailingMode');
            const wrap = document.getElementById('atMailingFilterWrap');
            if (!modeEl || !wrap) return;

            const mode = modeEl.value;
            if (mode === 'manual') {
                wrap.innerHTML = `
                    <label id="atMailingFilterLabel">Buscar contato</label>
                    <input id="atMailingManualSearch" type="text" placeholder="Digite nomes separados por vírgula">
                `;
                return;
            }

            if (mode === 'status') {
                wrap.innerHTML = `
                    <div style="display:flex; flex-wrap:wrap; gap:10px; align-items:flex-end; width:100%;">
                        <div class="form-group" style="margin:0; min-width:180px;">
                            <label>Status</label>
                            <select id="atMailingFilterValue" onchange="onAutoTocaMailingStatusSubModeChange()">
                                <option value="red">Atrasado</option>
                                <option value="yellow">Atenção</option>
                                <option value="green">Em dia</option>
                            </select>
                        </div>
                        <div class="form-group" style="margin:0; min-width:200px;">
                            <label>Subfiltro (opcional)</label>
                            <select id="atMailingStatusSubMode" onchange="onAutoTocaMailingStatusSubModeChange()">
                                <option value="">Nenhum</option>
                                <option value="position">Cargo</option>
                                <option value="area">Área de Atuação</option>
                                <option value="company">Conta</option>
                            </select>
                        </div>
                        <div class="form-group" style="margin:0; min-width:220px; flex:1; display:none;" id="atMailingStatusSubValueWrap">
                            <label id="atMailingStatusSubValueLabel">Cargo</label>
                            <select id="atMailingStatusSubValue"></select>
                        </div>
                    </div>
                `;
                return;
            }

            wrap.innerHTML = `
                <label id="atMailingFilterLabel"></label>
                <select id="atMailingFilterValue"></select>
            `;
            const label = document.getElementById('atMailingFilterLabel');
            const filterEl = document.getElementById('atMailingFilterValue');

            const options = mode === 'position'
                ? autoTocaMailingPositions
                : mode === 'area'
                    ? autoTocaMailingAreas
                    : Array.from(new Set((autoTocaMailingClients || []).map(c => (c.company || '').trim()).filter(Boolean))).sort((a, b) => a.localeCompare(b, 'pt-BR'));
            const modeLabel = mode === 'position' ? 'Cargo' : mode === 'area' ? 'Área de Atuação' : 'Conta';
            label.textContent = modeLabel;
            filterEl.innerHTML = options.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('');
        }

        function onAutoTocaMailingStatusSubModeChange() {
            const subModeEl = document.getElementById('atMailingStatusSubMode');
            const wrap = document.getElementById('atMailingStatusSubValueWrap');
            const label = document.getElementById('atMailingStatusSubValueLabel');
            const valueEl = document.getElementById('atMailingStatusSubValue');
            if (!subModeEl || !wrap || !label || !valueEl) return;

            const subMode = subModeEl.value;
            if (!subMode) {
                wrap.style.display = 'none';
                valueEl.innerHTML = '';
                return;
            }

            const status = (document.getElementById('atMailingFilterValue')?.value || 'red').trim();
            const pool = (autoTocaMailingClients || []).filter(c =>
                getStatus(c.last_activity_date, c.position, c.is_target, c.is_cold_contact) === status
            );

            let options;
            if (subMode === 'position') {
                label.textContent = 'Cargo';
                options = Array.from(new Set(pool.map(c => (c.position || '').trim()).filter(Boolean))).sort((a, b) => a.localeCompare(b, 'pt-BR'));
            } else if (subMode === 'area') {
                label.textContent = 'Área de Atuação';
                options = Array.from(new Set(pool.map(c => (c.area_of_activity || '').trim()).filter(Boolean))).sort((a, b) => a.localeCompare(b, 'pt-BR'));
            } else {
                label.textContent = 'Conta';
                options = Array.from(new Set(pool.map(c => (c.company || '').trim()).filter(Boolean))).sort((a, b) => a.localeCompare(b, 'pt-BR'));
            }

            wrap.style.display = '';
            valueEl.innerHTML = options.length
                ? options.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('')
                : '<option value="">Nenhum contato neste status</option>';
        }

        function _getAutoTocaFilteredMailingClients() {
            const mode = document.getElementById('atMailingMode')?.value || 'position';
            if (mode === 'manual') {
                const q = (document.getElementById('atMailingManualSearch')?.value || '').trim().toLowerCase();
                const terms = q.split(',').map(s => s.trim()).filter(Boolean);
                if (!terms.length) return [];
                return autoTocaMailingClients.filter(c => terms.some(term => String(c.name || '').toLowerCase().includes(term)));
            }

            if (mode === 'status') {
                const status = (document.getElementById('atMailingFilterValue')?.value || '').trim();
                if (!status) return [];
                let pool = (autoTocaMailingClients || []).filter(c =>
                    getStatus(c.last_activity_date, c.position, c.is_target, c.is_cold_contact) === status
                );
                const subMode = (document.getElementById('atMailingStatusSubMode')?.value || '').trim();
                const subValue = (document.getElementById('atMailingStatusSubValue')?.value || '').trim();
                if (subMode && subValue) {
                    if (subMode === 'position') pool = pool.filter(c => (c.position || '') === subValue);
                    else if (subMode === 'area') pool = pool.filter(c => (c.area_of_activity || '') === subValue);
                    else if (subMode === 'company') pool = pool.filter(c => (c.company || '') === subValue);
                }
                return pool;
            }

            const selected = (document.getElementById('atMailingFilterValue')?.value || '').trim();
            if (!selected) return [];
            if (mode === 'position') return autoTocaMailingClients.filter(c => (c.position || '') === selected);
            if (mode === 'area') return autoTocaMailingClients.filter(c => (c.area_of_activity || '') === selected);
            return autoTocaMailingClients.filter(c => (c.company || '') === selected);
        }

        function getAutoTocaMailingStatus(lastActivityDate, position, isTarget = 0, isColdContact = 0) {
            const statusName = getStatus(lastActivityDate, position, isTarget, isColdContact);
            const statusColor = statusName === 'green' ? '#10b981' : statusName === 'yellow' ? '#f59e0b' : '#ef4444';
            const statusText = statusName === 'green' ? 'Em dia' : statusName === 'yellow' ? 'Atenção' : 'Atrasado';

            if (!lastActivityDate) {
                return { color: statusColor, label: `${statusText} — sem histórico de interação` };
            }

            const lastDate = new Date(lastActivityDate);
            if (Number.isNaN(lastDate.getTime())) {
                return { color: statusColor, label: `${statusText} — data de última interação inválida` };
            }

            const msPerDay = 1000 * 60 * 60 * 24;
            const daysSince = Math.max(0, Math.floor((Date.now() - lastDate.getTime()) / msPerDay));
            const formattedDate = lastDate.toLocaleDateString('pt-BR');
            return { color: statusColor, label: `${statusText} — último contato há ${daysSince} dia(s) (${formattedDate})` };
        }

        function openAutoTocaMailingPreview() {
            const filtered = _getAutoTocaFilteredMailingClients();
            if (!filtered.length) return showInfo('Nenhum contato encontrado para esse filtro.');
            _autoTocaMailingPreviewFiltered = filtered;

            // Reseta canal para e-mail ao abrir o preview
            _autoTocaMailingChannel = 'email';

            // Seleção inicial: apenas contatos visíveis (não arquivados e não frios) com e-mail
            autoTocaMailingSelection = filtered
                .filter(c => !isArchivedClient(c) && !Number(c.is_cold_contact))
                .filter(c => String(c.email || '').trim())
                .map(c => c.id);

            const hasArchived = filtered.some(c => isArchivedClient(c));
            const hasCold = filtered.some(c => Number(c.is_cold_contact) === 1);

            let html = `<div class="modal active" id="autoTocaMailingPreviewModal" onclick="if(event.target===this) closeAutoTocaMailingPreview()">`;
            html += `<div class="modal-content" style="max-width:920px;">`;
            html += `<h2 style="color:#047857;">Mala Direta — Seleção de Contatos</h2>`;

            // Toggle de canal — fica AQUI, no preview, onde o usuário vê quem tem o dado de contato
            html += `<div style="display:flex; align-items:center; gap:10px; margin-bottom:10px; padding:9px 14px; background:rgba(243,244,246,.6); border:1px solid #e5e7eb; border-radius:10px; flex-wrap:wrap;">
                <span style="font-size:13px; font-weight:600; color:#374151;">Canal de envio:</span>
                <button id="atPreviewChEmail" class="btn btn-primary btn-small" onclick="_switchAutoTocaMailingChannelInPreview('email')"><i class="fas fa-envelope"></i> E-mail</button>
                <button id="atPreviewChWpp" class="btn btn-secondary btn-small" onclick="_switchAutoTocaMailingChannelInPreview('whatsapp')"><i class="fab fa-whatsapp"></i> WhatsApp</button>
                <span id="atPreviewChannelNote" style="font-size:12px; color:#6b7280; margin-left:4px;">Apenas contatos com e-mail poderão ser selecionados.</span>
            </div>`;

            // Barra de filtros internos do modal
            html += `<div style="display:flex; align-items:center; gap:16px; padding:9px 14px; background:rgba(243,244,246,.85); border:1px solid #e5e7eb; border-radius:10px; margin-bottom:14px; flex-wrap:wrap;">
                <span style="font-size:12px; font-weight:700; color:#374151; text-transform:uppercase; letter-spacing:.04em;">Exibir também:</span>
                <label style="display:flex; align-items:center; gap:7px; cursor:pointer; font-size:13px; color:#4b5563; ${!hasArchived ? 'opacity:.4; pointer-events:none;' : ''}">
                    <input type="checkbox" id="atMailingShowArchived" onchange="_renderAutoTocaMailingPreviewContacts()" style="cursor:pointer; accent-color:#6b7280;" ${!hasArchived ? 'disabled' : ''}>
                    <i class="fas fa-box-archive" style="color:#6b7280; font-size:12px;"></i>
                    Arquivados${hasArchived ? '' : ' <em style="font-size:11px;">(nenhum neste filtro)</em>'}
                </label>
                <label style="display:flex; align-items:center; gap:7px; cursor:pointer; font-size:13px; color:#4b5563; ${!hasCold ? 'opacity:.4; pointer-events:none;' : ''}">
                    <input type="checkbox" id="atMailingShowCold" onchange="_renderAutoTocaMailingPreviewContacts()" style="cursor:pointer; accent-color:#0e7490;" ${!hasCold ? 'disabled' : ''}>
                    <i class="fas fa-snowflake" style="color:#0e7490; font-size:12px;"></i>
                    Frios${hasCold ? '' : ' <em style="font-size:11px;">(nenhum neste filtro)</em>'}
                </label>
                <label style="display:flex; align-items:center; gap:7px; cursor:pointer; font-size:13px; color:#4b5563; margin-left:auto;">
                    <input type="checkbox" id="atMailingHideNoContact" onchange="_renderAutoTocaMailingPreviewContacts()" style="cursor:pointer; accent-color:#dc2626;" checked>
                    <i class="fas fa-eye-slash" style="color:#dc2626; font-size:12px;"></i>
                    <span id="atMailingHideNoContactLabel">Ocultar sem e-mail</span>
                </label>
            </div>`;

            html += `<div id="atMailingPreviewGrid" style="max-height:420px; overflow:auto; display:grid; grid-template-columns:repeat(auto-fill, minmax(250px,1fr)); gap:10px;">`;
            html += _buildAutoTocaMailingPreviewContactsHTML();
            html += `</div>`;
            html += `<div style="display:flex; justify-content:flex-end; gap:10px; margin-top:14px;"><button class="btn btn-secondary" onclick="closeAutoTocaMailingPreview()">Cancelar</button><button class="btn btn-primary" onclick="openAutoTocaMailingComposer()">Próximo →</button></div>`;
            html += `</div></div>`;
            document.body.insertAdjacentHTML('beforeend', html);
        }

        function _buildAutoTocaMailingPreviewContactsHTML() {
            const showArchived = document.getElementById('atMailingShowArchived')?.checked || false;
            const showCold = document.getElementById('atMailingShowCold')?.checked || false;
            const hideNoContact = document.getElementById('atMailingHideNoContact')?.checked ?? true;
            const isWpp = _autoTocaMailingChannel === 'whatsapp';

            const visible = _autoTocaMailingPreviewFiltered.filter(c => {
                if (isArchivedClient(c) && !showArchived) return false;
                if (Number(c.is_cold_contact) === 1 && !showCold) return false;
                if (hideNoContact) {
                    const hasContact = isWpp
                        ? !!normalizePhoneForWhatsapp(c.phone)
                        : !!String(c.email || '').trim();
                    if (!hasContact) return false;
                }
                return true;
            });

            if (!visible.length) {
                return `<div style="grid-column:1/-1; text-align:center; color:#6b7280; padding:30px 0; font-size:14px;">
                    <i class="fas fa-filter" style="margin-bottom:8px; font-size:22px; opacity:.4; display:block;"></i>
                    Nenhum contato a exibir com os filtros selecionados.
                </div>`;
            }

            return visible.map(c => {
                const noContact = isWpp
                    ? !normalizePhoneForWhatsapp(c.phone)
                    : !String(c.email || '').trim();
                const missingLabel = isWpp ? 'Sem telefone' : 'Sem e-mail';
                const status = getAutoTocaMailingStatus(c.last_activity_date, c.position, c.is_target, c.is_cold_contact);
                const isCold = Number(c.is_cold_contact) === 1;
                const isArchived = isArchivedClient(c);
                const badges = [];
                if (isCold) badges.push('<span title="Contato marcado como frio" style="display:inline-flex; align-items:center; gap:4px; font-size:11px; padding:2px 8px; border-radius:999px; background:rgba(8,145,178,.12); color:#0e7490; border:1px solid rgba(8,145,178,.3); font-weight:600;"><i class="fas fa-snowflake"></i> Frio</span>');
                if (isArchived) badges.push('<span title="Contato arquivado" style="display:inline-flex; align-items:center; gap:4px; font-size:11px; padding:2px 8px; border-radius:999px; background:rgba(107,114,128,.15); color:#374151; border:1px solid rgba(107,114,128,.3); font-weight:600;"><i class="fas fa-box-archive"></i> Arquivado</span>');
                const badgesHtml = badges.length ? `<div style="display:flex; flex-wrap:wrap; gap:4px; margin-top:6px;">${badges.join('')}</div>` : '';
                const isSelected = autoTocaMailingSelection.includes(c.id);
                return `<label style="display:flex; gap:10px; align-items:flex-start; padding:10px; border:1px solid ${noContact ? 'rgba(156,163,175,.45)' : 'rgba(16,185,129,.25)'}; border-radius:10px; background:${noContact ? 'rgba(243,244,246,.7)' : 'rgba(236,253,245,.5)'}; ${noContact ? 'opacity:.6; cursor:not-allowed;' : 'cursor:pointer;'}">
                    <input type="checkbox" ${noContact ? 'disabled' : (isSelected ? 'checked' : '')} onchange="toggleAutoTocaMailingContact(${Number(c.id)}, this.checked)" style="margin-top:4px;">
                    <img src="${c.photo_url || '/logo-coelho.png'}" style="width:40px;height:40px;border-radius:999px;object-fit:cover;">
                    <div style="min-width:0;">
                        <div style="font-weight:700; color:#065f46; display:flex; align-items:center; gap:6px;">
                            <span title="${escapeHtml(status.label)}" aria-label="${escapeHtml(status.label)}" style="display:inline-block; width:9px; height:9px; min-width:9px; border-radius:999px; background:${status.color};"></span>
                            <span style="min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(c.name || '-')}</span>
                        </div>
                        <div style="font-size:12px;color:#6b7280;">${escapeHtml(c.company || '-')}</div>
                        <div style="font-size:12px;color:#9ca3af;">${escapeHtml(c.position || '-')}</div>
                        <div style="font-size:12px;color:#9ca3af;">${escapeHtml(c.area_of_activity || '-')}</div>
                        ${badgesHtml}
                        ${noContact ? `<div style="font-size:12px;color:#b45309; margin-top:4px;"><i class="fas fa-triangle-exclamation"></i> ${missingLabel}</div>` : ''}
                    </div>
                </label>`;
            }).join('');
        }

        function _renderAutoTocaMailingPreviewContacts() {
            const showArchived = document.getElementById('atMailingShowArchived')?.checked || false;
            const showCold = document.getElementById('atMailingShowCold')?.checked || false;

            // Calcula quais ficam visíveis após a mudança
            const visible = _autoTocaMailingPreviewFiltered.filter(c => {
                if (isArchivedClient(c) && !showArchived) return false;
                if (Number(c.is_cold_contact) === 1 && !showCold) return false;
                return true;
            });
            const visibleIds = new Set(visible.map(c => c.id));

            // Remove da seleção os que ficaram ocultos
            autoTocaMailingSelection = autoTocaMailingSelection.filter(id => visibleIds.has(id));

            // Adiciona automaticamente os recém-exibidos que têm a info de contato do canal
            const isWppRender = _autoTocaMailingChannel === 'whatsapp';
            visible.forEach(c => {
                const hasContact = isWppRender
                    ? !!normalizePhoneForWhatsapp(c.phone)
                    : !!String(c.email || '').trim();
                if (hasContact && !autoTocaMailingSelection.includes(c.id)) {
                    autoTocaMailingSelection.push(c.id);
                }
            });

            const grid = document.getElementById('atMailingPreviewGrid');
            if (grid) grid.innerHTML = _buildAutoTocaMailingPreviewContactsHTML();
        }

        function toggleAutoTocaMailingContact(contactId, checked) {
            const contact = autoTocaMailingClients.find(c => Number(c.id) === Number(contactId));
            const isWpp = _autoTocaMailingChannel === 'whatsapp';
            const hasContact = isWpp
                ? !!normalizePhoneForWhatsapp(contact?.phone)
                : !!String(contact?.email || '').trim();
            if (checked) {
                if (!hasContact) return;
                if (!autoTocaMailingSelection.includes(contactId)) autoTocaMailingSelection.push(contactId);
                return;
            }
            autoTocaMailingSelection = autoTocaMailingSelection.filter(id => Number(id) !== Number(contactId));
        }

        function closeAutoTocaMailingPreview() {
            document.getElementById('autoTocaMailingPreviewModal')?.remove();
        }

        function _switchAutoTocaMailingChannelInPreview(ch) {
            _autoTocaMailingChannel = ch;

            // Botões de toggle no preview
            const emailBtn = document.getElementById('atPreviewChEmail');
            const wppBtn   = document.getElementById('atPreviewChWpp');
            if (emailBtn) emailBtn.className = `btn btn-small ${ch === 'email' ? 'btn-primary' : 'btn-secondary'}`;
            if (wppBtn)   wppBtn.className   = `btn btn-small ${ch === 'whatsapp' ? 'btn-primary' : 'btn-secondary'}`;

            // Nota de canal e label do ocultar
            const note = document.getElementById('atPreviewChannelNote');
            if (note) note.textContent = ch === 'email'
                ? 'Apenas contatos com e-mail poderão ser selecionados.'
                : 'Apenas contatos com telefone poderão ser selecionados.';
            const hideLabel = document.getElementById('atMailingHideNoContactLabel');
            if (hideLabel) hideLabel.textContent = ch === 'email' ? 'Ocultar sem e-mail' : 'Ocultar sem telefone';

            // Redefine a seleção para o novo canal (apenas visíveis com a info necessária)
            const showArchived = document.getElementById('atMailingShowArchived')?.checked || false;
            const showCold = document.getElementById('atMailingShowCold')?.checked || false;
            const visible = _autoTocaMailingPreviewFiltered.filter(c => {
                if (isArchivedClient(c) && !showArchived) return false;
                if (Number(c.is_cold_contact) === 1 && !showCold) return false;
                return true;
            });

            autoTocaMailingSelection = visible.filter(c => {
                return ch === 'whatsapp'
                    ? !!normalizePhoneForWhatsapp(c.phone)
                    : !!String(c.email || '').trim();
            }).map(c => c.id);

            const grid = document.getElementById('atMailingPreviewGrid');
            if (grid) grid.innerHTML = _buildAutoTocaMailingPreviewContactsHTML();
        }

        function openAutoTocaMailingComposer() {
            const selectedContacts = autoTocaMailingClients.filter(c => autoTocaMailingSelection.includes(c.id));
            if (!selectedContacts.length) return showInfo('Selecione ao menos um contato.');
            closeAutoTocaMailingPreview();
            // Canal já definido no preview — não resetar aqui

            const isWppComposer = _autoTocaMailingChannel === 'whatsapp';
            const initialChips = selectedContacts.map(c => {
                const missing = isWppComposer
                    ? !normalizePhoneForWhatsapp(c.phone)
                    : !String(c.email || '').trim();
                const icon = missing
                    ? `<i class="fas fa-triangle-exclamation" title="${isWppComposer ? 'Sem telefone' : 'Sem e-mail'}"></i>`
                    : '';
                const wppIcon = isWppComposer ? `<i class="fab fa-whatsapp" style="color:${missing ? '#b45309' : '#059669'}; font-size:11px;"></i> ` : '';
                return `<span id="chip-destinatario-${c.id}" style="display:inline-flex; gap:5px; align-items:center; padding:4px 10px; border-radius:999px; border:1px solid ${missing ? 'rgba(245,158,11,.4)' : 'rgba(16,185,129,.35)'}; background:${missing ? 'rgba(255,251,235,.8)' : 'rgba(236,253,245,.8)'}; font-size:12px;">${wppIcon}${escapeHtml(c.name || '-')} ${icon}<button type="button" onclick="removeAutoTocaMailingRecipient(${Number(c.id)})" title="Remover destinatário" aria-label="Remover destinatário ${escapeHtml(c.name || '-')}" style="border:none; background:transparent; color:#ef4444; cursor:pointer; padding:0; font-size:12px; line-height:1;"><i class="fas fa-times"></i></button></span>`;
            }).join('');

            const initialMergeTags = isWppComposer
                ? ['<nome do contato>', '<sobrenome>', '<conta>', '<cargo>', '<area de atuacao>', '<telefone>']
                : ['<nome do contato>', '<sobrenome>', '<conta>', '<cargo>', '<area de atuacao>', '<email>'];
            const mergeTagsBtns = initialMergeTags.map(tag =>
                `<button type="button" class="btn btn-secondary btn-small" onclick="insertAutoTocaMergeTag('${tag.replace(/'/g, "\\'")}')">${escapeHtml(tag)}</button>`
            ).join('');

            const channelBadge = isWppComposer
                ? `<span class="btn btn-small btn-primary" style="pointer-events:none; background:#25d366; border-color:#25d366;"><i class="fab fa-whatsapp"></i> WhatsApp</span>`
                : `<span class="btn btn-small btn-primary" style="pointer-events:none;"><i class="fas fa-envelope"></i> E-mail</span>`;
            const channelNoteText = isWppComposer
                ? 'Os contatos sem telefone serão ignorados no envio.'
                : 'Os contatos sem e-mail serão ignorados no envio.';

            let html = `<div class="modal active" id="autoTocaMailingComposerModal">`;
            html += `<div class="modal-content" style="max-width:1120px;">`;
            html += `<h2 style="color:#047857; margin-bottom:10px;">Mala Direta — Composição</h2>`;
            // Exibe o canal escolhido (somente leitura — troca no preview)
            html += `<div style="display:flex; align-items:center; gap:10px; margin-bottom:14px; padding:9px 14px; background:rgba(243,244,246,.6); border:1px solid #e5e7eb; border-radius:10px; flex-wrap:wrap;">
                <span style="font-size:13px; font-weight:600; color:#374151;">Canal de envio:</span>
                ${channelBadge}
                <span id="atMailingChannelNote" style="font-size:12px; color:#6b7280; margin-left:4px;">${channelNoteText}</span>
            </div>`;
            html += `<div style="display:grid; grid-template-columns:220px 1fr 250px; gap:14px;">`;
            html += `<div style="border:1px solid rgba(16,185,129,.2); border-radius:10px; padding:10px; background:rgba(236,253,245,.55);">
                <div style="font-weight:700; color:#065f46; margin-bottom:8px;">Chaves de merge</div>
                <p style="font-size:12px; color:#4b5563; line-height:1.45;">Cada chave será substituída pelo dado real do contato no momento do envio.</p>
                <div id="atMailingMergeTagsPanel" style="display:flex; flex-direction:column; gap:6px; margin-top:8px;">${mergeTagsBtns}</div>
            </div>`;
            const initialSubjectDisplay = isWppComposer ? 'none' : '';
            const initialBodyLabel = isWppComposer ? 'Mensagem WhatsApp' : 'Mensagem';
            const initialBodyPlaceholder = isWppComposer
                ? 'Olá <nome do contato>! Tudo bem?\n\nEstamos entrando em contato sobre...'
                : 'Escreva o corpo do e-mail usando as chaves desejadas.';
            const initialSendBtnHtml = isWppComposer
                ? '<i class="fab fa-whatsapp"></i> Disparar via WhatsApp'
                : '<i class="fas fa-paper-plane"></i> Abrir e-mails no Outlook';

            html += `<div>
                <div class="form-group"><label>Destinatários confirmados</label><div id="autoTocaMailingComposerRecipients" style="display:flex; flex-wrap:wrap; gap:6px; border:1px solid #d1d5db; border-radius:8px; padding:8px; min-height:42px; background:#fff;">${initialChips}</div></div>
                <div id="atMailingSubjectGroup" class="form-group" style="display:${initialSubjectDisplay};"><label>Assunto</label><input id="autoTocaMailingSubject" type="text" placeholder="Ex: Olá &lt;nome do contato&gt;, oportunidade para &lt;conta&gt;"></div>
                <div class="form-group"><label id="atMailingBodyLabel">${initialBodyLabel}</label><textarea id="autoTocaMailingBody" rows="10" placeholder="${initialBodyPlaceholder}"></textarea></div>
                <div style="display:flex; justify-content:flex-end; gap:10px;"><button class="btn btn-secondary" onclick="closeAutoTocaMailingComposer()">Cancelar</button><button id="autoTocaMailingSendBtn" class="btn btn-primary" onclick="sendAutoTocaMailingBatch()">${initialSendBtnHtml}</button></div>
            </div>`;
            html += `<div style="border-left:1px solid rgba(16,185,129,.2); padding-left:12px;"><h4 style="color:#047857; margin-bottom:8px;">Conteúdo Padrão</h4><div id="atMailingTemplateDrawer">${renderTemplateDrawer(isWppComposer ? 'whatsapp' : 'email','autoTocaMailingBody')}</div></div>`;
            html += `</div></div></div>`;
            document.body.insertAdjacentHTML('beforeend', html);
            updateAutoTocaMailingComposerSendState();
        }

        function _switchAutoTocaMailingChannel(ch) {
            _autoTocaMailingChannel = ch;

            // Botões de toggle
            const emailBtn = document.getElementById('atMailingChEmail');
            const wppBtn   = document.getElementById('atMailingChWpp');
            if (emailBtn) emailBtn.className = `btn btn-small ${ch === 'email' ? 'btn-primary' : 'btn-secondary'}`;
            if (wppBtn)   wppBtn.className   = `btn btn-small ${ch === 'whatsapp' ? 'btn-primary' : 'btn-secondary'}`;

            // Nota de canal
            const note = document.getElementById('atMailingChannelNote');
            if (note) note.textContent = ch === 'email'
                ? 'Os contatos sem e-mail serão ignorados no envio.'
                : 'Os contatos sem telefone serão ignorados no envio.';

            // Assunto (só e-mail tem assunto)
            const subjectGroup = document.getElementById('atMailingSubjectGroup');
            if (subjectGroup) subjectGroup.style.display = ch === 'email' ? '' : 'none';

            // Label e placeholder do corpo
            const bodyLabel = document.getElementById('atMailingBodyLabel');
            const bodyEl    = document.getElementById('autoTocaMailingBody');
            if (bodyLabel) bodyLabel.textContent = ch === 'email' ? 'Mensagem' : 'Mensagem WhatsApp';
            if (bodyEl) bodyEl.placeholder = ch === 'email'
                ? 'Escreva o corpo do e-mail usando as chaves desejadas.'
                : 'Olá <nome do contato>! Tudo bem?\n\nEstamos entrando em contato sobre...';

            // Painel de chaves de merge
            const mergePanel = document.getElementById('atMailingMergeTagsPanel');
            if (mergePanel) {
                const tags = ch === 'email'
                    ? ['<nome do contato>', '<sobrenome>', '<conta>', '<cargo>', '<area de atuacao>', '<email>']
                    : ['<nome do contato>', '<sobrenome>', '<conta>', '<cargo>', '<area de atuacao>', '<telefone>'];
                mergePanel.innerHTML = tags.map(tag =>
                    `<button type="button" class="btn btn-secondary btn-small" onclick="insertAutoTocaMergeTag('${tag.replace(/'/g, "\\'")}')">${escapeHtml(tag)}</button>`
                ).join('');
            }

            // Chips de destinatários
            const selectedContacts = autoTocaMailingClients.filter(c => autoTocaMailingSelection.includes(c.id));
            const recipientsEl = document.getElementById('autoTocaMailingComposerRecipients');
            if (recipientsEl) {
                const chips = selectedContacts.map(c => {
                    const missing = ch === 'whatsapp'
                        ? !normalizePhoneForWhatsapp(c.phone)
                        : !String(c.email || '').trim();
                    const icon = missing
                        ? (ch === 'whatsapp' ? '<i class="fas fa-triangle-exclamation" title="Sem telefone"></i>' : '<i class="fas fa-triangle-exclamation" title="Sem e-mail"></i>')
                        : '';
                    const wppIcon = ch === 'whatsapp' ? `<i class="fab fa-whatsapp" style="color:${missing ? '#b45309' : '#059669'}; font-size:11px;"></i> ` : '';
                    return `<span id="chip-destinatario-${c.id}" style="display:inline-flex; gap:5px; align-items:center; padding:4px 10px; border-radius:999px; border:1px solid ${missing ? 'rgba(245,158,11,.4)' : 'rgba(16,185,129,.35)'}; background:${missing ? 'rgba(255,251,235,.8)' : 'rgba(236,253,245,.8)'}; font-size:12px;">${wppIcon}${escapeHtml(c.name || '-')} ${icon}<button type="button" onclick="removeAutoTocaMailingRecipient(${Number(c.id)})" title="Remover" style="border:none; background:transparent; color:#ef4444; cursor:pointer; padding:0; font-size:12px; line-height:1; margin-left:2px;"><i class="fas fa-times"></i></button></span>`;
                }).join('') || '<span style="font-size:12px; color:#6b7280;">Nenhum destinatário.</span>';
                recipientsEl.innerHTML = chips;
            }

            // Botão de envio
            const sendBtn = document.getElementById('autoTocaMailingSendBtn');
            if (sendBtn) sendBtn.innerHTML = ch === 'email'
                ? '<i class="fas fa-paper-plane"></i> Abrir e-mails no Outlook'
                : '<i class="fab fa-whatsapp"></i> Disparar via WhatsApp';

            // Gaveta de templates
            const drawerEl = document.getElementById('atMailingTemplateDrawer');
            if (drawerEl) drawerEl.innerHTML = renderTemplateDrawer(ch === 'email' ? 'email' : 'whatsapp', 'autoTocaMailingBody');
        }

        function updateAutoTocaMailingComposerSendState() {
            const sendBtn = document.getElementById('autoTocaMailingSendBtn');
            if (!sendBtn) return;
            sendBtn.disabled = autoTocaMailingSelection.length === 0;
        }

        function removeAutoTocaMailingRecipient(contactId) {
            autoTocaMailingSelection = autoTocaMailingSelection.filter(id => Number(id) !== Number(contactId));
            document.getElementById(`chip-destinatario-${contactId}`)?.remove();
            updateAutoTocaMailingComposerSendState();
            if (autoTocaMailingSelection.length === 0) {
                document.getElementById('autoTocaMailingComposerRecipients').innerHTML = '<span style="font-size:12px; color:#6b7280;">Nenhum destinatário selecionado.</span>';
                showInfo('Todos os destinatários foram removidos. Selecione contatos para enviar a mala direta.');
            }
        }

        function closeAutoTocaMailingComposer() {
            document.getElementById('autoTocaMailingComposerModal')?.remove();
        }

        function insertAutoTocaMergeTag(tag) {
            const subjectEl = document.getElementById('autoTocaMailingSubject');
            const bodyEl = document.getElementById('autoTocaMailingBody');
            const activeEl = document.activeElement;
            const target = (activeEl === subjectEl || activeEl === bodyEl)
                ? activeEl
                : (bodyEl || subjectEl);

            if (!target) return;
            target.focus();

            const start = Number.isFinite(target.selectionStart) ? target.selectionStart : target.value.length;
            const end = Number.isFinite(target.selectionEnd) ? target.selectionEnd : start;
            const before = target.value.slice(0, start);
            const after = target.value.slice(end);
            target.value = `${before}${tag}${after}`;
            const cursorPos = start + tag.length;
            target.setSelectionRange(cursorPos, cursorPos);
            target.dispatchEvent(new Event('input', { bubbles: true }));
        }

        function getAutoTocaContactFirstName(name) {
            return String(name || '').trim().split(/\s+/)[0] || '';
        }

        function getAutoTocaContactLastName(name) {
            const parts = String(name || '').trim().split(/\s+/);
            return parts.length > 1 ? parts[parts.length - 1] : '';
        }

        function applyMergeFields(template, contact) {
            return String(template || '')
                .replaceAll('<nome do contato>', getAutoTocaContactFirstName(contact.name))
                .replaceAll('<sobrenome>', getAutoTocaContactLastName(contact.name))
                .replaceAll('<conta>', contact.company || '')
                .replaceAll('<cargo>', contact.position || '')
                .replaceAll('<area de atuacao>', contact.area_of_activity || '')
                .replaceAll('<email>', contact.email || '')
                .replaceAll('<telefone>', contact.phone || '');
        }

        /** Insere uma chave de merge na posição do cursor de qualquer textarea/input pelo id. */
        function insertMergeTagInto(textareaId, tag) {
            const el = document.getElementById(textareaId);
            if (!el) return;
            el.focus();
            const start = Number.isFinite(el.selectionStart) ? el.selectionStart : el.value.length;
            const end   = Number.isFinite(el.selectionEnd)   ? el.selectionEnd   : start;
            el.value = el.value.slice(0, start) + tag + el.value.slice(end);
            const pos = start + tag.length;
            el.setSelectionRange(pos, pos);
            el.dispatchEvent(new Event('input', { bubbles: true }));
        }

        /** Insere chave de merge no campo ativo do modal de e-mail individual (assunto ou corpo). */
        function insertEmailDraftMergeTag(tag) {
            const subjectEl = document.getElementById('emailDraftSubject');
            const bodyEl    = document.getElementById('emailDraftBody');
            const activeEl  = document.activeElement;
            const target    = (activeEl === subjectEl || activeEl === bodyEl) ? activeEl : (bodyEl || subjectEl);
            if (!target) return;
            insertMergeTagInto(target.id, tag);
        }

        // Estado global do despacho da mala direta (uma lista por vez).
        let autoTocaMailingDispatchDrafts = [];
        let _autoTocaMailingChannel = 'email'; // 'email' | 'whatsapp'

        function sendAutoTocaMailingBatch() {
            if (_autoTocaMailingChannel === 'whatsapp') {
                _sendAutoTocaWhatsAppBatch();
                return;
            }

            const selectedContacts = autoTocaMailingClients.filter(c => autoTocaMailingSelection.includes(c.id));
            const subjectTemplate = document.getElementById('autoTocaMailingSubject')?.value || '';
            const bodyTemplate = document.getElementById('autoTocaMailingBody')?.value || '';
            const contactsWithEmail = selectedContacts.filter(c => String(c.email || '').trim());
            const skipped = selectedContacts.length - contactsWithEmail.length;

            if (!contactsWithEmail.length) return showError('Nenhum contato selecionado possui e-mail.');

            tocaDebug('mala-direta.send', 'Iniciando despacho', {
                selected: selectedContacts.length,
                withEmail: contactsWithEmail.length,
                skipped
            });

            autoTocaMailingDispatchDrafts = contactsWithEmail.map((contact, idx) => {
                const subject = applyMergeFields(subjectTemplate, contact);
                const body = applyMergeFields(bodyTemplate, contact);
                return {
                    idx,
                    contact,
                    subject,
                    body,
                    channel: 'email',
                    url: `https://outlook.office.com/mail/deeplink/compose?to=${encodeURIComponent(contact.email)}&subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`,
                    status: 'pending'
                };
            });

            closeAutoTocaMailingComposer();
            openAutoTocaMailingDispatchModal(skipped);
        }

        function _sendAutoTocaWhatsAppBatch() {
            const selectedContacts = autoTocaMailingClients.filter(c => autoTocaMailingSelection.includes(c.id));
            const bodyTemplate = document.getElementById('autoTocaMailingBody')?.value || '';
            const contactsWithPhone = selectedContacts.filter(c => normalizePhoneForWhatsapp(c.phone));
            const skipped = selectedContacts.length - contactsWithPhone.length;

            if (!contactsWithPhone.length) return showError('Nenhum contato selecionado possui telefone válido para WhatsApp.');

            tocaDebug('mala-direta.send-wpp', 'Iniciando despacho WhatsApp', {
                selected: selectedContacts.length,
                withPhone: contactsWithPhone.length,
                skipped
            });

            autoTocaMailingDispatchDrafts = contactsWithPhone.map((contact, idx) => {
                const body = applyMergeFields(bodyTemplate, contact);
                const phone = normalizePhoneForWhatsapp(contact.phone);
                return {
                    idx,
                    contact,
                    body,
                    phone,
                    channel: 'whatsapp',
                    status: 'pending'
                };
            });

            closeAutoTocaMailingComposer();
            openAutoTocaMailingDispatchModal(skipped);
        }

        function openAutoTocaMailingDispatchModal(skipped = 0) {
            const drafts = autoTocaMailingDispatchDrafts;
            if (!drafts.length) return;

            const isWpp = drafts[0]?.channel === 'whatsapp';

            const rowsHtml = drafts.map((d, i) => {
                const subInfo = isWpp
                    ? `<div style="font-size:12px; color:#6b7280;"><i class="fab fa-whatsapp" style="color:#25d366;"></i> ${escapeHtml(d.phone || '-')}</div>`
                    : `<div style="font-size:12px; color:#6b7280;">${escapeHtml(d.contact.email || '-')}</div>
                       <div style="font-size:12px; color:#4b5563; margin-top:4px;"><strong>Assunto:</strong> ${escapeHtml(d.subject || '(sem assunto)')}</div>`;
                const btnIcon = isWpp ? '<i class="fab fa-whatsapp"></i>' : '<i class="fas fa-paper-plane"></i>';
                const btnLabel = isWpp ? 'Abrir no WhatsApp' : 'Abrir no Outlook';
                const wahaBtn = isWpp
                    ? `<button id="mailingWahaBtn_${i}" class="btn btn-auto-mapping btn-small" onclick="dispatchMailingViaWahaOne(${i})" title="Enviar direto via WAHA, sem abrir janela do navegador"><i class="fas fa-bolt"></i> WAHA</button>`
                    : '';
                return `
                <div id="mailingDispatchRow_${i}" style="display:grid; grid-template-columns:1fr auto auto${isWpp ? ' auto' : ''}; gap:10px; align-items:center; padding:10px 12px; border:1px solid #e5e7eb; border-radius:8px; background:#fff;">
                    <div style="min-width:0; overflow:hidden;">
                        <div style="font-weight:600; color:#065f46;">${escapeHtml(d.contact.name || '-')}</div>
                        ${subInfo}
                    </div>
                    <span class="mailing-dispatch-status" id="mailingDispatchStatus_${i}" style="font-size:12px; color:#92400e; white-space:nowrap;">Pendente</span>
                    ${wahaBtn}
                    <button id="mailingDispatchBtn_${i}" class="btn btn-primary btn-small" onclick="sendAutoTocaMailingDispatchOne(${i})">${btnIcon} ${btnLabel}</button>
                </div>`;
            }).join('');

            const batchBtnHtml = isWpp
                ? `<button class="btn btn-auto-mapping btn-small" onclick="dispatchMailingViaWahaAll()" title="Envia toda a fila direto via WAHA, com intervalo aleatório entre mensagens"><span class="ai-star-icon">✦</span> Enviar todos via WAHA</button>
                   <button class="btn btn-secondary btn-small" onclick="scheduleMailingViaWaha()" title="Agendar o envio de toda a fila via WAHA para uma data e horário"><i class="fas fa-clock"></i> Agendar</button>
                   <span id="mailingWahaQuota" style="font-size:12px; color:#6b7280;"></span>
                   <button id="mailingDispatchBatchBtn" class="btn btn-secondary btn-small" onclick="sendAutoTocaMailingDispatchAll()"><i class="fas fa-forward-step"></i> Abrir próximo no WhatsApp</button>`
                : `<button id="mailingDispatchBatchBtn" class="btn btn-secondary btn-small" onclick="sendAutoTocaMailingDispatchAll()"><i class="fas fa-bolt"></i> Tentar abrir todos de uma vez</button>`;

            const batchNote = isWpp
                ? `Cada mensagem WhatsApp deve ser aberta e enviada individualmente — o sistema reutiliza a mesma aba do WhatsApp Web. Use <strong>Abrir próximo no WhatsApp</strong> para ciclar pelos contatos em sequência, ou <strong>Abrir no WhatsApp</strong> em cada linha para enviar um por vez.`
                : `Para evitar o bloqueador de pop-ups do navegador, cada janela do Outlook é aberta por um clique individual.
                   Clique em <strong>Abrir no Outlook</strong> em cada linha para disparar a janela correspondente e registrar automaticamente a atividade daquele contato.
                   Se você já autorizou pop-ups deste site, pode tentar o modo em lote no botão abaixo.`;

            const skippedNote = skipped
                ? `<p style="color:#92400e; font-size:12px; margin-bottom:10px;">${skipped} contato(s) sem ${isWpp ? 'telefone' : 'e-mail'} foram ignorados.</p>`
                : '';

            const html = `
                <div class="modal active" id="autoTocaMailingDispatchModal" onclick="if(event.target===this) closeAutoTocaMailingDispatchModal()">
                    <div class="modal-content" style="max-width:900px;">
                        <h2 style="color:#047857; margin-bottom:8px;">Mala Direta — Despacho ${isWpp ? '<i class="fab fa-whatsapp" style="color:#25d366; font-size:20px;"></i>' : '<i class="fas fa-envelope"></i>'}</h2>
                        <p style="color:#4b5563; font-size:13px; margin-bottom:10px; line-height:1.45;">${batchNote}</p>
                        ${skippedNote}
                        <div style="display:flex; gap:8px; margin-bottom:12px; align-items:center; flex-wrap:wrap;">
                            ${batchBtnHtml}
                            <span id="mailingDispatchCounter" style="font-size:12px; color:#6b7280;">0 de ${drafts.length} enviados</span>
                        </div>
                        <div id="mailingWahaProgress" style="display:none; padding:8px 4px 12px;">
                            <div style="font-size:13px; color:#6b7280; margin-bottom:8px; text-align:center;" id="mailingWahaProgressStep">Iniciando...</div>
                            <div style="position:relative; background:#d1fae5; border-radius:99px; height:12px; overflow:visible; margin:0 16px;">
                                <div id="mailingWahaProgressBar" style="position:relative; height:100%; width:5%; background:linear-gradient(90deg,#059669,#10b981,#34d399); border-radius:99px; transition:width .6s ease;">
                                    <img src="/images/coelho-correndo.webp" class="coelho-run" alt="">
                                </div>
                            </div>
                        </div>
                        <div style="display:flex; flex-direction:column; gap:8px; max-height:55vh; overflow:auto; padding-right:4px;">
                            ${rowsHtml}
                        </div>
                        <div style="display:flex; justify-content:flex-end; margin-top:14px;">
                            <button class="btn btn-secondary" onclick="closeAutoTocaMailingDispatchModal()">Fechar</button>
                        </div>
                    </div>
                </div>
            `;
            document.body.insertAdjacentHTML('beforeend', html);
            if (isWpp && typeof _wahaRefreshQuota === 'function') _wahaRefreshQuota();
            tocaDebug('mala-direta.dispatch-modal', 'Modal de despacho aberto', { total: drafts.length, channel: drafts[0]?.channel });
        }

        function closeAutoTocaMailingDispatchModal() {
            document.getElementById('autoTocaMailingDispatchModal')?.remove();
            autoTocaMailingDispatchDrafts = [];
        }

        function _updateAutoTocaMailingDispatchRow(idx) {
            const draft = autoTocaMailingDispatchDrafts[idx];
            if (!draft) return;
            const statusEl = document.getElementById(`mailingDispatchStatus_${idx}`);
            const btnEl = document.getElementById(`mailingDispatchBtn_${idx}`);
            const rowEl = document.getElementById(`mailingDispatchRow_${idx}`);
            if (statusEl) {
                statusEl.textContent = 'Enviado';
                statusEl.style.color = '#065f46';
            }
            if (btnEl) {
                btnEl.disabled = true;
                btnEl.innerHTML = '<i class="fas fa-check"></i> Enviado';
            }
            if (rowEl) {
                rowEl.style.background = 'rgba(236,253,245,.55)';
                rowEl.style.borderColor = 'rgba(16,185,129,.35)';
            }
            const sentCount = autoTocaMailingDispatchDrafts.filter(d => d.status === 'sent').length;
            const counterEl = document.getElementById('mailingDispatchCounter');
            if (counterEl) counterEl.textContent = `${sentCount} de ${autoTocaMailingDispatchDrafts.length} enviados`;
        }

        async function _registerAutoTocaMailingActivity(draft) {
            try {
                const formData = new FormData();
                formData.set('client_id', draft.contact.id);
                formData.set('contact_type', draft.channel === 'whatsapp' ? 'WhatsApp' : 'Email');
                formData.set('information', draft.body || (draft.channel === 'whatsapp' ? 'Mensagem WhatsApp enviada.' : 'Email enviado.'));
                const response = await fetch(`${API_BASE}/atividades`, { method: 'POST', body: formData });
                if (!response.ok) {
                    tocaDebug('mala-direta.activity', 'Falha HTTP ao registrar atividade', {
                        idx: draft.idx,
                        contact_id: draft.contact.id,
                        status: response.status
                    });
                    return false;
                }
                tocaDebug('mala-direta.activity', 'Atividade registrada', {
                    idx: draft.idx,
                    contact_id: draft.contact.id
                });
                const payload = await response.json().catch(() => ({}));
                return payload.id || true;
            } catch (e) {
                tocaDebug('mala-direta.activity', 'Erro ao registrar atividade', {
                    idx: draft.idx,
                    contact_id: draft.contact.id,
                    error: String(e)
                });
                return false;
            }
        }

        async function sendAutoTocaMailingDispatchOne(idx) {
            const draft = autoTocaMailingDispatchDrafts[idx];
            if (!draft || draft.status === 'sent') return;

            const isWpp = draft.channel === 'whatsapp';

            tocaDebug('mala-direta.dispatch-one', 'Abrindo janela individual', {
                idx,
                contact_id: draft.contact.id,
                channel: draft.channel,
                contact: isWpp ? draft.phone : draft.contact.email
            });

            if (isWpp) {
                // WhatsApp: respeita preferência desktop/web igual ao dashboard
                if (getWhatsAppPreference() === 'desktop') {
                    openWhatsAppDesktopWithFallback(draft.phone, draft.body);
                } else {
                    const webUrl = `https://web.whatsapp.com/send?phone=${encodeURIComponent(draft.phone)}&text=${encodeURIComponent(draft.body)}`;
                    openWhatsAppTab(webUrl);
                }
            } else {
                // Email: abre no Outlook Web
                const win = window.open(draft.url, '_blank');
                if (!win) {
                    tocaDebug('mala-direta.dispatch-one', 'window.open retornou null (pop-up bloqueado)', {
                        idx,
                        contact_id: draft.contact.id
                    });
                    showError('O navegador bloqueou a janela. Permita pop-ups para este site e tente novamente.');
                    return;
                }
            }

            draft.status = 'sent';
            _updateAutoTocaMailingDispatchRow(idx);

            // Registro automático da atividade (Bloco 8) — sem perguntar por
            // contato; toast com opção de desfazer por ~10s.
            const activityId = await _registerAutoTocaMailingActivity(draft);
            if (activityId) {
                if (typeof showUndoToast === 'function' && Number(activityId)) {
                    showUndoToast('Atividade registrada — desfazer', async () => {
                        try { await fetch(`${API_BASE}/atividades/${activityId}`, { method: 'DELETE' }); } catch (e) {}
                        try { await Promise.all([loadActivities(), loadDashboard()]); } catch (e) {}
                    });
                }
                try { await Promise.all([loadActivities(), loadDashboard()]); } catch (e) {}
            }
        }

        // Estado e helpers do modal de orientação para liberar pop-ups.
        // O callback de "Já liberei" é mantido num módulo para que seja chamado
        // SINCRONAMENTE pelo onclick do botão, preservando o user gesture necessário
        // para que o navegador permita múltiplos window.open() em sequência.
        const _AUTOTOCA_MAILING_POPUP_HELP_KEY = 'autoTocaMailing_popupHelpDismissed';
        let _autoTocaMailingPopupHelpOnProceed = null;

        function _isAutoTocaMailingPopupHelpDismissed() {
            try {
                return localStorage.getItem(_AUTOTOCA_MAILING_POPUP_HELP_KEY) === 'true';
            } catch (e) {
                return false;
            }
        }

        function _openAutoTocaMailingPopupHelpModal(onProceed) {
            _autoTocaMailingPopupHelpOnProceed = onProceed;
            const origin = window.location.origin || 'http://localhost:3000';
            const html = `
                <div class="modal active" id="autoTocaMailingPopupHelpModal" onclick="if(event.target===this) _closeAutoTocaMailingPopupHelpModal()">
                    <div class="modal-content" style="max-width:580px;">
                        <h2 style="color:#047857; margin-bottom:8px;"><i class="fas fa-shield-alt"></i> Libere pop-ups para abrir o lote</h2>
                        <p style="color:#4b5563; font-size:13px; line-height:1.5; margin-bottom:12px;">
                            Para abrir várias janelas do Outlook de uma só vez, o navegador precisa permitir pop-ups e redirecionamentos deste site. Faça isso <strong>uma única vez</strong> seguindo os passos abaixo.
                        </p>
                        <div style="background:rgba(236,253,245,.55); border:1px solid rgba(16,185,129,.25); border-radius:8px; padding:12px 14px; margin-bottom:12px;">
                            <strong style="color:#065f46;">No Google Chrome / Microsoft Edge</strong>
                            <ol style="margin:8px 0 0 18px; padding:0; color:#1f2937; font-size:13px; line-height:1.7;">
                                <li>Abra uma nova aba e cole na barra de endereço: <code style="background:#fff; padding:2px 6px; border-radius:4px; border:1px solid #e5e7eb;">chrome://settings/content/popups</code></li>
                                <li>Na seção <em>"Permitido enviar pop-ups e usar redirecionamentos"</em>, clique em <strong>Adicionar</strong>.</li>
                                <li>Cole o endereço deste sistema: <code style="background:#fff; padding:2px 6px; border-radius:4px; border:1px solid #e5e7eb;">${escapeHtml(origin)}</code> e confirme.</li>
                                <li>Volte para esta aba e clique em <strong>Já liberei, abrir todos</strong>.</li>
                            </ol>
                        </div>
                        <div style="background:#fff; border:1px solid #e5e7eb; border-radius:8px; padding:10px 12px; margin-bottom:14px; font-size:12px; color:#4b5563; line-height:1.5;">
                            <strong style="color:#065f46;">Atalho:</strong> se tentar o lote mesmo bloqueado, vai aparecer um ícone <i class="fas fa-ban" style="color:#dc2626;"></i> à direita da barra de endereço. Clique nele e escolha <em>"Sempre permitir pop-ups e redirecionamentos de ${escapeHtml(origin)}"</em>.
                        </div>
                        <label style="display:flex; align-items:center; gap:8px; font-size:13px; color:#374151; cursor:pointer; margin-bottom:14px;">
                            <input type="checkbox" id="autoTocaMailingPopupHelpDontShow" style="cursor:pointer; width:16px; height:16px;">
                            Não mostrar este aviso novamente
                        </label>
                        <div style="display:flex; justify-content:flex-end; gap:8px;">
                            <button class="btn btn-secondary" onclick="_closeAutoTocaMailingPopupHelpModal()">Cancelar</button>
                            <button class="btn btn-primary" onclick="_confirmAutoTocaMailingPopupHelp()"><i class="fas fa-bolt"></i> Já liberei, abrir todos</button>
                        </div>
                    </div>
                </div>
            `;
            document.body.insertAdjacentHTML('beforeend', html);
            tocaDebug('mala-direta.popup-help', 'Modal de orientação aberto');
        }

        function _closeAutoTocaMailingPopupHelpModal() {
            document.getElementById('autoTocaMailingPopupHelpModal')?.remove();
            _autoTocaMailingPopupHelpOnProceed = null;
            tocaDebug('mala-direta.popup-help', 'Modal de orientação cancelado');
        }

        function _confirmAutoTocaMailingPopupHelp() {
            const dontShow = !!document.getElementById('autoTocaMailingPopupHelpDontShow')?.checked;
            if (dontShow) {
                try { localStorage.setItem(_AUTOTOCA_MAILING_POPUP_HELP_KEY, 'true'); } catch (e) {}
            }
            const cb = _autoTocaMailingPopupHelpOnProceed;
            _autoTocaMailingPopupHelpOnProceed = null;
            document.getElementById('autoTocaMailingPopupHelpModal')?.remove();
            tocaDebug('mala-direta.popup-help', 'Orientação confirmada — disparando lote', { dontShow });
            // Chamada síncrona aqui é CRÍTICA — estamos dentro do onclick do botão,
            // então o user gesture continua válido para os window.open() em sequência.
            if (cb) cb();
        }

        function sendAutoTocaMailingDispatchAll() {
            const pending = autoTocaMailingDispatchDrafts.filter(d => d.status === 'pending');
            if (!pending.length) {
                showInfo('Não há mensagens pendentes para abrir.');
                return;
            }

            if (_autoTocaMailingChannel === 'whatsapp') {
                // WhatsApp: modo sequencial — respeita preferência desktop/web
                const draft = pending[0];
                if (getWhatsAppPreference() === 'desktop') {
                    openWhatsAppDesktopWithFallback(draft.phone, draft.body);
                } else {
                    const webUrl = `https://web.whatsapp.com/send?phone=${encodeURIComponent(draft.phone)}&text=${encodeURIComponent(draft.body)}`;
                    openWhatsAppTab(webUrl);
                }
                draft.status = 'sent';
                _updateAutoTocaMailingDispatchRow(draft.idx);

                const remaining = autoTocaMailingDispatchDrafts.filter(d => d.status === 'pending');
                const batchBtnEl = document.getElementById('mailingDispatchBatchBtn');
                if (batchBtnEl) {
                    if (remaining.length > 0) {
                        batchBtnEl.innerHTML = `<i class="fas fa-forward-step"></i> Próximo (${remaining.length} restantes)`;
                    } else {
                        batchBtnEl.innerHTML = `<i class="fas fa-check-double"></i> Todos abertos`;
                        batchBtnEl.disabled = true;
                    }
                }

                (async () => {
                    const contactName = draft.contact.name || draft.phone;
                    const shouldRegister = await uiConfirm(
                        `Deseja registrar essa interação de WhatsApp como atividade em "${contactName}"?`
                    );
                    if (shouldRegister) {
                        const ok = await _registerAutoTocaMailingActivity(draft);
                        if (ok) {
                            try { await Promise.all([loadActivities(), loadDashboard()]); } catch (e) {}
                        }
                    }
                })();
                return;
            }

            // Email: verifica permissão de pop-ups e abre todos de uma vez
            if (!_isAutoTocaMailingPopupHelpDismissed()) {
                _openAutoTocaMailingPopupHelpModal(_doAutoTocaMailingDispatchAll);
                return;
            }

            _doAutoTocaMailingDispatchAll();
        }

        function _doAutoTocaMailingDispatchAll() {
            const pending = autoTocaMailingDispatchDrafts.filter(d => d.status === 'pending');
            if (!pending.length) {
                showInfo('Não há e-mails pendentes para abrir.');
                return;
            }

            tocaDebug('mala-direta.dispatch-all', 'Tentando abrir todas as janelas pendentes', {
                pending: pending.length
            });

            // IMPORTANTE: o loop precisa ser SÍNCRONO para preservar o "user gesture".
            const results = [];
            for (const draft of pending) {
                const win = window.open(draft.url, '_blank');
                results.push({ draft, opened: !!win });
            }

            // Depois do loop síncrono, processamos os resultados e pedimos uma ÚNICA
            // confirmação para registrar todas as atividades dos e-mails que abriram
            // (evita N diálogos consecutivos num único clique "abrir todos").
            (async () => {
                let sent = 0;
                let blocked = 0;
                const openedDrafts = [];
                for (const { draft, opened } of results) {
                    if (!opened) {
                        blocked++;
                        tocaDebug('mala-direta.dispatch-all', 'Pop-up bloqueado em lote', {
                            idx: draft.idx,
                            contact_id: draft.contact.id
                        });
                        continue;
                    }
                    draft.status = 'sent';
                    _updateAutoTocaMailingDispatchRow(draft.idx);
                    sent++;
                    openedDrafts.push(draft);
                }

                let registered = 0;
                if (openedDrafts.length) {
                    const shouldRegister = await uiConfirm(
                        `Deseja registrar essas ${openedDrafts.length} interações de Email como atividades nos contatos correspondentes?`
                    );
                    tocaDebug('mala-direta.dispatch-all', 'Decisão sobre registro em lote', {
                        count: openedDrafts.length,
                        register: !!shouldRegister
                    });
                    if (shouldRegister) {
                        for (const draft of openedDrafts) {
                            const ok = await _registerAutoTocaMailingActivity(draft);
                            if (ok) registered++;
                        }
                        if (registered) {
                            try { await Promise.all([loadActivities(), loadDashboard()]); } catch (e) {}
                        }
                    }
                }

                tocaDebug('mala-direta.dispatch-all', 'Resultado do lote', { sent, blocked, registered });
                if (blocked && !sent) {
                    showError(`O navegador bloqueou todas as ${blocked} janelas. Permita pop-ups para este site ou clique em cada linha individualmente.`);
                } else if (blocked) {
                    showInfo(`${sent} e-mail(is) aberto(s)${registered ? ` — ${registered} atividade(s) registrada(s)` : ''}. ${blocked} foram bloqueado(s) pelo navegador — clique individualmente nas linhas pendentes.`);
                } else {
                    showSuccess(`${sent} e-mail(is) aberto(s)${registered ? ` — ${registered} atividade(s) registrada(s)` : ''}.`);
                }
            })();
        }

        async function autotocaAutoFill(evt) {
            const conta = document.getElementById('autotocaConta').value === 'OUTRO'
                ? document.getElementById('autotocaContaOutro').value.trim()
                : document.getElementById('autotocaConta').value;
            if (!conta) return showError('Selecione ou informe a Conta antes de usar o AutoFill.');

            const btn = evt?.currentTarget || document.getElementById('autotocaAutoFillBtn');
            const originalHtml = btn?.innerHTML;
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Buscando...';
            }

            try {
                const response = await fetch(`${API_BASE}/autotoca/account-info`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ account_name: conta })
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || 'Falha ao buscar dados da conta.');

                document.getElementById('autotocaRazaoSocial').value = data.razao_social || '';
                document.getElementById('autotocaCnpj').value = data.cnpj || '';
                document.getElementById('autotocaEnderecoFinal').value = data.endereco || '';

                if (data.razao_social || data.cnpj || data.endereco) {
                    showSuccess('Dados preenchidos pelo AutoFill. Confira antes de enviar.');
                } else {
                    showInfo('Não encontrei dados confiáveis. Por favor, preencha manualmente.');
                }
            } catch (e) {
                showError(e.message);
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = originalHtml;
                }
            }
        }

        async function loadAutoTocaSupportFiles() {
            const container = document.getElementById('autotocaSupportFilesList');
            if (!container) return;

            container.innerHTML = '<div style="color:#6b7280; font-size:13px;">Carregando arquivos...</div>';
            try {
                const response = await fetch(`${API_BASE}/autotoca/support-files`);
                const files = response.ok ? await response.json() : [];
                if (!Array.isArray(files) || !files.length) {
                    container.innerHTML = '<div style="color:#6b7280; font-size:13px;">Adicione os PDFs da pasta de apoio para exibi-los aqui.</div>';
                    return;
                }

                container.innerHTML = files.map(file => `
                    <a href="${escapeHtml(file.url || '#')}" download class="btn btn-secondary" style="justify-content:flex-start; gap:10px; text-decoration:none;">
                        <i class="fas fa-file-pdf" style="color:#dc2626;"></i>
                        <span style="white-space:normal; text-align:left;">${escapeHtml(file.name || 'Arquivo.pdf')}</span>
                    </a>
                `).join('');
            } catch (error) {
                container.innerHTML = '<div style="color:#b91c1c; font-size:13px;">Não foi possível carregar os arquivos de apoio.</div>';
            }
        }

        function _autoTocaGetLogsEl() {
            return document.getElementById('autotocaLogs');
        }

        function _autoTocaRenderLogLines(lines = []) {
            const el = _autoTocaGetLogsEl();
            if (!el) return;
            const html = lines.map(line => `<div style="margin-bottom:6px;">${line}</div>`).join('');
            el.innerHTML = html || '<span style="color:#6b7280;">Sem logs.</span>';
        }

        function _autoTocaAppendLog(message, tone = 'info') {
            const el = _autoTocaGetLogsEl();
            if (!el) return;
            const palette = {
                info: '#374151',
                success: '#065f46',
                warning: '#92400e',
                error: '#b91c1c',
            };
            const color = palette[tone] || palette.info;
            const stamp = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            el.insertAdjacentHTML('beforeend', `<div style="margin-bottom:6px; color:${color};">[${stamp}] ${escapeHtml(message)}</div>`);
        }

        function _chamadoRobotEnsureStyles() {
            if (document.getElementById('chamado-robot-bunny-style')) return;
            const style = document.createElement('style');
            style.id = 'chamado-robot-bunny-style';
            style.textContent = `
                @keyframes chamado-robot-hop { 0%,100%{transform:translateY(-50%) scaleY(1)} 50%{transform:translateY(-70%) scaleY(.85)} }
                @keyframes chamado-robot-paw-fade { 0%,100%{opacity:.25} 50%{opacity:.7} }
                .chamado-robot-bunny { position:absolute; right:-14px; top:50%; transform:translateY(-50%); font-size:18px; line-height:1; animation:chamado-robot-hop .5s ease-in-out infinite; pointer-events:none; }
                .chamado-robot-paw { display:inline-block; font-size:10px; animation:chamado-robot-paw-fade 1s ease-in-out infinite; }
                .chamado-robot-paw:nth-child(2){animation-delay:.2s} .chamado-robot-paw:nth-child(3){animation-delay:.4s}
            `;
            document.head.appendChild(style);
        }

        function _chamadoRobotSetProgress(pct, step) {
            const bar = document.getElementById('autotocaRobotBar');
            const stepEl = document.getElementById('autotocaRobotStep');
            const pctEl = document.getElementById('autotocaRobotPct');
            if (bar) bar.style.width = Math.max(5, pct) + '%';
            if (stepEl) stepEl.textContent = step || '';
            if (pctEl) pctEl.textContent = Math.round(pct) + '%';
        }

        function _chamadoRobotToggleRunning(running) {
            const robotBtn = document.getElementById('autotocaRobotBtn');
            const progressArea = document.getElementById('autotocaRobotProgress');
            if (robotBtn) robotBtn.disabled = running;
            if (progressArea) progressArea.style.display = running ? 'block' : 'none';
        }

        // Campos de upload do Chamado Jurídico — mesmas chaves aceitas pelo backend
        // (ver CHAMADO_JURIDICO_FILE_FIELDS em app.py).
        const CJ_FILE_FIELDS = [
            { key: 'aditivos_anteriores', label: 'Aditivos anteriores', multiple: true },
            { key: 'contrato_anterior', label: 'Contrato Anterior', multiple: false },
            { key: 'minuta_cliente', label: 'Há minuta do cliente?', multiple: false },
            { key: 'aprovacao_reajuste', label: 'Aprovação de Reajuste Diferente do Contrato', multiple: false },
            { key: 'proposta_comercial_tecnica', label: 'Proposta comercial e técnica', multiple: false },
        ];

        function _cjFileInputId(key) { return `cjFile_${key}`; }

        function _cjRenderFileFields() {
            const grid = document.getElementById('cjFileFieldsGrid');
            if (!grid || grid.dataset.rendered) return;
            grid.dataset.rendered = '1';
            grid.innerHTML = CJ_FILE_FIELDS.map(f => `
                <div class="form-group">
                    <label>${escapeHtml(f.label)}</label>
                    <input type="file" id="${_cjFileInputId(f.key)}" ${f.multiple ? 'multiple' : ''} onchange="_cjOnFileChange('${f.key}')">
                    <div id="${_cjFileInputId(f.key)}List" style="margin-top:4px;"></div>
                    <button type="button" id="${_cjFileInputId(f.key)}Reuse" onclick="_cjToggleReuseFile('${f.key}')"
                        style="display:none; margin-top:6px; font-size:11px; padding:4px 10px; border-radius:12px; border:1px solid #059669; background:#fff; color:#059669; cursor:pointer;"></button>
                </div>
            `).join('');
        }

        function _cjRenderFileList(key) {
            const input = document.getElementById(_cjFileInputId(key));
            const listEl = document.getElementById(`${_cjFileInputId(key)}List`);
            if (!input || !listEl) return;
            const files = Array.from(input.files || []);
            listEl.innerHTML = files.map((f, idx) => `
                <span style="display:inline-flex; align-items:center; gap:4px; background:#f3f4f6; border-radius:12px; padding:2px 8px; margin:2px 4px 2px 0; font-size:11px;">
                    ${escapeHtml(f.name)}
                    <button type="button" onclick="_cjRemoveFile('${key}', ${idx})" title="Remover arquivo" style="border:0; background:transparent; color:#dc2626; cursor:pointer; font-weight:700; padding:0 2px; line-height:1;">×</button>
                </span>
            `).join('');
        }

        function _cjRemoveFile(key, index) {
            const input = document.getElementById(_cjFileInputId(key));
            if (!input) return;
            const dt = new DataTransfer();
            Array.from(input.files || []).forEach((f, i) => { if (i !== index) dt.items.add(f); });
            input.files = dt.files;
            _cjRenderFileList(key);
        }

        function _cjOnFileChange(key) {
            // Selecionar um arquivo novo cancela o reaproveitamento do histórico
            // para esse campo — nunca os dois juntos (era assim que o robô acabava
            // enviando o anexo antigo E o novo ao mesmo tempo para o Forms).
            _cjReuseSelectedFields.delete(key);
            _cjRenderReuseChipState(key);
            _cjRenderFileList(key);
        }

        // Nomes dos arquivos do histórico disponíveis para reaproveitar, por campo —
        // preenchido em onChamadoHistorySelect(). Usado só para exibir o texto do chip.
        let _cjReuseFileNames = {};

        function _cjSetReuseChip(key, fileNames) {
            const btn = document.getElementById(`${_cjFileInputId(key)}Reuse`);
            if (!btn) return;
            _cjReuseFileNames[key] = fileNames || [];
            if (!fileNames || !fileNames.length) {
                btn.style.display = 'none';
                return;
            }
            btn.style.display = 'inline-block';
            _cjRenderReuseChipState(key);
        }

        function _cjRenderReuseChipState(key) {
            const btn = document.getElementById(`${_cjFileInputId(key)}Reuse`);
            if (!btn) return;
            const names = (_cjReuseFileNames[key] || []).join(', ');
            const selected = _cjReuseSelectedFields.has(key);
            btn.style.background = selected ? '#059669' : '#fff';
            btn.style.color = selected ? '#fff' : '#059669';
            btn.textContent = (selected ? '✓ Anexado: ' : '📎 Usar do histórico: ') + names;
        }

        function _cjToggleReuseFile(key) {
            if (_cjReuseSelectedFields.has(key)) {
                _cjReuseSelectedFields.delete(key);
            } else {
                _cjReuseSelectedFields.add(key);
                // Mutuamente exclusivo com um upload novo no mesmo campo.
                const input = document.getElementById(_cjFileInputId(key));
                if (input) { input.value = ''; _cjRenderFileList(key); }
            }
            _cjRenderReuseChipState(key);
        }

        function _cjToggleConditional(triggerId, wrapId) {
            const trigger = document.getElementById(triggerId);
            const wrap = document.getElementById(wrapId);
            if (!trigger || !wrap) return;
            const show = trigger.value === 'Sim';
            wrap.style.display = show ? '' : 'none';
            const input = wrap.querySelector('input, textarea');
            if (input) {
                input.disabled = !show;
                input.required = show;
                if (!show) input.value = '';
            }
        }

        let _cjReuseHistoryId = '';
        let _cjReuseSelectedFields = new Set();

        // Limpa todos os campos do Chamado Jurídico — chamado ao sair do módulo/aba,
        // para que o usuário sempre encontre o formulário em branco na próxima visita.
        function _cjResetForm() {
            const textIds = [
                'autotocaContaOutro', 'autotocaRazaoSocial', 'autotocaCnpj', 'autotocaEnderecoFinal',
                'cjMinutaTipo', 'cjOppSalesforce', 'cjDataAssinatura', 'cjHaveraReajuste', 'cjValoresReajuste',
                'cjHouveReoneracao', 'cjInclutNovosServicos', 'cjProrrogacaoVigencia', 'cjVigenciaDatas',
                'cjAssinaturaPlataforma', 'cjDescricaoPedido',
            ];
            textIds.forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });

            const contaSelect = document.getElementById('autotocaConta');
            if (contaSelect) contaSelect.selectedIndex = 0;
            const contaOutroWrap = document.getElementById('autotocaContaOutroWrap');
            if (contaOutroWrap) contaOutroWrap.style.display = 'none';

            _cjToggleConditional('cjHaveraReajuste', 'cjValoresReajusteWrap');
            _cjToggleConditional('cjProrrogacaoVigencia', 'cjVigenciaDatasWrap');

            _cjReuseSelectedFields.clear();
            CJ_FILE_FIELDS.forEach(f => {
                const input = document.getElementById(_cjFileInputId(f.key));
                if (input) input.value = '';
                _cjRenderFileList(f.key);
                _cjSetReuseChip(f.key, []);
            });

            _cjReuseHistoryId = '';
            const historySelect = document.getElementById('cjHistorySelect');
            if (historySelect) historySelect.value = '';
        }

        async function loadChamadoJuridicoHistory() {
            const select = document.getElementById('cjHistorySelect');
            if (!select) return;
            try {
                const response = await fetch(`${API_BASE}/autotoca/chamado-juridico/history`);
                const items = response.ok ? await response.json() : [];
                const current = select.value;
                select.innerHTML = '<option value="">Novo chamado (em branco)</option>' + items.map(item => {
                    const when = item.created_at ? new Date(item.created_at.replace(' ', 'T')).toLocaleDateString('pt-BR') : '';
                    const label = `${item.conta}${item.proposta_original_name ? ' — ' + item.proposta_original_name : ''} (${when})`;
                    return `<option value="${item.id}">${escapeHtml(label)}</option>`;
                }).join('');
                select.value = current;
            } catch (_) { /* histórico é conveniência, falha silenciosa */ }
        }

        async function onChamadoHistorySelect() {
            const select = document.getElementById('cjHistorySelect');
            const historyId = select?.value || '';
            _cjReuseHistoryId = historyId;
            if (!historyId) return;

            try {
                const response = await fetch(`${API_BASE}/autotoca/chamado-juridico/history/${historyId}`);
                if (!response.ok) throw new Error('Não foi possível carregar esse histórico.');
                const entry = await response.json();
                const p = entry.payload || {};

                const setVal = (id, value) => { const el = document.getElementById(id); if (el) el.value = value || ''; };
                setVal('autotocaRazaoSocial', p.razao_social);
                setVal('autotocaCnpj', p.cnpj);
                setVal('autotocaEnderecoFinal', p.endereco);
                setVal('cjMinutaTipo', p.minuta_tipo);
                setVal('cjOppSalesforce', p.opp_salesforce);
                setVal('cjDataAssinatura', p.data_assinatura);
                setVal('cjHaveraReajuste', p.havera_reajuste);
                setVal('cjValoresReajuste', p.valores_reajuste);
                setVal('cjHouveReoneracao', p.houve_reoneracao);
                setVal('cjInclutNovosServicos', p.inclui_novos_servicos);
                setVal('cjProrrogacaoVigencia', p.e_prorrogacao_vigencia);
                setVal('cjVigenciaDatas', p.vigencia_datas);
                setVal('cjAssinaturaPlataforma', p.assinatura_plataforma);
                setVal('cjDescricaoPedido', p.descricao_pedido);
                _cjToggleConditional('cjHaveraReajuste', 'cjValoresReajusteWrap');
                _cjToggleConditional('cjProrrogacaoVigencia', 'cjVigenciaDatasWrap');

                const contaSelect = document.getElementById('autotocaConta');
                if (contaSelect && p.conta) {
                    const hasOption = Array.from(contaSelect.options).some(o => o.value === p.conta);
                    contaSelect.value = hasOption ? p.conta : 'OUTRO';
                    if (!hasOption) {
                        document.getElementById('autotocaContaOutroWrap').style.display = 'block';
                        document.getElementById('autotocaContaOutro').value = p.conta;
                    }
                }

                _cjReuseSelectedFields.clear();
                CJ_FILE_FIELDS.forEach(f => {
                    const input = document.getElementById(_cjFileInputId(f.key));
                    if (input) input.value = '';
                    _cjRenderFileList(f.key);
                    const files = (entry.files || {})[f.key] || [];
                    _cjSetReuseChip(f.key, files.map(x => x.original_name));
                });

                showInfo('Histórico carregado. Clique nos anexos que quiser reaproveitar e confira os campos antes de acionar o robô.');
            } catch (error) {
                showError(error.message || 'Erro ao carregar histórico.');
            }
        }

        function _cjValidate(conta, endereco) {
            const required = [
                ['cjMinutaTipo', 'Minuta/Contrato é do cliente ou da Stefanini'],
                ['cjHaveraReajuste', 'Haverá Reajuste'],
                ['cjHouveReoneracao', 'Houve reoneração'],
                ['cjInclutNovosServicos', 'Inclui novos serviços'],
                ['cjProrrogacaoVigencia', 'É prorrogação de vigência'],
                ['cjAssinaturaPlataforma', 'Assinatura pela plataforma'],
                ['cjDescricaoPedido', 'Descrição do pedido'],
            ];
            if (!conta) return 'Preencha a Conta.';
            if (!endereco) return 'Preencha o Endereço.';
            for (const [id, label] of required) {
                if (!(document.getElementById(id)?.value || '').trim()) return `Preencha "${label}".`;
            }
            if (document.getElementById('cjHaveraReajuste').value === 'Sim' && !document.getElementById('cjValoresReajuste').value.trim()) {
                return 'Descreva os valores de reajuste.';
            }
            if (document.getElementById('cjProrrogacaoVigencia').value === 'Sim' && !document.getElementById('cjVigenciaDatas').value.trim()) {
                return 'Informe a data inicial e final da vigência.';
            }
            return null;
        }

        async function runChamadoJuridicoRobot(event) {
            event?.preventDefault?.();

            const conta = document.getElementById('autotocaConta').value === 'OUTRO'
                ? document.getElementById('autotocaContaOutro').value.trim()
                : document.getElementById('autotocaConta').value;
            const endereco = document.getElementById('autotocaEnderecoFinal').value.trim();

            const validationError = _cjValidate(conta, endereco);
            if (validationError) {
                showError(validationError);
                return;
            }

            const fd = new FormData();
            fd.append('conta', conta);
            fd.append('razao_social', document.getElementById('autotocaRazaoSocial').value.trim());
            fd.append('cnpj', document.getElementById('autotocaCnpj').value.trim());
            fd.append('endereco', endereco);
            fd.append('minuta_tipo', document.getElementById('cjMinutaTipo').value);
            fd.append('opp_salesforce', document.getElementById('cjOppSalesforce').value.trim());
            fd.append('data_assinatura', document.getElementById('cjDataAssinatura').value);
            fd.append('havera_reajuste', document.getElementById('cjHaveraReajuste').value);
            fd.append('valores_reajuste', document.getElementById('cjValoresReajuste').value.trim());
            fd.append('houve_reoneracao', document.getElementById('cjHouveReoneracao').value);
            fd.append('inclui_novos_servicos', document.getElementById('cjInclutNovosServicos').value);
            fd.append('e_prorrogacao_vigencia', document.getElementById('cjProrrogacaoVigencia').value);
            fd.append('vigencia_datas', document.getElementById('cjVigenciaDatas').value.trim());
            fd.append('assinatura_plataforma', document.getElementById('cjAssinaturaPlataforma').value);
            fd.append('descricao_pedido', document.getElementById('cjDescricaoPedido').value.trim());
            if (_cjReuseHistoryId) {
                fd.append('reuse_history_id', _cjReuseHistoryId);
                fd.append('reuse_fields', JSON.stringify(Array.from(_cjReuseSelectedFields)));
            }

            CJ_FILE_FIELDS.forEach(f => {
                const input = document.getElementById(_cjFileInputId(f.key));
                Array.from(input?.files || []).forEach(file => fd.append(f.key, file));
            });

            _chamadoRobotEnsureStyles();
            _chamadoRobotToggleRunning(true);
            _chamadoRobotSetProgress(5, 'Iniciando o robô...');
            _autoTocaAppendLog('Robô do Chamado Jurídico iniciado. Uma janela do navegador será aberta.', 'info');

            try {
                const response = await fetch(`${API_BASE}/autotoca/chamado-juridico/robot`, { method: 'POST', body: fd });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.error || 'Erro ao iniciar o robô.');
                const taskId = data.task_id;
                if (!taskId) throw new Error('Resposta inesperada do servidor.');

                const progressEl = document.getElementById('autotocaRobotProgress');
                _attachBgTaskControls(
                    progressEl, taskId,
                    () => _chamadoRobotToggleRunning(false),
                    () => { _chamadoRobotToggleRunning(false); showError('Acompanhamento do robô cancelado — a janela dele pode continuar aberta.'); }
                );

                const sourceTab = typeof _currentTab !== 'undefined' ? _currentTab : 'autotoca';
                BgTaskManager.register(
                    taskId,
                    `${API_BASE}/autotoca/chamado-juridico/robot/tasks/${taskId}`,
                    'Robô do Chamado Jurídico',
                    sourceTab,
                    (result) => {
                        _chamadoRobotToggleRunning(false);
                        const filled = result?.filled?.length ? `Campos preenchidos: ${result.filled.join(', ')}.` : '';
                        const positional = result?.positional?.length ? ` Localizados por posição (confira visualmente): ${result.positional.join(', ')}.` : '';
                        const unmatched = result?.unmatched?.length ? ` Não localizei no formulário: ${result.unmatched.join(', ')}.` : '';
                        if (result?.submitted) {
                            showSuccess('Chamado Jurídico enviado com sucesso pelo Microsoft Forms!');
                            _autoTocaAppendLog(`Envio confirmado pelo Forms. ${filled}${positional}${unmatched}`, 'success');
                        } else {
                            showInfo('Preenchimento concluído. Revise, anexe os arquivos e clique em Enviar na janela do robô.');
                            _autoTocaAppendLog(`Preenchimento concluído — envio pendente de revisão. ${filled}${positional}${unmatched}`, 'warning');
                        }
                        loadChamadoJuridicoHistory();
                    },
                    (errMsg) => {
                        _chamadoRobotToggleRunning(false);
                        showError(errMsg || 'Erro no robô do Chamado Jurídico.');
                        _autoTocaAppendLog(`Robô falhou: ${errMsg || 'erro desconhecido'}`, 'error');
                    },
                    (pct, step) => _chamadoRobotSetProgress(pct, step)
                );
            } catch (error) {
                _chamadoRobotToggleRunning(false);
                showError(error.message || 'Erro ao iniciar o robô.');
                _autoTocaAppendLog(`Robô não iniciou: ${error.message || 'erro desconhecido'}`, 'error');
            }
        }
        async function loadIntegrationConfig() {
            const response = await fetch(`${API_BASE}/config/integrations`);
            if (response.ok) integrationConfig = await response.json();
        }

        async function loadUpdateSourceConfig() {
            const response = await fetch(`${API_BASE}/config/update-source`);
            if (response.ok) updateSourceConfig = await response.json();
        }

        async function loadStatusConfig() {
            const response = await fetch(`${API_BASE}/config/status`);
            if (response.ok) statusConfig = await response.json();
        }

        async function loadUserProfile() {
            const response = await fetch(`${API_BASE}/config/profile`);
            if (response.ok) userProfile = await response.json();
            await renderDashboardGreeting();
        }

        async function loadPositions() {
            const response = await fetch(`${API_BASE}/cargos`);
            if (response.ok) cachedPositions = await response.json();
        }

        function renderSettings() {
            document.getElementById('universalGreen').value = Number(statusConfig.universal.green_days || 7);
            document.getElementById('universalYellow').value = Number(statusConfig.universal.yellow_days || 14);

            const rulesHtml = (statusConfig.rules || []).length
                ? statusConfig.rules.map(rule => `<div class="rule-item"><div><strong>${escapeHtml(rule.position)}</strong><div style="font-size:12px;color:#6b7280;">Em dia: ${rule.green_days}d • Atenção: ${rule.yellow_days}d</div></div><button class="btn btn-danger btn-small" onclick="deleteStatusRule(${rule.id})"><i class="fas fa-trash"></i></button></div>`).join('')
                : '<div style="color:#6b7280;">Nenhuma regra específica cadastrada.</div>';
            document.getElementById('statusRulesList').innerHTML = rulesHtml;

            const form = document.getElementById('userProfileForm');
            form.full_name.value = userProfile?.full_name || '';
            form.nickname.value = userProfile?.nickname || '';
            form.position.value = userProfile?.position || '';
            form.email.value = userProfile?.email || '';
            form.phone.value = formatPhone(userProfile?.phone || '');
            form.boss_name.value = userProfile?.boss_name || '';
            form.boss_email.value = userProfile?.boss_email || '';
            const preview = document.getElementById('profilePhotoPreview');
            if (userProfile?.photo_url) {
                preview.src = userProfile.photo_url;
                preview.style.display = 'block';
            } else {
                preview.style.display = 'none';
                preview.removeAttribute('src');
            }
            
            // Mostrar botão de excluir apenas se usuário existe
            const deleteBtn = document.getElementById('deleteUserBtn');
            if (deleteBtn) {
                deleteBtn.style.display = userProfile ? 'inline-block' : 'none';
            }

            document.getElementById('tavilyApiKey').value = '';
            document.getElementById('openrouterApiKey').value = '';
            document.getElementById('openrouterModel').value = integrationConfig?.openrouter_model || 'stepfun/step-3.5-flash:free';
            document.getElementById('openrouterSiteUrl').value = integrationConfig?.openrouter_site_url || 'http://localhost';
            document.getElementById('openrouterAppName').value = integrationConfig?.openrouter_app_name || 'TocaDoCoelho';
            document.getElementById('tavilyKeyStatus').textContent = integrationConfig?.tavily_configured
                ? `Configurada (${integrationConfig?.tavily_key_preview || '***'})`
                : 'Não configurada';
            document.getElementById('openrouterKeyStatus').textContent = integrationConfig?.openrouter_configured
                ? `Configurada (${integrationConfig?.openrouter_key_preview || '***'})`
                : 'Não configurada';
            // iToca SAI fields
            document.getElementById('itocaSaiApiKey').value = '';
            document.getElementById('itocaSaiTemplateId').value = integrationConfig?.itoca_sai_template_id || '69ac3c87024adc2d2bdc19f5';
            document.getElementById('itocaSaiBaseUrl').value = integrationConfig?.itoca_sai_base_url || 'https://sai-library.saiapplications.com';
            document.getElementById('itocaSaiKeyStatus').textContent = integrationConfig?.itoca_sai_configured
                ? `Configurada (${integrationConfig?.itoca_sai_key_preview || '***'})`
                : 'Não configurada';

            document.getElementById('updateGithubOwner').value = updateSourceConfig?.github_owner || '';
            document.getElementById('updateGithubRepo').value = updateSourceConfig?.github_repo || '';
            document.getElementById('updateGithubToken').value = '';
            document.getElementById('updateGithubTokenStatus').textContent = updateSourceConfig?.github_token_configured
                ? `Configurado (${updateSourceConfig?.github_token_preview || '***'})`
                : 'Não configurado — verificações usam o limite anônimo do GitHub (60/hora).';
            document.getElementById('currentVersionLabel').textContent = `Versão instalada: ${updateSourceConfig?.current_version || '-'}`;
            const updateResult = document.getElementById('updateCheckResult');
            if (updateResult) updateResult.textContent = '';
        }

        async function saveIntegrationConfig(event) {
            event.preventDefault();
            const payload = {
                tavily_api_key: document.getElementById('tavilyApiKey').value.trim(),
                openrouter_api_key: document.getElementById('openrouterApiKey').value.trim(),
                openrouter_model: document.getElementById('openrouterModel').value.trim(),
                openrouter_site_url: document.getElementById('openrouterSiteUrl').value.trim(),
                openrouter_app_name: document.getElementById('openrouterAppName').value.trim(),
                itoca_sai_api_key: document.getElementById('itocaSaiApiKey').value.trim(),
                itoca_sai_template_id: document.getElementById('itocaSaiTemplateId').value.trim(),
                itoca_sai_base_url: document.getElementById('itocaSaiBaseUrl').value.trim()
            };

            const response = await fetch(`${API_BASE}/config/integrations`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (response.ok) {
                showSuccess('Integrações salvas com sucesso!');
                await loadIntegrationConfig();
                renderSettings();
            } else {
                const result = await response.json().catch(() => ({}));
                showError(result.error || 'Erro ao salvar integrações');
            }
        }

        async function saveUpdateSourceConfig(event) {
            event.preventDefault();
            const payload = {
                github_owner: document.getElementById('updateGithubOwner').value.trim(),
                github_repo: document.getElementById('updateGithubRepo').value.trim(),
                github_token: document.getElementById('updateGithubToken').value.trim()
            };

            const response = await fetch(`${API_BASE}/config/update-source`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (response.ok) {
                showSuccess('Fonte de atualização salva!');
                await loadUpdateSourceConfig();
                renderSettings();
            } else {
                const result = await response.json().catch(() => ({}));
                showError(result.error || 'Erro ao salvar fonte de atualização');
            }
        }

        async function checkForUpdatesOnStartup() {
            try {
                const resp = await fetch(`${API_BASE}/config/startup-update-check`);
                if (!resp.ok) return;
                const result = await resp.json().catch(() => ({}));
                if (!result.update_available) return;
                window._pendingUpdate = result.installer_url
                    ? { url: result.installer_url, name: result.installer_name || 'TocaDoCoelho-Setup.exe' }
                    : null;
                _showStartupUpdateModal(result);
            } catch (_) {}
        }

        function _showStartupUpdateModal(result) {
            const existingId = 'startupUpdateModal';
            if (document.getElementById(existingId)) return;

            const releaseUrl = result.html_url || '';
            const releaseLinkHtml = releaseUrl
                ? `<a href="${releaseUrl}" target="_blank" rel="noopener noreferrer" style="color:#059669;font-size:12px;">Ver release no GitHub ↗</a>`
                : '';
            const notes = (result.release_notes || '').trim();
            const notesHtml = notes
                ? `<div style="margin-top:10px;max-height:120px;overflow-y:auto;background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:8px 10px;font-size:12px;color:#6b7280;white-space:pre-wrap;">${escapeHtml(notes)}</div>`
                : '';
            const hasInstaller = !!(result.installer_url);

            const overlay = document.createElement('div');
            overlay.id = existingId;
            overlay.style.cssText = 'position:fixed;inset:0;z-index:99999;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.45);';
            overlay.innerHTML = `
                <div style="background:#fff;border-radius:14px;padding:28px 28px 22px;max-width:440px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,0.25);font-family:inherit;">
                    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;">
                        <img src="/images/coelho-correndo.webp" alt="" style="height:38px;width:auto;flex-shrink:0;">
                        <div>
                            <div style="font-size:16px;font-weight:700;color:#111827;">Nova versão disponível!</div>
                            <div style="font-size:13px;color:#6b7280;margin-top:2px;">
                                Versão <strong style="color:#059669;">${escapeHtml(result.latest_version || '')}</strong>
                                &nbsp;·&nbsp; atual: ${escapeHtml(result.current_version || '')}
                            </div>
                        </div>
                    </div>
                    ${notesHtml}
                    <div style="margin-top:12px;">${releaseLinkHtml}</div>
                    <label style="display:flex;align-items:center;gap:8px;margin-top:16px;font-size:13px;color:#6b7280;cursor:pointer;">
                        <input type="checkbox" id="startupUpdateSnoozeCheck" style="width:15px;height:15px;accent-color:#059669;">
                        Não perguntar nos próximos 5 dias
                    </label>
                    <div style="display:flex;gap:10px;margin-top:18px;">
                        ${hasInstaller
                            ? `<button id="startupUpdateYesBtn" style="flex:1;padding:9px 0;background:#059669;color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;">Atualizar agora</button>`
                            : `<button id="startupUpdateYesBtn" style="flex:1;padding:9px 0;background:#6b7280;color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;" disabled title="Esta release não possui instalador .exe">Sem instalador</button>`
                        }
                        <button id="startupUpdateNoBtn" style="flex:1;padding:9px 0;background:#f3f4f6;color:#374151;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;">Não agora</button>
                    </div>
                </div>
            `;
            document.body.appendChild(overlay);

            const closeModal = async (doSnooze) => {
                if (doSnooze) {
                    try { await fetch(`${API_BASE}/config/snooze-update`, { method: 'POST' }); } catch (_) {}
                }
                overlay.remove();
            };

            document.getElementById('startupUpdateNoBtn').addEventListener('click', () => {
                const snooze = document.getElementById('startupUpdateSnoozeCheck')?.checked;
                closeModal(snooze);
            });

            if (hasInstaller) {
                document.getElementById('startupUpdateYesBtn').addEventListener('click', () => {
                    overlay.remove();
                    switchTab(null, 'configuracoes');
                    // skipConfirm=true: o popup de startup já é a confirmação do usuário,
                    // não faz sentido pedir confirmação novamente 400ms depois.
                    setTimeout(() => downloadAndInstallUpdate({ skipConfirm: true }), 800);
                });
            }
        }

        async function checkForUpdates() {
            const container = document.getElementById('updateCheckResult');
            if (container) container.textContent = 'Verificando releases no GitHub...';

            try {
                const response = await fetch(`${API_BASE}/config/check-updates`);
                const result = await response.json().catch(() => ({}));

                if (!response.ok) {
                    const errorMsg = result.error || result.message || 'Falha ao verificar atualizações.';
                    if (container) container.textContent = errorMsg;
                    showError(errorMsg);
                    return;
                }

                const commitsAhead = Number(result.commits_ahead || 0);
                const branch = result.github_branch || '';
                const compareUrl = result.compare_html_url || result.branch_html_url || '';
                const commitsList = Array.isArray(result.commits_ahead_list) ? result.commits_ahead_list : [];
                const commitsPreviewHtml = commitsList.length
                    ? `<ul style="margin:6px 0 0 18px;padding:0;font-size:0.9em;">${commitsList.map(c => `<li><code>${escapeHtml(c.sha || '')}</code> ${escapeHtml(c.message || '')}</li>`).join('')}</ul>`
                    : '';
                const compareLinkHtml = compareUrl
                    ? ` <a href="${compareUrl}" target="_blank" rel="noopener noreferrer">Ver no GitHub</a>`
                    : '';

                if (result.update_available) {
                    const releaseUrl = result.html_url || '';
                    const releaseLinkHtml = releaseUrl
                        ? ` <a href="${releaseUrl}" target="_blank" rel="noopener noreferrer">Abrir release</a>`
                        : '';
                    const extraAheadHtml = commitsAhead > 0
                        ? `<div style="margin-top:6px;">Além disso, há <strong>${commitsAhead}</strong> commit(s) na branch <code>${escapeHtml(branch)}</code> após esse release.${compareLinkHtml}${commitsPreviewHtml}</div>`
                        : '';
                    window._pendingUpdate = result.installer_url
                        ? { url: result.installer_url, name: result.installer_name || 'TocaDoCoelho-Setup.exe' }
                        : null;
                    const autoInstallHtml = result.installer_url
                        ? `<div style="margin-top:10px;"><button class="btn btn-primary btn-small" id="autoUpdateBtn" onclick="downloadAndInstallUpdate()"><i class="fas fa-download"></i> Baixar e instalar atualização</button></div>`
                        : `<div style="margin-top:8px; color:#9ca3af; font-size:12px;">Esta release não tem instalador (.exe) anexado — instalação automática indisponível.</div>`;
                    if (container) {
                        container.innerHTML = `Nova versão disponível: <strong>${escapeHtml(result.latest_version || '')}</strong> (atual: ${escapeHtml(result.current_version || '')}).${releaseLinkHtml}${extraAheadHtml}${autoInstallHtml}`;
                    }
                    showSuccess(`Nova versão disponível: ${result.latest_version}`);
                } else if (commitsAhead > 0) {
                    if (container) {
                        container.innerHTML = `Você está na versão do último release (<strong>${escapeHtml(result.current_version || '')}</strong>), mas há <strong>${commitsAhead}</strong> commit(s) novo(s) na branch <code>${escapeHtml(branch)}</code> ainda não publicado(s) como release.${compareLinkHtml}${commitsPreviewHtml}`;
                    }
                    showSuccess(`${commitsAhead} commit(s) novo(s) na branch ${branch}.`);
                } else if (result.commits_check_ok === false) {
                    const checkMsg = result.commits_check_error || 'Não foi possível verificar os commits da branch. Tente novamente em alguns minutos.';
                    if (container) {
                        container.innerHTML = `<span style="color:#b45309;"><strong>⚠️ Verificação incompleta.</strong></span> ${escapeHtml(checkMsg)} O release publicado está em dia, mas não foi possível confirmar se há commits novos na branch <code>${escapeHtml(branch)}</code>.${compareLinkHtml}`;
                    }
                    showError('Não foi possível verificar atualizações da branch. Tente novamente.');
                } else {
                    if (container) {
                        container.textContent = `Você já está na versão mais recente (${result.current_version || ''}).`;
                    }
                    showSuccess('Você já está na versão mais recente.');
                }
            } catch (error) {
                if (container) container.textContent = 'Erro ao verificar atualizações.';
                showError('Erro ao verificar atualizações.');
            }
        }

        function _updSetProgress(pct, step) {
            const bar = document.getElementById('updProgressBar');
            const stepEl = document.getElementById('updProgressStep');
            const pctEl = document.getElementById('updProgressPct');
            if (bar) bar.style.width = Math.max(5, pct) + '%';
            if (stepEl) stepEl.textContent = step || '';
            if (pctEl) pctEl.textContent = Math.round(pct) + '%';
        }

        async function downloadAndInstallUpdate(opts) {
            const info = window._pendingUpdate;
            if (!info || !info.url) { showError('Nenhum instalador disponível para esta release.'); return; }
            if (!(opts && opts.skipConfirm)) {
                if (!await uiConfirm('O Toca do Coelho vai baixar a nova versão e abrir o instalador. O aplicativo será fechado automaticamente para concluir a atualização e reaberto ao final. Deseja continuar?', 'Atualizar aplicativo')) return;
            }

            const btn = document.getElementById('autoUpdateBtn');
            if (btn) btn.disabled = true;
            const container = document.getElementById('updateCheckResult');
            if (container) {
                container.innerHTML = `
                    <div id="updProgressStep" style="font-size:13px;color:#6b7280;margin-bottom:8px;">Iniciando download...</div>
                    <div style="position:relative;background:#d1fae5;border-radius:99px;height:12px;overflow:visible;margin:0 18px 6px 0;">
                        <div id="updProgressBar" style="position:relative;height:100%;width:5%;background:linear-gradient(90deg,#059669,#10b981,#34d399);border-radius:99px;transition:width .5s ease;">
                            <img src="/images/coelho-correndo.webp" class="coelho-run" alt="">
                        </div>
                    </div>
                    <div id="updProgressPct" style="font-size:11px;color:#6b7280;text-align:right;">5%</div>
                `;
            }

            try {
                const startResp = await fetch(`${API_BASE}/config/download-update`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ installer_url: info.url, installer_name: info.name })
                });
                const startData = await startResp.json().catch(() => ({}));
                if (!startResp.ok || !startData.task_id) {
                    throw new Error(startData.error || 'Falha ao iniciar o download.');
                }

                const taskId = startData.task_id;
                let task = {};
                while (true) {
                    await new Promise(r => setTimeout(r, 800));
                    const pollResp = await fetch(`${API_BASE}/config/update-tasks/${taskId}`);
                    task = await pollResp.json().catch(() => ({}));
                    _updSetProgress(Number(task.progress || 5), task.step || 'Baixando...');
                    if (task.status === 'done' || task.status === 'error') break;
                }

                if (task.status === 'error') {
                    throw new Error(task.error || 'Falha no download da atualização.');
                }

                _updSetProgress(100, 'Download concluído. Abrindo o instalador...');
                const installResp = await fetch(`${API_BASE}/config/install-update`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ installer_path: task.installer_path })
                });
                const installData = await installResp.json().catch(() => ({}));
                if (!installResp.ok) {
                    throw new Error(installData.error || 'Falha ao iniciar o instalador.');
                }

                if (container) {
                    container.innerHTML = `<div style="color:#059669;"><strong>Instalador iniciado.</strong> O Toca do Coelho vai fechar agora para concluir a atualização. Siga o assistente de instalação — o app reabrirá ao final.</div>`;
                }
                showSuccess('Instalador iniciado. O aplicativo será encerrado.');
            } catch (error) {
                if (btn) btn.disabled = false;
                if (container) {
                    container.innerHTML = `<span style="color:#b45309;"><strong>⚠️ ${escapeHtml(error.message || 'Erro ao atualizar.')}</strong></span>`;
                }
                showError(error.message || 'Erro ao baixar/instalar a atualização.');
            }
        }

        async function saveUniversalStatus(event) {
            event.preventDefault();
            const green_days = Number(document.getElementById('universalGreen').value);
            const yellow_days = Number(document.getElementById('universalYellow').value);
            const response = await fetch(`${API_BASE}/config/status/universal`, {
                method: 'PUT', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ green_days, yellow_days })
            });
            if (response.ok) {
                showSuccess('Regra universal atualizada!');
                await loadStatusConfig();
                renderSettings();
                loadDashboard();
            } else showError('Erro ao salvar regra universal');
        }

        function openStatusRuleModal() {
            const options = ['<option value="">Selecione...</option>', ...cachedPositions.map(p => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`)].join('\n');
            document.getElementById('rulePosition').innerHTML = options;
            document.getElementById('ruleGreen').value = Number(statusConfig.universal.green_days || 7);
            document.getElementById('ruleYellow').value = Number(statusConfig.universal.yellow_days || 14);
            document.getElementById('statusRuleModal').classList.add('active');
        }

        function closeStatusRuleModal() {
            document.getElementById('statusRuleModal').classList.remove('active');
        }

        async function saveStatusRule(event) {
            event.preventDefault();
            const payload = {
                position: document.getElementById('rulePosition').value,
                green_days: Number(document.getElementById('ruleGreen').value),
                yellow_days: Number(document.getElementById('ruleYellow').value)
            };
            const response = await fetch(`${API_BASE}/config/status/rules`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
            });
            if (response.ok) {
                closeStatusRuleModal();
                showSuccess('Regra por cargo salva!');
                await loadStatusConfig();
                renderSettings();
                loadDashboard();
            } else showError('Erro ao salvar regra por cargo');
        }

        async function deleteStatusRule(ruleId) {
            const response = await fetch(`${API_BASE}/config/status/rules/${ruleId}`, { method: 'DELETE' });
            if (response.ok) {
                showSuccess('Regra removida');
                await loadStatusConfig();
                renderSettings();
                loadDashboard();
            } else showError('Erro ao remover regra');
        }

        async function saveUserProfile(event) {
            event.preventDefault();
            const formData = new FormData(document.getElementById('userProfileForm'));
            if (!formData.get('photo')?.name && !userProfile?.photo_url) {
                showError('Foto é obrigatória no cadastro do usuário');
                return;
            }
            const response = await fetch(`${API_BASE}/config/profile`, { method: 'POST', body: formData });
            if (response.ok) {
                showSuccess('Cadastro do usuário salvo!');
                await loadUserProfile();
                renderSettings();
            } else {
                const payload = await response.json().catch(() => ({}));
                showError(payload.error || 'Erro ao salvar usuário');
            }
        }

        async function deleteUserProfile() {
            if (!await uiConfirm('Tem certeza que deseja excluir o usuário cadastrado? Esta ação não pode ser desfeita.')) {
                return;
            }
            
            try {
                const response = await fetch(`${API_BASE}/config/profile`, { method: 'DELETE' });
                if (response.ok) {
                    showSuccess('Usuário excluído com sucesso!');
                    await loadUserProfile();
                    renderSettings();
                    // Atualizar dashboard para remover saudação personalizada
                    if (typeof renderDashboardGreeting === 'function') {
                        await renderDashboardGreeting();
                    }
                } else {
                    const payload = await response.json().catch(() => ({}));
                    showError(payload.error || 'Erro ao excluir usuário');
                }
            } catch (error) {
                showError('Erro ao excluir usuário');
            }
        }

        // Load Dashboard
        let dashboardSortField = 'status';
        let dashboardSortOrder = 'desc';
        let clientsSortField = 'name';
        let clientsSortOrder = 'asc';
        let dashboardCompanyFilter = '';
        let dashboardPositionFilter = '';
        let dashboardTargetFilter = '';
        let dashboardContactSearch = '';
        let clientsCompanyFilter = '';
        let clientsPositionFilter = '';
        let clientsNameSearch = '';
        let dashboardArchivedExpanded = false;
        let agendaCurrentMonth = new Date(new Date().getFullYear(), new Date().getMonth(), 1);



        function uniqueValues(items, key) {
            return [...new Set(items.map(i => (i[key] || '').trim()).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'pt-BR'));
        }

        function isArchivedClient(client) {
            return Number(client?.is_archived) === 1 || !String(client?.company || '').trim();
        }

        function renderFilters(prefix, allClients, currentCompany, currentPosition) {
            const companies = uniqueValues(allClients, 'company');
            const positions = uniqueValues(allClients, 'position');
            const currentSearch = prefix === 'Clients' ? clientsNameSearch : '';
            const dashboardSearch = prefix === 'Dashboard' ? dashboardContactSearch : '';

            let html = '<div class="filters-bar">';
            html += '<div class="filters-row">';
            if (prefix === 'Dashboard') {
                html += `<div class="filter-group"><label class="filter-label">Pesquisa</label><input id="dashboardSearchInput" class="filter-input" type="text" placeholder="Pesquisar contato" value="${escapeHtml(dashboardSearch)}" oninput="setDashboardContactSearch(this.value)"></div>`;
            }
            html += `<div class="filter-group"><label class="filter-label">Cliente</label><select class="filter-select" onchange="set${prefix}Filter('company', this.value)"><option value="">Todos os clientes</option>${companies.map(c=>`<option value="${escapeHtml(c)}" ${c===currentCompany?'selected':''}>${escapeHtml(c)}</option>`).join('')}</select></div>`;
            if (prefix === 'Clients') {
                html += `<div class="filter-group"><label class="filter-label">Pesquisar Nome</label><input class="filter-input" type="text" placeholder="Digite o nome do cliente" value="${escapeHtml(currentSearch)}" oninput="setClientsNameSearch(this.value)"></div>`;
            }
            html += `<div class="filter-group"><label class="filter-label">Cargo</label><select class="filter-select" onchange="set${prefix}Filter('position', this.value)"><option value="">Todos os cargos</option>${positions.map(p=>`<option value="${escapeHtml(p)}" ${p===currentPosition?'selected':''}>${escapeHtml(p)}</option>`).join('')}</select></div>`;
            if (prefix === 'Dashboard') {
                html += `<div class="filter-group"><label class="filter-label">Target</label><select class="filter-select" onchange="setDashboardFilter('target', this.value)"><option value="">Todos</option><option value="target" ${dashboardTargetFilter==='target'?'selected':''}>Target</option><option value="nao_target" ${dashboardTargetFilter==='nao_target'?'selected':''}>Não Target</option></select></div>`;
            }
            html += '</div>';
            html += `<button class="filter-clear-btn" onclick="clear${prefix}Filters()"><i class="fas fa-broom"></i> Limpar filtros</button>`;
            html += '</div>';
            return html;
        }


        function clearDashboardFilters() {
            dashboardCompanyFilter = '';
            dashboardPositionFilter = '';
            dashboardTargetFilter = '';
            dashboardContactSearch = '';
            // Re-renderiza a barra de filtros (reseta dropdowns e campo de busca) sem buscar no servidor
            _renderDashboardFilters();
            _renderDashboardTable();
        }

        function setDashboardFilter(type, value) {
            if (type === 'company') dashboardCompanyFilter = value;
            if (type === 'position') dashboardPositionFilter = value;
            if (type === 'target') dashboardTargetFilter = value;
            // Só re-renderiza a tabela — a barra de filtros não é destruída (sem perda de foco)
            _renderDashboardTable();
        }

        function setDashboardContactSearch(value) {
            dashboardContactSearch = (value || '').trimStart();
            // Só re-renderiza a tabela — o input de busca não é destruído (sem perda de foco)
            _renderDashboardTable();
        }


        function clearClientsFilters() {
            clientsCompanyFilter = '';
            clientsPositionFilter = '';
            clientsNameSearch = '';
            loadClients();
        }

        function setClientsFilter(type, value) {
            if (type === 'company') clientsCompanyFilter = value;
            if (type === 'position') clientsPositionFilter = value;
            loadClients();
        }

        function setClientsNameSearch(value) {
            clientsNameSearch = value || '';
            loadClients();
        }

        async function loadWeekSummary() {
            try {
                const response = await fetch(`${API_BASE}/agenda/semana-atual-count`);
                const result = await response.json();
                return result.total || 0;
            } catch {
                return 0;
            }
        }



        async function openWeekCommitmentsModal() {
            try {
                const today = new Date();
                const day = (today.getDay() + 6) % 7;
                const start = new Date(today);
                start.setDate(today.getDate() - day);
                const end = new Date(start);
                end.setDate(start.getDate() + 6);
                const startDate = start.toISOString().slice(0,10);
                const endDate = end.toISOString().slice(0,10);
                const response = await fetch(`${API_BASE}/agenda?start_date=${startDate}&end_date=${endDate}`);
                const items = response.ok ? await response.json() : [];
                let html = `<div class="modal active" id="weekCommitmentsModal" onclick="if(event.target===this) closeWeekCommitmentsModal()">`;
                html += '<div class="modal-content" style="max-width:700px;">';
                html += '<h2 style="color:#047857; margin-bottom:8px;">Compromissos da Semana</h2>';
                html += `<p style="color:#6b7280; margin-bottom:14px;">Período: ${formatDateBr(startDate)} a ${formatDateBr(endDate)}</p>`;
                if (!items.length) {
                    html += '<div class="empty-state" style="padding:14px 8px;"><p>Nenhum compromisso nesta semana.</p></div>';
                } else {
                    html += '<div style="max-height:420px; overflow:auto;">';
                    items.forEach(item => {
                        html += `<div class="history-item" style="margin-bottom:10px;"><div class="history-meta">${formatDateBr(item.due_date)}${item.due_time ? ' ' + escapeHtml(item.due_time) : ''} • ${escapeHtml(item.client_name || '-')}${item.client_company ? ` (${escapeHtml(item.client_company)})` : ''}</div><div>${escapeHtml(item.title || item.notes || '-')}</div></div>`;
                    });
                    html += '</div>';
                }
                html += '<div style="margin-top:16px; text-align:right;"><button class="btn btn-secondary" onclick="closeWeekCommitmentsModal()">Fechar</button></div>';
                html += '</div></div>';
                document.body.insertAdjacentHTML('beforeend', html);
            } catch (error) {
                showError('Erro ao carregar compromissos da semana');
            }
        }

        function closeWeekCommitmentsModal() { const m = document.getElementById('weekCommitmentsModal'); if (m) m.remove(); }

        async function renderDashboardGreeting() {
            const greetingEl = document.getElementById('dashboardGreeting');
            if (!greetingEl) return;

            try {
                const response = await fetch(`${API_BASE}/config/profile`);
                const profile = await response.json();
                
                if (profile && profile.nickname && profile.photo_url) {
                    const photoHtml = `<img src="${profile.photo_url}" style="width: 44px; height: 44px; border-radius: 50%; object-fit: cover; border: 2px solid rgba(226,223,213,.5);">`;
                    greetingEl.innerHTML = `<div style="display:flex; align-items:center; gap:10px;"><span style="font-size: 18px; font-weight: 700; color: #e2dfd5;">Olá ${profile.nickname}</span>${photoHtml}</div>`;
                } else {
                    greetingEl.innerHTML = `<span style="font-size: 18px; font-weight: 700; color: #e2dfd5;">Olá</span>`;
                }
            } catch (error) {
                greetingEl.innerHTML = `<span style="font-size: 18px; font-weight: 700; color: #e2dfd5;">Olá</span>`;
            }
        }

        async function updateWeekCommitmentsBell() {
            const bellEl = document.getElementById('weekCommitmentsBell');
            if (!bellEl) return;
            const weekCount = await loadWeekSummary();
            bellEl.classList.toggle('has-updates', weekCount > 0);
            bellEl.title = weekCount > 0
                ? `Você tem ${weekCount} compromisso(s) nesta semana`
                : 'Nenhum compromisso nesta semana';
        }

