        // =====================================================
        // Radar do Dia (Bloco 5) — painel de sugestões priorizadas na Home.
        // Categorias novas (Blocos 9-12) aparecem aqui automaticamente:
        // basta o backend inserir em daily_suggestions com um suggestion_type
        // registrado em _RADAR_TYPES.
        // =====================================================

        const _RADAR_TYPES = {
            contact_overdue:    { icon: '📞', label: 'Contato atrasado' },
            followup_overdue:   { icon: '⏰', label: 'Follow-up vencido' },
            kanban_stalled:     { icon: '🧱', label: 'Kanban parado' },
            incomplete_profile: { icon: '📝', label: 'Cadastro incompleto' },
            missing_position:   { icon: '👥', label: 'Cargo faltante' },
            map_environment:    { icon: '🗺️', label: 'Mapear ambiente' },
            context_trigger:    { icon: '📰', label: 'Gatilho de contexto' },
            birthday:           { icon: '🎂', label: 'Aniversário' },
            multithreading:     { icon: '🕸️', label: 'Risco de concentração' },
            job_change:         { icon: '🚀', label: 'Mudança de emprego' },
            whitespace:         { icon: '⬜', label: 'Oferta não explorada' },
        };

        async function loadRadarDoDia() {
            const el = document.getElementById('radarContent');
            if (!el) return;
            try {
                const resp = await fetch(`${API_BASE}/suggestions/today`);
                const items = await resp.json();
                if (!resp.ok) throw new Error(items.error || 'Erro ao carregar o Radar do Dia.');
                const active = (items || []).filter(s => !s.completed);
                const done = (items || []).filter(s => s.completed);
                if (!active.length && !done.length) {
                    el.innerHTML = '<div style="color:#9ca3af; font-size:13px;">Nenhuma sugestão para hoje — carteira em dia! 🐇</div>';
                    return;
                }
                el.innerHTML = active.map(s => _radarItemHtml(s)).join('') +
                    (done.length ? `<div style="font-size:12px; color:#9ca3af; margin-top:6px;">✅ ${done.length} sugestão(ões) concluída(s) hoje</div>` : '');
            } catch (e) {
                el.innerHTML = `<div style="color:#ef4444; font-size:13px;">${escapeHtml(e.message || 'Erro ao carregar o Radar do Dia.')}</div>`;
            }
        }

        function _radarItemHtml(s) {
            const meta = _RADAR_TYPES[s.suggestion_type] || { icon: '💡', label: s.suggestion_type };
            return `
                <div class="radar-item" style="display:flex; align-items:center; gap:10px; padding:8px 10px; border:1px solid rgba(148,163,184,.18); border-radius:10px;">
                    <span style="font-size:18px;" title="${escapeHtml(meta.label)}">${meta.icon}</span>
                    <div style="flex:1; min-width:160px; cursor:pointer;" onclick='radarAct(${s.id}, ${JSON.stringify(s.suggestion_type)}, ${JSON.stringify(s.target_data || "{}")})' title="Agir nesta sugestão">
                        <div style="font-weight:600; font-size:13.5px;">${escapeHtml(s.title)}</div>
                        <div style="font-size:12px; color:#9ca3af;">${escapeHtml(s.description || '')}</div>
                    </div>
                    <button class="btn btn-secondary btn-small" onclick="radarSnooze(${s.id})" title="Adiar para amanhã"><i class="fas fa-clock"></i></button>
                    <button class="btn btn-primary btn-small" onclick="radarComplete(${s.id})" title="Marcar como concluída"><i class="fas fa-check"></i></button>
                </div>`;
        }

        async function radarComplete(id) {
            try {
                const resp = await fetch(`${API_BASE}/suggestions/${id}/complete`, { method: 'POST' });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.error || 'Erro ao concluir sugestão.');
                }
                loadRadarDoDia();
            } catch (e) { showError(e.message); }
        }

        async function radarSnooze(id) {
            try {
                const resp = await fetch(`${API_BASE}/suggestions/${id}/snooze`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ days: 1 })
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.error || 'Erro ao adiar sugestão.');
                }
                loadRadarDoDia();
            } catch (e) { showError(e.message); }
        }

        async function radarAct(id, type, targetDataJson) {
            let data = {};
            try { data = JSON.parse(targetDataJson || '{}'); } catch (e) { /* segue com vazio */ }
            window.currentSuggestion = { id, type, data };
            if (type === 'contact_overdue' && data.client_id) {
                await openActivityModal();
                const sel = document.getElementById('clientSelect');
                if (sel) sel.value = String(data.client_id);
            } else if (type === 'incomplete_profile' && data.client_id) {
                await apCompleteInfos(data.client_id);
            } else if (type === 'followup_overdue') {
                switchTab(null, 'agenda');
            } else if (type === 'kanban_stalled') {
                switchTab(null, 'kanban');
            } else if (type === 'multithreading' && data.company) {
                openAccountPlanningFor(data.company);
            } else if (type === 'whitespace' || type === 'context_trigger' || type === 'birthday' || type === 'job_change') {
                if (typeof radarActExtended === 'function') radarActExtended(id, type, data);
            }
        }
