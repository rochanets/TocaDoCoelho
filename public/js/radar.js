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
            multithreading:     { icon: '🕸️', label: 'Risco de concentração' },
            job_change:         { icon: '🚀', label: 'Mudança de emprego' },
            whitespace:         { icon: '⬜', label: 'Oferta não explorada' },
        };

        function toggleRadarDoDia() {
            const el = document.getElementById('radarContent');
            const toggle = document.getElementById('radarToggle');
            if (!el) return;
            const showing = el.style.display !== 'none';
            el.style.display = showing ? 'none' : 'flex';
            if (toggle) toggle.textContent = showing ? 'mostrar ▾' : 'ocultar ▴';
        }

        function _radarSetBadge(count) {
            const badge = document.getElementById('radarBadge');
            if (!badge) return;
            badge.style.display = count > 0 ? '' : 'none';
            badge.textContent = count;
        }

        async function loadRadarDoDia() {
            const el = document.getElementById('radarItemsList');
            if (!el) return;
            try {
                const resp = await fetch(`${API_BASE}/suggestions/today`);
                const items = await resp.json();
                if (!resp.ok) throw new Error(items.error || 'Erro ao carregar o Radar do Dia.');
                const active = (items || []).filter(s => !s.completed);
                const done = (items || []).filter(s => s.completed);
                _radarSetBadge(active.length);
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
                if (typeof clients === 'undefined' || !clients.length) await loadClients();
                openProfileModal(data.client_id);
            } else if (type === 'incomplete_profile' && data.client_id) {
                await apCompleteInfos(data.client_id);
            } else if (type === 'followup_overdue') {
                switchTab(null, 'agenda');
            } else if (type === 'kanban_stalled') {
                switchTab(null, 'kanban');
            } else if (type === 'multithreading' && data.company) {
                openAccountPlanningFor(data.company);
            } else if (type === 'whitespace' || type === 'context_trigger' || type === 'job_change') {
                if (typeof radarActExtended === 'function') radarActExtended(id, type, data);
            }
        }

        // =====================================================
        // Pendentes de Resposta (Bloco 6) — inbound WhatsApp/Outlook
        // =====================================================

        function _inboundWaitLabel(hours) {
            if (hours == null) return '';
            if (hours < 1) return 'menos de 1h';
            if (hours < 48) return `${hours}h`;
            return `${Math.floor(hours / 24)} dias`;
        }

        async function loadInboundPending() {
            const panel = document.getElementById('inboundPanel');
            const content = document.getElementById('inboundContent');
            const badge = document.getElementById('inboundBadge');
            if (!panel || !content) return;
            try {
                const resp = await fetch(`${API_BASE}/inbound/pending`);
                const items = await resp.json();
                if (!resp.ok) throw new Error(items.error || 'erro');
                if (badge) {
                    badge.style.display = items.length ? '' : 'none';
                    badge.textContent = items.length;
                }
                if (!items.length) { panel.style.display = 'none'; return; }
                panel.style.display = '';
                content.innerHTML = items.map(it => `
                    <div style="display:flex; align-items:center; gap:10px; padding:8px 10px; border:1px solid rgba(239,68,68,.25); border-radius:10px; cursor:pointer;" onclick="inboundOpenConversation(${it.client_id}, '${it.channel}')" title="Abrir conversa com ${escapeHtml(it.name)}">
                        <span style="font-size:16px;">${it.channel === 'email' ? '📧' : '📱'}</span>
                        <div style="flex:1; min-width:160px;">
                            <div style="font-weight:600; font-size:13.5px;">${escapeHtml(it.name)}${it.company ? ' · ' + escapeHtml(it.company) : ''}
                                <span style="color:#ef4444; font-weight:700; font-size:12px;"> aguardando há ${_inboundWaitLabel(it.waiting_hours)}</span>
                            </div>
                            <div style="font-size:12px; color:#9ca3af;">${escapeHtml(it.preview || '')}</div>
                        </div>
                        <button class="btn btn-primary btn-small" onclick="event.stopPropagation(); inboundRespond(${it.id})" title="Marcar como respondido"><i class="fas fa-check"></i> Respondi</button>
                    </div>`).join('');
                // Métrica de tempo de resposta (mediana 30 dias)
                fetch(`${API_BASE}/inbound/metrics`).then(r => r.json()).then(m => {
                    const el = document.getElementById('inboundMetric');
                    if (el && m && m.median_response_hours != null) {
                        el.textContent = `mediana de resposta (30d): ${m.median_response_hours}h`;
                    }
                }).catch(() => {});
            } catch (e) {
                panel.style.display = 'none';
            }
        }

        async function inboundOpenConversation(clientId, channel) {
            if (!clientId) return;
            if (typeof clients === 'undefined' || !clients.length) await loadClients();
            if (channel === 'email') {
                if (typeof openEmailDraftModal === 'function') openEmailDraftModal(clientId);
                else if (typeof openProfileModal === 'function') openProfileModal(clientId);
                return;
            }
            const client = clients.find(c => c.id === clientId);
            const phone = client && client.phone ? normalizePhoneForWhatsapp(client.phone) : '';
            if (!phone) {
                if (typeof openMissingContactModal === 'function') openMissingContactModal();
                return;
            }
            if (getWhatsAppPreference() === 'desktop') {
                openWhatsAppDesktopWithFallback(phone, '');
            } else {
                whatsappWindowRef = openWhatsAppTab(`https://web.whatsapp.com/send?phone=${encodeURIComponent(phone)}`);
            }
        }

        async function inboundRespond(id) {
            try {
                const resp = await fetch(`${API_BASE}/inbound/${id}/respond`, { method: 'POST' });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.error || 'Erro ao marcar como respondido.');
                }
                loadInboundPending();
            } catch (e) { showError(e.message); }
        }

        // =====================================================
        // Banner de follow-ups (Bloco 7) — do dia e vencidos
        // =====================================================

        async function loadRadarBanner() {
            const el = document.getElementById('radarBanner');
            if (!el) return;
            try {
                const resp = await fetch(`${API_BASE}/commitments/alerts`);
                const data = await resp.json();
                if (!resp.ok) throw new Error(data.error || 'erro');
                const parts = [];
                if ((data.today || []).length) {
                    parts.push(`<b>${data.today.length}</b> follow-up(s) para hoje: ` +
                        data.today.map(t => `${escapeHtml(t.name)}${t.due_time ? ' às ' + escapeHtml(t.due_time) : ''}`).join(' · '));
                }
                if ((data.overdue || []).length) {
                    parts.push(`<b style="color:#ef4444;">${data.overdue.length}</b> follow-up(s) vencido(s) sem atividade registrada`);
                }
                if (!parts.length) { el.innerHTML = ''; return; }
                el.innerHTML = `
                    <div style="background:rgba(16,185,129,.08); border:1px solid rgba(16,185,129,.3); border-radius:10px; padding:10px 12px; margin-bottom:10px; font-size:13px; cursor:pointer;"
                         onclick="switchTab(null, 'agenda')" title="Abrir a Agenda">
                        ⏰ ${parts.join(' &nbsp;|&nbsp; ')}
                    </div>`;
            } catch (e) { el.innerHTML = ''; }
        }

        // =====================================================
        // Minha Semana (Bloco 14) — resumo semanal sob demanda
        // =====================================================

        let _weekReviewLoaded = false;

        async function toggleWeekReview() {
            const el = document.getElementById('weekReviewContent');
            const toggle = document.getElementById('weekReviewToggle');
            if (!el) return;
            const showing = el.style.display !== 'none';
            el.style.display = showing ? 'none' : '';
            if (toggle) toggle.textContent = showing ? 'mostrar ▾' : 'ocultar ▴';
            if (showing || _weekReviewLoaded) return;
            el.innerHTML = '<div style="color:#9ca3af; font-size:13px;">Carregando resumo da semana... 🐇</div>';
            try {
                const resp = await fetch(`${API_BASE}/week-review`);
                const d = await resp.json();
                if (!resp.ok) throw new Error(d.error || 'erro');
                _weekReviewLoaded = true;
                const cooled = (d.cooled || []).map(c =>
                    `<li>${escapeHtml(c.name)} (${escapeHtml(c.company || '')}) → ${c.status === 'atrasado' ? '🔴 atrasado' : '🟡 atenção'}</li>`).join('');
                const planByDay = {};
                (d.next_week_plan || []).forEach(p => { (planByDay[p.day] = planByDay[p.day] || []).push(p.title); });
                const plan = Object.entries(planByDay).map(([day, items]) =>
                    `<div style="margin-top:6px;"><b>${day}</b><ul style="margin:2px 0 0 18px;">${items.map(t => `<li>${escapeHtml(t)}</li>`).join('')}</ul></div>`).join('');
                el.innerHTML = `
                    <div style="display:flex; gap:18px; flex-wrap:wrap; font-size:13.5px; margin-bottom:8px;">
                        <div>✋ <b>${d.touches}</b> toques na semana</div>
                        <div>⏰ follow-ups: <b>${d.followups_created}</b> criados · <b>${d.followups_done}</b> cumpridos</div>
                        <div>📡 <b>${(d.pending_suggestions || []).length}</b> sugestão(ões) pendente(s) hoje</div>
                    </div>
                    ${cooled ? `<div style="font-size:13px;"><b>Esfriaram na semana:</b><ul style="margin:4px 0 0 18px;">${cooled}</ul></div>`
                             : '<div style="font-size:13px; color:#059669;">Nenhum contato esfriou nesta semana 🎉</div>'}
                    <div style="font-size:13px; margin-top:10px;"><b>Plano da próxima semana</b> (pré-priorizado pelo Radar):${plan || ' <span style=\"color:#9ca3af;\">sem pendências</span>'}</div>
                    <div style="margin-top:10px;">
                        <button class="btn btn-secondary btn-small" onclick="event.stopPropagation(); sendWeekReviewEmail()" title="Enviar este resumo + plano por e-mail (Outlook)"><i class="fas fa-envelope"></i> Enviar por e-mail agora</button>
                    </div>`;
            } catch (e) {
                el.innerHTML = `<div style="color:#ef4444; font-size:13px;">${escapeHtml(e.message || 'Erro ao carregar.')}</div>`;
            }
        }

        async function sendWeekReviewEmail() {
            try {
                const resp = await fetch(`${API_BASE}/week-review/send-email`, { method: 'POST' });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(payload.error || 'Falha ao enviar e-mail.');
                showSuccess('Revisão enviada para o seu e-mail!');
            } catch (e) { showError(e.message); }
        }
