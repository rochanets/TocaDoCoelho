        // =====================================================
        // Account Planning — mapeamento de decisores com IA (Bloco 4)
        // Busca cargos-chave de uma empresa via Tavily (resultados públicos
        // indexados do LinkedIn — sem scraping) e permite salvar como contato.
        // =====================================================

        let _apState = { candidates: [], company: '', segment: '', country: '' };

        function _apEnsureBunnyStyle() {
            if (document.getElementById('iata-bunny-style')) return;
            const style = document.createElement('style');
            style.id = 'iata-bunny-style';
            style.textContent = `
                @keyframes iata-bunny-hop { 0%,100%{transform:translateY(-50%) scaleY(1)} 50%{transform:translateY(-70%) scaleY(.85)} }
                @keyframes iata-paw-fade { 0%,100%{opacity:.25} 50%{opacity:.7} }
                .iata-bunny { position:absolute; right:-14px; top:50%; transform:translateY(-50%); font-size:18px; line-height:1; animation:iata-bunny-hop .5s ease-in-out infinite; pointer-events:none; }
                .iata-paw { display:inline-block; font-size:10px; animation:iata-paw-fade 1s ease-in-out infinite; }
                .iata-paw:nth-child(2){animation-delay:.2s} .iata-paw:nth-child(3){animation-delay:.4s}
            `;
            document.head.appendChild(style);
        }

        async function initAccountPlanning() {
            _apEnsureBunnyStyle();
            // Pré-preenchimento quando aberto a partir de uma conta existente
            if (window._apPrefillCompany) {
                const input = document.getElementById('apCompanyInput');
                if (input) input.value = window._apPrefillCompany;
                window._apPrefillCompany = null;
            }
            try {
                const segs = await (await fetch(`${API_BASE}/account-planning/segments`)).json();
                const dl = document.getElementById('apSegmentOptions');
                if (dl) dl.innerHTML = (segs || []).map(s => `<option value="${escapeHtml(s)}">`).join('');
            } catch (e) { /* sugestões são opcionais */ }
            try {
                const runs = await (await fetch(`${API_BASE}/account-planning/runs`)).json();
                const sel = document.getElementById('apRecentRuns');
                if (sel) {
                    sel.innerHTML = '<option value="">Buscas recentes...</option>' + (runs || []).map(r =>
                        `<option value="${r.id}">${escapeHtml(r.company)}${r.segment ? ' · ' + escapeHtml(r.segment) : ''} (${(r.created_at || '').slice(0, 10)})</option>`
                    ).join('');
                }
            } catch (e) { /* histórico é opcional */ }
        }

        function openAccountPlanningFor(company) {
            window._apPrefillCompany = company || null;
            switchTab(null, 'gestao-conta');
            switchGestaoContaSubmodule('planning');
        }

        function _apSetProgress(pct, step) {
            const bar = document.getElementById('apProgressBar');
            const stepEl = document.getElementById('apProgressStep');
            const pctEl = document.getElementById('apProgressPct');
            if (bar) bar.style.width = Math.max(5, pct) + '%';
            if (stepEl) stepEl.textContent = step || '';
            if (pctEl) pctEl.textContent = Math.round(pct) + '%';
        }

        async function startAccountPlanningSearch() {
            const company = (document.getElementById('apCompanyInput')?.value || '').trim();
            const segment = (document.getElementById('apSegmentInput')?.value || '').trim();
            const country = (document.getElementById('apCountryInput')?.value || '').trim();
            if (!company) { showError('Informe o nome da empresa.'); return; }
            const progressArea = document.getElementById('apProgressArea');
            const resultsEl = document.getElementById('apResultsContent');
            if (resultsEl) resultsEl.innerHTML = '';
            if (progressArea) progressArea.style.display = 'block';
            _apSetProgress(5, 'Iniciando busca de decisores...');
            try {
                const resp = await fetch(`${API_BASE}/account-planning/search`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ company, segment, country })
                });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(payload.error || 'Erro ao iniciar a busca.');
                BgTaskManager.register(
                    payload.task_id,
                    `${API_BASE}/account-planning/tasks/${payload.task_id}`,
                    `Account Planning — ${company}`,
                    'gestao-conta',
                    (result) => {
                        if (progressArea) progressArea.style.display = 'none';
                        renderAccountPlanningResults(result);
                        initAccountPlanning();
                    },
                    (errMsg) => {
                        if (progressArea) progressArea.style.display = 'none';
                        showError(errMsg || 'Erro na busca de decisores.');
                    },
                    (pct, step) => _apSetProgress(pct, step)
                );
            } catch (error) {
                if (progressArea) progressArea.style.display = 'none';
                showError(error.message || 'Erro ao iniciar a busca.');
            }
        }

        async function loadAccountPlanningRun(runId) {
            try {
                const resp = await fetch(`${API_BASE}/account-planning/runs/${runId}`);
                const payload = await resp.json();
                if (!resp.ok) throw new Error(payload.error || 'Erro ao carregar busca.');
                const setVal = (id, v) => { const el = document.getElementById(id); if (el && v != null) el.value = v; };
                setVal('apCompanyInput', payload.company);
                setVal('apSegmentInput', payload.segment);
                setVal('apCountryInput', payload.country);
                renderAccountPlanningResults(payload);
            } catch (e) {
                showError(e.message || 'Erro ao carregar busca.');
            }
        }

        function renderAccountPlanningResults(payload) {
            _apState = {
                candidates: (payload && payload.candidates) || [],
                company: (payload && payload.company) || '',
                segment: (payload && payload.segment) || '',
                country: (payload && payload.country) || ''
            };
            const el = document.getElementById('apResultsContent');
            if (!el) return;
            if (!_apState.candidates.length) {
                el.innerHTML = `<div class="card toca-text" style="padding:18px;">Nenhum decisor com presença pública no LinkedIn foi encontrado para "<b>${escapeHtml(_apState.company)}</b>". Tente variar o nome da empresa.</div>`;
                return;
            }
            const rows = _apState.candidates.map((cand, idx) => _apRowHtml(cand, idx)).join('');
            el.innerHTML = `
                <div class="card" style="padding:14px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; flex-wrap:wrap; gap:8px;">
                        <h3 class="toca-text-strong" style="margin:0; font-size:15px;">Decisores encontrados — ${escapeHtml(_apState.company)}</h3>
                        <small class="toca-text-muted">Fotos são aproximadas (busca por nome+empresa) — confirme antes de salvar.</small>
                    </div>
                    <div id="apRowsContainer">${rows}</div>
                </div>`;
        }

        function _apRowHtml(cand, idx) {
            const photo = cand.photo_url
                ? `<img src="${escapeHtml(cand.photo_url)}" alt="" style="width:44px; height:44px; border-radius:50%; object-fit:cover;" onerror="this.outerHTML='<div style=&quot;width:44px;height:44px;border-radius:50%;background:#e5e7eb;display:flex;align-items:center;justify-content:center;&quot;>👤</div>'" title="Foto aproximada — pode não corresponder exatamente à pessoa">`
                : `<div style="width:44px; height:44px; border-radius:50%; background:#e5e7eb; display:flex; align-items:center; justify-content:center;" title="Sem foto encontrada">👤</div>`;
            let actions;
            if (cand.already_registered) {
                actions = `<span style="font-size:12px; color:#059669; font-weight:600;">✓ Já cadastrado</span>
                           <button class="btn btn-secondary btn-small" onclick="apCompleteInfos(${cand.client_id})">Ver contato</button>`;
            } else if (cand.saved_client_id) {
                actions = `<button class="btn btn-auto-mapping btn-small" onclick="apCompleteInfos(${cand.saved_client_id})"><span class="ai-star-icon">✦</span> Completar infos</button>`;
            } else {
                actions = `<button class="btn btn-primary btn-small" id="apSaveBtn_${idx}" onclick="apSaveCandidate(${idx})">Salvar</button>
                           <button class="btn btn-secondary btn-small" onclick="apDiscardCandidate(${idx})">Descartar</button>`;
            }
            return `
                <div class="ap-row" id="apRow_${idx}" style="display:flex; align-items:center; gap:12px; padding:10px 6px; border-bottom:1px solid rgba(148,163,184,.2);">
                    ${photo}
                    <div style="flex:1; min-width:180px;">
                        <div class="toca-text-strong" style="font-weight:600;">${escapeHtml(cand.name)}</div>
                        <div class="toca-text-muted" style="font-size:12px;">${escapeHtml(cand.position || cand.target)} · <span>${escapeHtml(cand.target)}</span></div>
                    </div>
                    <a href="${escapeHtml(cand.linkedin)}" target="_blank" rel="noopener" class="btn btn-secondary btn-small" title="Abrir perfil público no LinkedIn"><i class="fab fa-linkedin"></i> LinkedIn</a>
                    <div style="display:flex; gap:6px; align-items:center;" id="apActions_${idx}">${actions}</div>
                </div>`;
        }

        function apDiscardCandidate(idx) {
            // Remove só da lista em tela — não persiste (pode reaparecer em busca futura)
            document.getElementById(`apRow_${idx}`)?.remove();
        }

        async function apSaveCandidate(idx) {
            const cand = _apState.candidates[idx];
            if (!cand) return;
            const btn = document.getElementById(`apSaveBtn_${idx}`);
            if (btn) { btn.disabled = true; btn.textContent = 'Salvando...'; }
            try {
                const dupResp = await fetch(`${API_BASE}/clients/check-duplicate`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: cand.name })
                });
                const dup = await dupResp.json().catch(() => ({ matches: [] }));
                let forceCreate = false;
                if ((dup.matches || []).length) {
                    forceCreate = await uiConfirm(
                        `Já existe um contato chamado "${cand.name}". Deseja criar mesmo assim?`,
                        'Possível duplicado'
                    );
                    if (!forceCreate) { if (btn) { btn.disabled = false; btn.textContent = 'Salvar'; } return; }
                }
                const fd = new FormData();
                fd.append('name', cand.name);
                fd.append('company', _apState.company);
                fd.append('position', cand.position || cand.target);
                fd.append('linkedin', cand.linkedin);
                if (_apState.segment) fd.append('area_of_activity', _apState.segment);
                if (cand.photo_url) fd.append('autofind_photo_url', cand.photo_url);
                if (forceCreate) fd.append('force_create', '1');
                const resp = await fetch(`${API_BASE}/clientes`, { method: 'POST', body: fd });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(payload.error || 'Erro ao criar contato.');
                cand.saved_client_id = payload.id;
                showSuccess(`Contato "${cand.name}" criado!`);
                // Troca só as ações da linha — sem recarregar a lista inteira
                const actionsEl = document.getElementById(`apActions_${idx}`);
                if (actionsEl) actionsEl.innerHTML =
                    `<button class="btn btn-auto-mapping btn-small" onclick="apCompleteInfos(${payload.id})"><span class="ai-star-icon">✦</span> Completar infos</button>`;
            } catch (error) {
                showError(error.message || 'Erro ao salvar contato.');
                if (btn) { btn.disabled = false; btn.textContent = 'Salvar'; }
            }
        }

        async function apCompleteInfos(clientId) {
            // Abre o modal de edição de contato já existente com o contato carregado
            await loadClients();
            editClient(clientId);
        }
