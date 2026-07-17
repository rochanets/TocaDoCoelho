        // =====================================================
        // iToca Chat
        // =====================================================
        let itocaChatMsgCount = 0;
        // ID de sessão único por visita ao iToca (gerado ao entrar na aba)
        let _itocaSessionId = null;
        let _itocaSessionHasMessages = false;

        function _itocaNewSession() {
            _itocaSessionId = 'sess_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
            _itocaSessionHasMessages = false;
        }
        _itocaNewSession(); // cria sessão inicial

        async function loadITocaBaseStatus() {
            const label = document.getElementById('itocaBaseUpdatedAt');
            if (!label) return;
            try {
                const response = await fetch(`${API_BASE}/itoca/base-status`);
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.error || 'Falha ao consultar base iToca.');
                if (!payload.has_base) {
                    label.textContent = 'Base não atualizada.';
                    return;
                }
                label.textContent = `Último update: ${formatDateBr(payload.updated_at)} — ${payload.items_count} registros`;
            } catch (error) {
                label.textContent = 'Base iToca indisponível.';
            }
        }

        async function updateITocaBase(incremental = false) {
            const label = document.getElementById('itocaBaseUpdatedAt');
            const btn = document.getElementById('itocaBaseUpdateBtn');
            const progressContainer = document.getElementById('itocaProgressContainer');
            const progressBar = document.getElementById('itocaProgressBar');
            const progressMsg = document.getElementById('itocaProgressMsg');
            const progressPct = document.getElementById('itocaProgressPct');

            if (btn) { btn.disabled = true; btn.style.opacity = '0.6'; }
            if (label) label.textContent = 'Verificando alterações...';
            if (progressContainer) progressContainer.style.display = 'block';
            if (progressBar) progressBar.style.width = '5%';
            if (progressMsg) progressMsg.textContent = 'Iniciando indexação...';
            if (progressPct) progressPct.textContent = '5%';

            function setProgress(pct, msg) {
                const pb = document.getElementById('itocaProgressBar');
                const pc = document.getElementById('itocaProgressPct');
                const pm = document.getElementById('itocaProgressMsg');
                if (pb) pb.style.width = pct + '%';
                if (pc) pc.textContent = pct + '%';
                if (pm) pm.textContent = msg || '';
            }

            try {
                const response = await fetch(`${API_BASE}/itoca/base-update`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ incremental: !!incremental })
                });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.error || 'Falha ao iniciar indexação.');
                const taskId = payload.task_id;
                if (!taskId) throw new Error('Resposta inesperada do servidor.');

                // Botões Cancelar / Minimizar no topo da barra de progresso
                const _itocaProgressEl = document.getElementById('itocaProgressContainer');
                _attachBgTaskControls(
                    _itocaProgressEl, taskId,
                    () => { if (_itocaProgressEl) _itocaProgressEl.style.display = 'none'; if (btn) { btn.disabled = false; btn.style.opacity = '1'; } },
                    () => { if (_itocaProgressEl) _itocaProgressEl.style.display = 'none'; if (btn) { btn.disabled = false; btn.style.opacity = '1'; } if (label) label.textContent = 'Indexação cancelada.'; }
                );

                const sourceTab = typeof _currentTab !== 'undefined' ? _currentTab : 'iata';
                BgTaskManager.register(
                    taskId,
                    `${API_BASE}/tasks/${taskId}`,
                    'Atualizando Base iToca',
                    sourceTab,
                    (result) => {
                        const lbl = document.getElementById('itocaBaseUpdatedAt');
                        const pc  = document.getElementById('itocaProgressContainer');
                        const b   = document.getElementById('itocaBaseUpdateBtn');
                        setProgress(100, 'Concluído!');
                        showSuccess(result.message || 'Base iToca atualizada.');
                        const modeLabel = result.incremental ? ' (incremental)' : '';
                        if (lbl) lbl.textContent = `Último update: ${formatDateBr(result.updated_at)} — ${result.items_count} registros${modeLabel}`;
                        if (b) { b.disabled = false; b.style.opacity = '1'; }
                        setTimeout(() => { if (pc) pc.style.display = 'none'; }, 3000);
                    },
                    (errMsg) => {
                        const lbl = document.getElementById('itocaBaseUpdatedAt');
                        const pc  = document.getElementById('itocaProgressContainer');
                        const b   = document.getElementById('itocaBaseUpdateBtn');
                        showError(errMsg || 'Falha no update da base iToca.');
                        if (lbl) lbl.textContent = 'Base não atualizada.';
                        if (pc)  pc.style.display = 'none';
                        if (b) { b.disabled = false; b.style.opacity = '1'; }
                    },
                    (pct, step) => setProgress(pct || 5, step)
                );
            } catch (error) {
                showError(error.message || 'Falha no update da base iToca.');
                if (label) label.textContent = 'Base não atualizada.';
                if (progressContainer) progressContainer.style.display = 'none';
                if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
            }
        }

        function _itocaScrollToBottom() {
            const container = document.getElementById('itocaChatMessages');
            if (container) container.scrollTop = container.scrollHeight;
        }

        function _itocaHideEmpty() {
            const empty = document.getElementById('itocaChatEmpty');
            if (empty) empty.style.display = 'none';
        }

        function _itocaGetUserAvatarHtml() {
            if (userProfile && userProfile.photo_url) {
                return `<img src="${userProfile.photo_url}" alt="Você" onerror="this.parentElement.innerHTML='<span class=itoca-avatar-initial>' + (userProfile?.nickname || userProfile?.full_name || 'U').charAt(0).toUpperCase() + '</span>'">`;
            }
            const initial = (userProfile?.nickname || userProfile?.full_name || 'U').charAt(0).toUpperCase();
            return `<span class="itoca-avatar-initial">${initial}</span>`;
        }

        function _itocaRenderMarkdown(text) {
            // Pré-processa o texto antes de passar ao marked:
            // converte bullets com • em listas Markdown e normaliza espaços
            let processed = text;

            // Converte linhas que começam com • ou – em listas Markdown (-)
            processed = processed.replace(/^[\u2022\u2013\u2014]\s*/gm, '- ');

            // Garante que linhas de cabeçalho (Contato principal:, Compromissos:, etc.)
            // que terminam com ':' e estão sozinhas na linha virem como bold
            processed = processed.replace(/^([A-ZÀ-ÿ][^:\n]{2,50}):$/gm, '**$1:**');

            if (typeof marked !== 'undefined') {
                try {
                    // breaks:true converte \n simples em <br>, gfm habilita tabelas e listas
                    let html = marked.parse(processed, { breaks: true, gfm: true });
                    // Envolve cada <table> em um wrapper scrollable para evitar corte
                    html = html.replace(/<table>/g, '<div class="itoca-table-wrap"><table>').replace(/<\/table>/g, '</table></div>');
                    return html;
                } catch(e) {
                    // Fallback manual se marked falhar
                }
            }

            // Fallback manual: converte Markdown básico sem biblioteca
            let html = processed
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                // Headers
                .replace(/^### (.+)$/gm, '<h3>$1</h3>')
                .replace(/^## (.+)$/gm, '<h2>$1</h2>')
                .replace(/^# (.+)$/gm, '<h1>$1</h1>')
                // Bold e italic
                .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                .replace(/\*(.+?)\*/g, '<em>$1</em>')
                // Listas
                .replace(/^- (.+)$/gm, '<li>$1</li>')
                // Linhas horizontais
                .replace(/^---+$/gm, '<hr>')
                // Quebras de linha
                .replace(/\n/g, '<br>');
            // Envolve li em ul
            html = html.replace(/(<li>.*?<\/li>)(<br>)*/gs, (m) => `<ul>${m.replace(/<br>/g,'')}</ul>`);
            return html;
        }

        function _itocaIsLongResponse(text) {
            // Considera longa se tem mais de 80 chars, tem markdown ou tem quebras de linha
            return text.length > 80 || /[#*_`\[\]|\n\u2022\u2013]/.test(text);
        }

        function _itocaAppendUserMsg(question) {
            _itocaHideEmpty();
            const container = document.getElementById('itocaChatMessages');
            if (!container) return;
            const escaped = question.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
            const div = document.createElement('div');
            div.className = 'itoca-msg user';
            div.innerHTML = `
                <div class="itoca-msg-avatar">${_itocaGetUserAvatarHtml()}</div>
                <div class="itoca-msg-bubble">${escaped}</div>
            `;        container.appendChild(div);
            _itocaScrollToBottom();
        }

        function _itocaAppendTyping(stepText) {
            _itocaHideEmpty();
            const container = document.getElementById('itocaChatMessages');
            if (!container) return null;
            const div = document.createElement('div');
            div.className = 'itoca-msg assistant';
            div.id = 'itocaTypingIndicator';
            div.innerHTML = `
                <div class="itoca-msg-avatar"><img src="/images/itoca-avatar.png" alt="iToca"></div>
                <div class="itoca-typing">
                    <div class="itoca-typing-dots"><span></span><span></span><span></span></div>
                    <div class="itoca-typing-step" id="itocaTypingStep">${stepText || ''}</div>
                </div>
            `;
            container.appendChild(div);
            _itocaScrollToBottom();
            return div;
        }

        function _itocaRemoveTyping() {
            const el = document.getElementById('itocaTypingIndicator');
            if (el) el.remove();
        }

        function _itocaUpdateTypingStep(stepText) {
            const el = document.getElementById('itocaTypingStep');
            if (el) { el.textContent = stepText || ''; _itocaScrollToBottom(); }
        }

        function _itocaConfidenceClass(pct) {
            if (pct >= 70) return 'high';
            if (pct >= 40) return 'medium';
            return 'low';
        }

        function _itocaToggleSources(btn) {
            const list = btn.nextElementSibling;
            if (!list) return;
            list.classList.toggle('open');
            btn.textContent = list.classList.contains('open') ? 'Ocultar fontes' : `Ver fontes (${list.dataset.count})`;
        }

        function _itocaAppendAssistantMsg(payload) {
            const container = document.getElementById('itocaChatMessages');
            if (!container) return;
            const msgId = `itocaMsg${++itocaChatMsgCount}`;

            // ─── Sanitização defensiva do campo answer ────────────────────────────────
            // Caso o backend ainda retorne JSON bruto no campo answer (double-encoding
            // ou wrapper da API SAI não totalmente desencapsulado), tenta extrair aqui.
            let rawAnswer = payload.answer || 'Sem resposta disponível.';

            // 1. Se rawAnswer começa com '{' e contém "answer", tenta extrair
            if (typeof rawAnswer === 'string' && rawAnswer.trimStart().startsWith('{') && rawAnswer.includes('"answer"')) {
                let extracted = null;
                // 1a. Tenta parse completo (JSON válido)
                try {
                    const innerObj = JSON.parse(rawAnswer);
                    if (innerObj && typeof innerObj.answer === 'string' && innerObj.answer.trim()) {
                        extracted = innerObj.answer;
                        if (innerObj.confidence_percent != null) payload.confidence_percent = innerObj.confidence_percent;
                        if (innerObj.needs_refinement != null) payload.needs_refinement = innerObj.needs_refinement;
                        if (innerObj.refinement_hint)           payload.refinement_hint  = innerObj.refinement_hint;
                    }
                } catch (_e) { /* JSON inválido ou truncado */ }

                // 1b. Fallback: JSON truncado — extrai o campo 'answer' manualmente
                if (!extracted) {
                    const keyIdx = rawAnswer.indexOf('"answer"');
                    if (keyIdx !== -1) {
                        const colonIdx = rawAnswer.indexOf(':', keyIdx + 8);
                        if (colonIdx !== -1) {
                            const valStart = rawAnswer.indexOf('"', colonIdx + 1);
                            if (valStart !== -1) {
                                const chars = [];
                                let i = valStart + 1;
                                while (i < rawAnswer.length) {
                                    const ch = rawAnswer[i];
                                    if (ch === '\\' && i + 1 < rawAnswer.length) {
                                        const nc = rawAnswer[i + 1];
                                        if (nc === 'n') chars.push('\n');
                                        else if (nc === 't') chars.push('\t');
                                        else if (nc === '"') chars.push('"');
                                        else if (nc === '\\') chars.push('\\');
                                        else chars.push(nc);
                                        i += 2; continue;
                                    }
                                    if (ch === '"') break; // fim da string
                                    chars.push(ch);
                                    i++;
                                }
                                const partial = chars.join('').trim();
                                if (partial) extracted = partial;
                            }
                        }
                    }
                }

                if (extracted) rawAnswer = extracted;
            }

            // 2. Converte \n literais (dois chars: barra + n) em quebras de linha reais
            rawAnswer = rawAnswer.replace(/\\n/g, '\n');

            // 3. Remove aspas externas se o LLM retornou a string entre aspas
            if (rawAnswer.startsWith('"') && rawAnswer.endsWith('"') && rawAnswer.length > 2) {
                try { rawAnswer = JSON.parse(rawAnswer); } catch (_e) {}
            }

            const confidence = payload.confidence_percent != null ? payload.confidence_percent : null;
            const needsRefinement = payload.needs_refinement || false;
            const refinementHint = (payload.refinement_hint || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
            const sources = payload.sources || [];
            const llmUsed = payload.llm_used || false;

            // Renderiza sempre como Markdown quando o LLM foi usado (respostas estruturadas)
            // Para respostas curtas sem LLM, usa texto simples
            const useMarkdown = llmUsed || _itocaIsLongResponse(rawAnswer);
            const answerHtml = useMarkdown
                ? _itocaRenderMarkdown(rawAnswer)
                : rawAnswer.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

            let metaHtml = '';
            if (confidence !== null && llmUsed) {
                const cls = _itocaConfidenceClass(confidence);
                metaHtml += `<span class="itoca-confidence ${cls}">${confidence}% confiança</span>`;
            }
            if (needsRefinement && refinementHint) {
                metaHtml += `<span class="itoca-refinement-hint"><i class="fas fa-lightbulb"></i> ${refinementHint}</span>`;
            }
            if (sources.length > 0) {
                const sourcesHtml = sources.map(s => {
                    const rowId = s.id != null ? `#${s.id}` : '';
                    const snippet = (s.snippet || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
                    return `<li>[${(s.table||'').replace(/&/g,'&amp;')}${rowId}] ${snippet}</li>`;
                }).join('');
                metaHtml += `<button class="itoca-sources-toggle" onclick="_itocaToggleSources(this)">Ver fontes (${sources.length})</button><ul class="itoca-sources-list" data-count="${sources.length}">${sourcesHtml}</ul>`;
            }

            // Notificação de ação sugerida (se houver)
            const suggestedAction = payload.suggested_action || null;
            let actionNotificationHtml = '';
            if (suggestedAction && suggestedAction.action_type) {
                actionNotificationHtml = _itocaBuildActionNotification(msgId, suggestedAction);
            }

            const bubbleClass = (needsRefinement ? 'itoca-msg-bubble needs-refinement' : 'itoca-msg-bubble') + (useMarkdown ? ' itoca-markdown' : '');
            const div = document.createElement('div');
            div.className = 'itoca-msg assistant';
            div.id = msgId;
            div.innerHTML = `
                <div class="itoca-msg-avatar"><img src="/images/itoca-avatar.png" alt="iToca"></div>
                <div style="flex:1; min-width:0;">
                    <div class="${bubbleClass}">${answerHtml}</div>
                    ${metaHtml ? `<div class="itoca-msg-meta">${metaHtml}</div>` : ''}
                    ${actionNotificationHtml}
                </div>
            `;
            container.appendChild(div);
            _itocaScrollToBottom();
        }

        // Mapa de rótulos legíveis para os campos de cada tipo de ação
        const _ITOCA_FIELD_LABELS = {
            title:        'Título',
            description:  'Descrição',
            urgency:      'Urgência',
            account_name: 'Empresa',
            company:      'Empresa',
            contact_name: 'Contato',
            name:         'Nome',
            position:     'Cargo',
            email:        'E-mail',
            phone:        'Telefone',
            linkedin:     'LinkedIn',
            information:  'Informação',
            contact_type: 'Tipo de contato',
            due_date:     'Data',
            due_time:     'Horário',
            notes:        'Observações',
            card_title:   'Pergunta de mapeamento',
            response:     'Resposta',
            content:      'Conteúdo',
            category:     'Categoria',
            tags:         'Tags',
        };

        // Campos editáveis por tipo de ação (o usuário pode corrigir antes de confirmar)
        const _ITOCA_EDITABLE_FIELDS = {
            kanban_card:         ['title', 'description', 'urgency', 'account_name', 'contact_name'],
            activity:            ['contact_name', 'company', 'description', 'contact_type'],
            new_contact:         ['name', 'company', 'position', 'email', 'phone', 'linkedin'],
            wiki_entry:          ['title', 'content', 'category', 'tags'],
            commitment:          ['title', 'due_date', 'due_time', 'contact_name', 'notes'],
            environment_mapping: ['company', 'card_title', 'response'],
        };

        function _itocaBuildActionNotification(msgId, action) {
            const notifId = `itocaAction_${msgId}`;
            const bodyId  = `itocaActionBody_${msgId}`;
            const label   = action.label || 'Ação sugerida';
            const fields  = action.fields || {};
            const actionType = action.action_type;
            const editableKeys = _ITOCA_EDITABLE_FIELDS[actionType] || Object.keys(fields);

            // Monta os campos editáveis
            let fieldsHtml = '';
            for (const key of editableKeys) {
                const val = (fields[key] || '').toString();
                if (!val && key !== 'notes' && key !== 'due_time' && key !== 'tags' && key !== 'category') continue;
                const fieldLabel = _ITOCA_FIELD_LABELS[key] || key;
                const escaped = val.replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                fieldsHtml += `
                    <div class="itoca-action-field">
                        <span class="itoca-action-field-label">${fieldLabel}:</span>
                        <input class="itoca-action-field-input" data-field="${key}" value="${escaped}" placeholder="${fieldLabel}">
                    </div>`;
            }

            const actionDataJson = JSON.stringify(action).replace(/"/g, '&quot;');

            return `
            <div class="itoca-action-notification" id="${notifId}">
                <div class="itoca-action-notification-header" onclick="_itocaToggleActionNotif('${bodyId}', this)">
                    <span class="itoca-action-notification-icon"><i class="fas fa-magic"></i></span>
                    <span class="itoca-action-notification-title">Ação sugerida: ${label}</span>
                    <span class="itoca-action-notification-badge">NOVO</span>
                    <span class="itoca-action-notification-chevron"><i class="fas fa-chevron-down"></i></span>
                </div>
                <div class="itoca-action-notification-body" id="${bodyId}">
                    <div class="itoca-action-fields">${fieldsHtml || '<span style="font-size:12px;color:#6b7280;">Nenhum campo extraído.</span>'}</div>
                    <div class="itoca-action-buttons">
                        <button class="itoca-action-btn-confirm" onclick="_itocaConfirmAction('${notifId}', '${bodyId}', '${actionType}')">
                            <i class="fas fa-check"></i> Confirmar e criar
                        </button>
                        <button class="itoca-action-btn-discard" onclick="_itocaDiscardAction('${notifId}')">
                            <i class="fas fa-times"></i> Descartar
                        </button>
                    </div>
                </div>
            </div>`;
        }

        function _itocaToggleActionNotif(bodyId, headerEl) {
            const body = document.getElementById(bodyId);
            if (!body) return;
            const isOpen = body.classList.toggle('open');
            if (headerEl) headerEl.classList.toggle('open', isOpen);
            _itocaScrollToBottom();
        }

        async function _itocaConfirmAction(notifId, bodyId, actionType) {
            const notif = document.getElementById(notifId);
            const body  = document.getElementById(bodyId);
            if (!notif || !body) return;

            // Coleta os campos editados pelo usuário
            const inputs = body.querySelectorAll('.itoca-action-field-input');
            const fields = {};
            inputs.forEach(inp => {
                const key = inp.dataset.field;
                if (key) fields[key] = inp.value.trim();
            });

            // Desabilita botões durante o envio
            const confirmBtn = body.querySelector('.itoca-action-btn-confirm');
            const discardBtn = body.querySelector('.itoca-action-btn-discard');
            if (confirmBtn) { confirmBtn.disabled = true; confirmBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Criando...'; }
            if (discardBtn) discardBtn.disabled = true;

            try {
                const response = await fetch(`${API_BASE}/itoca/execute-action`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action_type: actionType, fields })
                });
                const result = await response.json().catch(() => ({}));

                if (response.ok && result.success) {
                    // Substitui o corpo da notificação por mensagem de sucesso
                    body.innerHTML = `<div class="itoca-action-success"><i class="fas fa-check-circle"></i> ${result.message || 'Criado com sucesso!'}</div>`;
                    body.classList.add('open');
                    // Atualiza o header para indicar concluído
                    const header = notif.querySelector('.itoca-action-notification-header');
                    if (header) {
                        header.style.cursor = 'default';
                        header.onclick = null;
                        const badge = header.querySelector('.itoca-action-notification-badge');
                        if (badge) { badge.textContent = 'FEITO'; badge.style.background = '#059669'; }
                    }
                } else {
                    const errMsg = result.error || 'Não foi possível criar o registro.';
                    body.innerHTML += `<div class="itoca-action-error" style="margin-top:8px;"><i class="fas fa-exclamation-circle"></i> ${errMsg}</div>`;
                    if (confirmBtn) { confirmBtn.disabled = false; confirmBtn.innerHTML = '<i class="fas fa-check"></i> Tentar novamente'; }
                    if (discardBtn) discardBtn.disabled = false;
                }
            } catch (err) {
                body.innerHTML += `<div class="itoca-action-error" style="margin-top:8px;"><i class="fas fa-exclamation-circle"></i> Erro de conexão: ${err.message}</div>`;
                if (confirmBtn) { confirmBtn.disabled = false; confirmBtn.innerHTML = '<i class="fas fa-check"></i> Tentar novamente'; }
                if (discardBtn) discardBtn.disabled = false;
            }
            _itocaScrollToBottom();
        }

        function _itocaDiscardAction(notifId) {
            const notif = document.getElementById(notifId);
            if (notif) {
                notif.style.opacity = '0';
                notif.style.transition = 'opacity .3s';
                setTimeout(() => notif.remove(), 300);
            }
        }

        function _itocaAppendErrorMsg(message) {
            const container = document.getElementById('itocaChatMessages');
            if (!container) return;
            const escaped = (message || 'Erro desconhecido.').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
            const div = document.createElement('div');
            div.className = 'itoca-msg error';
            div.innerHTML = `
                <div class="itoca-msg-avatar" style="background:#fef2f2;border:1px solid #fecaca;color:#991b1b;"><i class="fas fa-exclamation-triangle"></i></div>
                <div class="itoca-msg-bubble">${escaped}</div>
            `;
            container.appendChild(div);
            _itocaScrollToBottom();
        }

        function clearITocaChat() {
            const container = document.getElementById('itocaChatMessages');
            if (!container) return;
            container.innerHTML = `
                <div class="itoca-chat-empty" id="itocaChatEmpty">
                    Olá! Sou o iToca. Atualize a base e me faça uma pergunta sobre seus contatos, atividades, agenda ou qualquer dado do sistema.
                </div>
            `;
            itocaChatMsgCount = 0;
            _itocaNewSession();
        }

        async function _itocaSaveSessionAndClear() {
            // Apenas limpa o chat e cria nova sessão; o histórico já foi salvo via API durante as perguntas
            clearITocaChat();
        }

        async function loadITocaHistory() {
            const listEl = document.getElementById('itocaHistoryList');
            if (!listEl) return;
            listEl.innerHTML = '<div class="itoca-history-empty">Carregando...</div>';
            try {
                const response = await fetch(`${API_BASE}/itoca/history`);
                const sessions = await response.json().catch(() => []);
                if (!Array.isArray(sessions) || sessions.length === 0) {
                    listEl.innerHTML = '<div class="itoca-history-empty">Nenhuma conversa registrada ainda.</div>';
                    return;
                }
                listEl.innerHTML = sessions.map(s => {
                    const date = s.last_at ? formatDateBr(s.last_at) : '';
                    const question = (s.first_question || 'Conversa').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
                    const msgCount = Math.floor((s.msg_count || 0) / 2);
                    const sessionId = (s.session_id || '').replace(/"/g,'&quot;');
                    return `
                        <div class="itoca-history-item" id="hist_${sessionId}">
                            <div class="itoca-history-item-header">
                                <span class="itoca-history-item-question" title="${question}">${question}</span>
                                <span class="itoca-history-item-date">${date}</span>
                                <button class="itoca-history-item-del" onclick="deleteITocaSession('${sessionId}', event)" title="Excluir sessão"><i class="fas fa-times"></i></button>
                            </div>
                            <div class="itoca-history-item-meta">${msgCount} pergunta${msgCount !== 1 ? 's' : ''}</div>
                            <div class="itoca-history-messages" id="histMsgs_${sessionId}"></div>
                        </div>
                    `;
                }).join('');
                // Adiciona click para expandir
                listEl.querySelectorAll('.itoca-history-item').forEach(item => {
                    item.addEventListener('click', function(e) {
                        if (e.target.closest('.itoca-history-item-del')) return;
                        const sessionId = this.id.replace('hist_', '');
                        toggleITocaHistorySession(sessionId);
                    });
                });
            } catch (e) {
                listEl.innerHTML = '<div class="itoca-history-empty">Erro ao carregar histórico.</div>';
            }
        }

        async function toggleITocaHistorySession(sessionId) {
            const msgsEl = document.getElementById(`histMsgs_${sessionId}`);
            if (!msgsEl) return;
            if (msgsEl.classList.contains('open')) {
                msgsEl.classList.remove('open');
                return;
            }
            msgsEl.innerHTML = '<div class="itoca-history-empty">Carregando...</div>';
            msgsEl.classList.add('open');
            try {
                const response = await fetch(`${API_BASE}/itoca/history/${encodeURIComponent(sessionId)}`);
                const messages = await response.json().catch(() => []);
                if (!Array.isArray(messages) || messages.length === 0) {
                    msgsEl.innerHTML = '<div class="itoca-history-empty">Sem mensagens.</div>';
                    return;
                }
                const msgHtml = messages.map(m => {
                    const roleLabel = m.role === 'user' ? 'Você' : 'iToca';
                    const content = (m.content || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
                    const time = m.created_at ? formatDateBr(m.created_at) : '';
                    let meta = '';
                    if (m.role === 'assistant' && m.confidence_percent != null) {
                        const cls = m.confidence_percent >= 70 ? 'high' : m.confidence_percent >= 40 ? 'medium' : 'low';
                        meta = `<span class="itoca-confidence ${cls}" style="margin-left:6px;">${m.confidence_percent}%</span>`;
                    }
                    return `<div class="itoca-history-msg">
                        <div class="itoca-history-msg-role ${m.role}">${roleLabel} &middot; ${time}${meta}</div>
                        <div class="itoca-history-msg-content">${content}</div>
                    </div>`;
                }).join('');
                const safeSessionId = sessionId.replace(/'/g, "\\'");
                msgsEl.innerHTML = msgHtml + `<button class="itoca-history-resume-btn" onclick="resumeITocaSession('${safeSessionId}')"><i class="fas fa-comments"></i> Continuar esta conversa</button>`;
            } catch (e) {
                msgsEl.innerHTML = '<div class="itoca-history-empty">Erro ao carregar mensagens.</div>';
            }
        }

        async function deleteITocaSession(sessionId, event) {
            if (event) event.stopPropagation();
            try {
                await fetch(`${API_BASE}/itoca/history/${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
                const item = document.getElementById(`hist_${sessionId}`);
                if (item) item.remove();
                const listEl = document.getElementById('itocaHistoryList');
                if (listEl && !listEl.querySelector('.itoca-history-item')) {
                    listEl.innerHTML = '<div class="itoca-history-empty">Nenhuma conversa registrada ainda.</div>';
                }
            } catch (e) {
                showError('Erro ao excluir sessão.');
            }
        }

        // Retoma uma conversa do histórico: carrega as mensagens no chat e reutiliza o session_id
        async function resumeITocaSession(sessionId) {
            try {
                const response = await fetch(`${API_BASE}/itoca/history/${encodeURIComponent(sessionId)}`);
                const messages = await response.json().catch(() => []);
                if (!Array.isArray(messages) || messages.length === 0) {
                    showError('Não foi possível carregar a conversa.');
                    return;
                }

                // Reutiliza o session_id existente — o backend vai usar o histórico do BD como contexto
                _itocaSessionId = sessionId;
                _itocaSessionHasMessages = true;

                // Limpa e popula o chat com o histórico
                const container = document.getElementById('itocaChatMessages');
                if (!container) return;
                _itocaHideEmpty();
                container.innerHTML = '';

                // Marca de separação visual para o contexto retomado
                const divider = document.createElement('div');
                divider.className = 'itoca-msg system';
                divider.innerHTML = `<span class="itoca-system-bubble"><i class="fas fa-history"></i> Conversa retomada do histórico</span>`;
                container.appendChild(divider);

                messages.forEach(m => {
                    const div = document.createElement('div');
                    if (m.role === 'user') {
                        div.className = 'itoca-msg user replayed';
                        const escaped = (m.content || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
                        div.innerHTML = `
                            <div class="itoca-msg-avatar">${_itocaGetUserAvatarHtml()}</div>
                            <div class="itoca-msg-bubble">${escaped}</div>`;
                    } else {
                        div.className = 'itoca-msg assistant replayed';
                        const htmlContent = _itocaRenderMarkdown(m.content || '');
                        let confidenceBadge = '';
                        if (m.confidence_percent != null) {
                            const cls = _itocaConfidenceClass(m.confidence_percent);
                            confidenceBadge = `<span class="itoca-confidence ${cls}">${m.confidence_percent}%</span>`;
                        }
                        div.innerHTML = `
                            <div class="itoca-msg-avatar"><img src="/images/itoca-avatar.png" alt="iToca" onerror="this.style.display='none'"></div>
                            <div class="itoca-msg-bubble itoca-assistant-bubble">
                                <div class="itoca-answer-text">${htmlContent}</div>
                                ${confidenceBadge}
                            </div>`;
                    }
                    container.appendChild(div);
                });

                // Separador visual indicando onde a nova mensagem será enviada
                const continueDiv = document.createElement('div');
                continueDiv.className = 'itoca-msg system';
                continueDiv.innerHTML = `<span class="itoca-system-bubble"><i class="fas fa-pencil-alt"></i> Continue a conversa abaixo</span>`;
                container.appendChild(continueDiv);

                _itocaScrollToBottom();

                // Fecha o histórico e sobe para o chat
                document.getElementById('itocaHistorySection')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                setTimeout(() => {
                    document.getElementById('iata')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    document.getElementById('iataText')?.focus();
                }, 200);

            } catch (e) {
                showError('Erro ao retomar conversa.');
            }
        }

        // Adiciona uma mensagem de sistema (informativa) ao chat do iToca
        function _itocaAppendSystemMsg(text) {
            _itocaHideEmpty();
            const container = document.getElementById('itocaChatMessages');
            if (!container) return null;
            const div = document.createElement('div');
            div.className = 'itoca-msg system';
            div.innerHTML = `<span class="itoca-system-bubble">${text}</span>`;
            container.appendChild(div);
            _itocaScrollToBottom();
            return div;
        }

        function handleITocaKeydown(event) {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                askIToca();
            }
        }

        // Verifica se a base do iToca está desatualizada (> 1 dia). Se sim, faz update
        // incremental silencioso antes de prosseguir com a pergunta.
        async function _itocaCheckAndAutoUpdate() {
            try {
                const statusResp = await fetch(`${API_BASE}/itoca/base-status`);
                if (!statusResp.ok) return;
                const statusData = await statusResp.json().catch(() => ({}));

                if (!statusData.updated_at) return; // base nunca atualizada, não intervém

                const updatedAt = new Date(statusData.updated_at.replace(' ', 'T'));
                const diffMs = Date.now() - updatedAt.getTime();
                if (diffMs < 24 * 60 * 60 * 1000) return; // menos de 1 dia → ok

                // Base com mais de 1 dia → update incremental silencioso
                const statusMsgEl = _itocaAppendSystemMsg('⏳ Base iToca desatualizada. Atualizando antes de responder...');

                const updateResp = await fetch(`${API_BASE}/itoca/base-update`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ incremental: true })
                });
                if (!updateResp.ok) {
                    statusMsgEl?.remove();
                    return;
                }
                const { task_id } = await updateResp.json().catch(() => ({}));
                if (!task_id) { statusMsgEl?.remove(); return; }

                // Polling até concluir, dar erro ou atingir timeout de 30s
                await Promise.race([
                    new Promise((resolve) => {
                        const poll = async () => {
                            try {
                                const taskResp = await fetch(`${API_BASE}/tasks/${task_id}`);
                                const taskData = await taskResp.json().catch(() => ({}));
                                if (taskData.status === 'done') {
                                    if (statusMsgEl) statusMsgEl.querySelector('.itoca-system-bubble').innerHTML = '✅ Base atualizada! Processando sua pergunta...';
                                    // Atualiza o label de status
                                    const lbl = document.getElementById('itocaBaseUpdatedAt');
                                    if (lbl && taskData.result?.updated_at) {
                                        const mode = taskData.result.incremental ? ' (incremental)' : '';
                                        lbl.textContent = `Último update: ${formatDateBr(taskData.result.updated_at)} — ${taskData.result.items_count} registros${mode}`;
                                    }
                                    setTimeout(() => statusMsgEl?.remove(), 1800);
                                    resolve();
                                } else if (taskData.status === 'error') {
                                    statusMsgEl?.remove();
                                    resolve();
                                } else {
                                    setTimeout(poll, 1500);
                                }
                            } catch (_e) { statusMsgEl?.remove(); resolve(); }
                        };
                        poll();
                    }),
                    new Promise(resolve => setTimeout(() => {
                        statusMsgEl?.remove();
                        resolve();
                    }, 30000)) // timeout de 30s — libera o input mesmo se o update travar
                ]);

            } catch (_e) { /* ignora erros no auto-update, a pergunta segue normalmente */ }
        }

        async function askIToca() {
            const textarea = document.getElementById('iataText');
            const question = (textarea?.value || '').trim();
            if (!question) {
                showError('Digite uma pergunta para o iToca.');
                return;
            }

            // Disable input while processing
            const askBtn = document.getElementById('iataAskBtn');
            if (askBtn) askBtn.disabled = true;
            if (textarea) textarea.disabled = true;

            // Verifica e atualiza a base se estiver desatualizada (> 1 dia)
            await _itocaCheckAndAutoUpdate();

            _itocaAppendUserMsg(question);
            if (textarea) textarea.value = '';
            _itocaAppendTyping('🔍 Iniciando busca...');

            try {
                _itocaSessionHasMessages = true;
                const response = await fetch(`${API_BASE}/itoca/ask`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ question, session_id: _itocaSessionId })
                });
                const payload = await response.json().catch(() => ({}));

                if (!response.ok) {
                    _itocaRemoveTyping();
                    const errMsg = payload.error || 'Não foi possível consultar o iToca.';
                    if (payload.base_ready === false) {
                        _itocaAppendErrorMsg('⚠️ ' + errMsg);
                    } else {
                        _itocaAppendErrorMsg(errMsg);
                    }
                    showError(errMsg);
                    return;
                }

                // Async path: backend returned 202 + task_id
                const taskId = payload.task_id;
                if (!taskId) {
                    // Fallback: sync response (base not ready or legacy)
                    _itocaRemoveTyping();
                    _itocaAppendAssistantMsg(payload);
                    return;
                }

                // Poll task until done or error (max ~90s, then slow-poll)
                let pollCount = 0;
                const MAX_POLLS = 112; // ~90s at 800ms
                await new Promise((resolve) => {
                    const poll = async () => {
                        try {
                            const taskResp = await fetch(`${API_BASE}/tasks/${taskId}`);
                            const taskData = await taskResp.json().catch(() => ({}));

                            if (taskData.step) _itocaUpdateTypingStep(taskData.step);

                            if (taskData.status === 'done') {
                                _itocaRemoveTyping();
                                _itocaAppendAssistantMsg(taskData.result || {});
                                const updatedAt = taskData.result?.base_updated_at;
                                if (updatedAt) {
                                    const label = document.getElementById('itocaBaseUpdatedAt');
                                    if (label) label.textContent = `Último update: ${formatDateBr(updatedAt)}`;
                                }
                                resolve();
                                return;
                            }

                            if (taskData.status === 'error') {
                                _itocaRemoveTyping();
                                const errMsg = taskData.error || 'Erro ao processar resposta.';
                                _itocaAppendErrorMsg(errMsg);
                                showError(errMsg);
                                resolve();
                                return;
                            }

                            // Still processing — continue polling
                            if (++pollCount >= MAX_POLLS) {
                                _itocaUpdateTypingStep('⏱️ Aguardando resposta da IA...');
                                setTimeout(poll, 2000);
                            } else {
                                setTimeout(poll, 800);
                            }
                        } catch (e) {
                            _itocaRemoveTyping();
                            _itocaAppendErrorMsg(e.message || 'Falha ao consultar iToca.');
                            showError(e.message || 'Falha ao consultar iToca.');
                            resolve();
                        }
                    };
                    poll();
                });

            } catch (error) {
                _itocaRemoveTyping();
                _itocaAppendErrorMsg(error.message || 'Falha ao consultar iToca.');
                showError(error.message || 'Falha ao consultar iToca.');
            } finally {
                if (askBtn) askBtn.disabled = false;
                if (textarea) { textarea.disabled = false; textarea.focus(); }
            }
        }

        function validateIataAttachment(event) {
            const files = Array.from(event.target.files || []);
            const allTxt = files.every(file => file.type === 'text/plain' || file.name.toLowerCase().endsWith('.txt'));
            if (!allTxt) {
                event.target.value = '';
                showError('No iToca, apenas anexo de texto (.txt).');
            }
            const lbl = document.getElementById('iataAttachmentLabel');
            if (lbl) lbl.classList.toggle('has-file', allTxt && files.length > 0);
        }

        let activeMediaRecorder = null;
        let activeVoiceBtnId = null;
        let activeAudioChunks = [];
        let activeVoiceTargetElement = null;
        let activeVoiceInitialValue = '';

        const VOICE_DEBUG = true;

        function setVoiceButtonState(btn, state) {
            if (!btn) return;
            btn.classList.remove('active', 'transcribing');
            if (state === 'recording') btn.classList.add('active');
            if (state === 'transcribing') btn.classList.add('transcribing');
        }

        async function transcribeRecordedAudio(audioBlob) {
            const formData = new FormData();
            formData.append('audio', audioBlob, 'gravacao.webm');
            const response = await fetch(`${API_BASE}/transcribe-audio`, {
                method: 'POST',
                body: formData,
                headers: { Accept: 'application/json' }
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) {
                const backendMessage = payload.error || `HTTP ${response.status}`;
                const installHelp = Array.isArray(payload.install_instructions)
                    ? `\n${payload.install_instructions.join('\n')}`
                    : '';
                if (VOICE_DEBUG) {
                    console.error('[Voice][Transcription] Falha no backend', {
                        status: response.status,
                        statusText: response.statusText,
                        payload
                    });
                }
                throw new Error(`Falha na transcrição: ${backendMessage}${installHelp}`);
            }
            if (VOICE_DEBUG) {
                console.log('[Voice][Transcription] Sucesso', { chars: String(payload.text || '').length });
            }
            return String(payload.text || '').trim();
        }

        async function toggleVoiceTranscription(targetInputId, buttonId) {
            const btn = document.getElementById(buttonId);
            const fallbackSelector = targetInputId === 'activityInformation'
                ? '#activityForm textarea[name="information"]'
                : '#iataText';
            const target = document.getElementById(targetInputId) || document.querySelector(fallbackSelector);
            if (!btn || !target) return;

            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || typeof MediaRecorder === 'undefined') {
                showError('Captura de áudio não suportada neste navegador.');
                return;
            }

            if (activeMediaRecorder && activeVoiceBtnId === buttonId) {
                activeMediaRecorder.stop();
                return;
            }

            if (activeMediaRecorder && activeVoiceBtnId && activeVoiceBtnId !== buttonId) {
                activeMediaRecorder.stop();
                return;
            }

            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                const mediaRecorder = new MediaRecorder(stream);
                activeAudioChunks = [];
                activeMediaRecorder = mediaRecorder;
                activeVoiceBtnId = buttonId;
                activeVoiceTargetElement = target;
                activeVoiceInitialValue = String(target.value || '').trim();
                setVoiceButtonState(btn, 'recording');
                target.focus();

                mediaRecorder.ondataavailable = (event) => {
                    if (event.data && event.data.size > 0) activeAudioChunks.push(event.data);
                };

                mediaRecorder.onerror = () => {
                    setVoiceButtonState(btn, 'idle');
                    showError('Erro durante gravação de áudio.');
                };

                mediaRecorder.onstop = async () => {
                    stream.getTracks().forEach(track => track.stop());
                    setVoiceButtonState(btn, 'transcribing');

                    try {
                        if (!activeAudioChunks.length) return;
                        const audioBlob = new Blob(activeAudioChunks, { type: 'audio/webm' });
                        const transcribedText = await transcribeRecordedAudio(audioBlob);
                        const currentTarget = activeVoiceTargetElement || target;
                        if (!transcribedText || !currentTarget) return;
                        const currentValue = String(currentTarget.value || '').trim();
                        const baseValue = currentValue || activeVoiceInitialValue;
                        currentTarget.value = [baseValue, transcribedText].filter(Boolean).join(' ').trim();
                    } catch (error) {
                        showError((error && error.message) ? error.message : 'Falha ao transcrever áudio. Veja o console/log do servidor para detalhes.');
                    } finally {
                        setVoiceButtonState(btn, 'idle');
                        activeMediaRecorder = null;
                        activeVoiceBtnId = null;
                        activeAudioChunks = [];
                        activeVoiceTargetElement = null;
                        activeVoiceInitialValue = '';
                    }
                };

                mediaRecorder.start();
            } catch (error) {
                setVoiceButtonState(btn, 'idle');
                showError('Não foi possível acessar o microfone.');
            }
        }

        async function openDuplicateWarningModal(client) {
            return new Promise(resolve => {
                const avatar = client.photo_url ? `<img src="${client.photo_url}" class="profile-avatar-large" style="width:86px;height:86px;">` : `<div class="profile-avatar-large" style="width:86px;height:86px;display:flex;align-items:center;justify-content:center;">${(client.name||'?').charAt(0).toUpperCase()}</div>`;
                const html = `
                    <div class="modal active" id="duplicateWarningModal" onclick="if(event.target===this){document.getElementById('duplicateWarningModal').remove(); window._dupResolve(false);}">
                        <div class="modal-content" style="max-width:700px; border:1px solid #fdba74; box-shadow:0 16px 34px rgba(249,115,22,0.22);">
                            <h2 style="color:#9a3412; margin-bottom:10px;">Possível duplicidade</h2>
                            <p style="color:#7c2d12; margin-bottom:12px;">Já existe um cadastro que pode ser o mesmo. Confira a ficha e confirme se deseja criar mesmo assim.</p>
                            <div class="profile-layout" style="background:#fff7ed; border:1px solid #fed7aa; border-radius:12px; padding:12px;">
                                <div class="profile-avatar-wrap">${avatar}</div>
                                <div style="flex:1; min-width:220px;">
                                    <div class="profile-info-grid">
                                        <div class="profile-field"><div class="profile-field-label">Nome</div><div class="profile-field-value">${escapeHtml(client.name || '-')}</div></div>
                                        <div class="profile-field"><div class="profile-field-label">Empresa</div><div class="profile-field-value">${escapeHtml(client.company || '-')}</div></div>
                                        <div class="profile-field"><div class="profile-field-label">Cargo</div><div class="profile-field-value">${escapeHtml(client.position || '-')}</div></div>
                                        <div class="profile-field"><div class="profile-field-label">Email</div><div class="profile-field-value">${escapeHtml(client.email || '-')}</div></div>
                                        <div class="profile-field"><div class="profile-field-label">Telefone</div><div class="profile-field-value">${escapeHtml(client.phone || '-')}</div></div>
                                    </div>
                                </div>
                            </div>
                            <div class="modal-footer" style="margin-top:14px;">
                                <button class="btn btn-secondary" style="background:#fed7aa; color:#7c2d12;" onclick="document.getElementById('duplicateWarningModal').remove(); window._dupResolve(false);">Cancelar</button>
                                <button class="btn btn-primary" style="background:#fb923c;" onclick="document.getElementById('duplicateWarningModal').remove(); window._dupResolve(true);">Confirmar criação</button>
                            </div>
                        </div>
                    </div>`;
                window._dupResolve = resolve;
                const existing = document.getElementById('duplicateWarningModal');
                if (existing) existing.remove();
                document.body.insertAdjacentHTML('beforeend', html);
            });
        }

        function normalizeCompanyKey(name) {
            return String(name || '').trim().toLowerCase();
        }

        let orgAccountFilter = '';
        let orgGroupingMode = 'position'; // padrão da tela

        function setOrgAccountFilter(value) {
            orgAccountFilter = String(value || '');
            loadOrganizationalMapping();
        }

        function setOrgGroupingMode(mode) {
            const allowedModes = new Set(['position', 'area', 'position_area']);
            orgGroupingMode = allowedModes.has(mode) ? mode : 'position';
            loadOrganizationalMapping();
        }

        function getOrgGroupLabel(client, mode) {
            const position = String(client?.position || '').trim() || 'Não informado';
            const area = String(client?.area_of_activity || '').trim() || 'Não informado';
            if (mode === 'area') return area;
            if (mode === 'position_area') return `${position} + ${area}`;
            return position;
        }

        async function loadOrganizationalMapping() {
            const [clientsRes, accountsRes] = await Promise.all([
                fetch(`${API_BASE}/clientes`),
                fetch(`${API_BASE}/accounts`)
            ]);
            const rawData = clientsRes.ok ? await clientsRes.json() : [];
            const data = (rawData || []).filter(c => !isArchivedClient(c));
            const accounts = accountsRes.ok ? await accountsRes.json() : [];
            const accountFilterSelect = document.getElementById('orgAccountFilterSelect');

            const accountByCompany = {};
            (accounts || []).forEach(acc => {
                const key = normalizeCompanyKey(acc.name);
                if (key) accountByCompany[key] = acc;
            });

            const accountNames = (accounts || [])
                .map(a => String(a?.name || '').trim())
                .filter(Boolean)
                .sort((a, b) => a.localeCompare(b, 'pt-BR'));

            if (accountFilterSelect) {
                const currentValue = String(orgAccountFilter || '');
                const options = ['<option value="">Selecione uma conta</option>']
                    .concat(accountNames.map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`));
                accountFilterSelect.innerHTML = options.join('');
                if (currentValue && accountNames.includes(currentValue)) {
                    accountFilterSelect.value = currentValue;
                } else {
                    accountFilterSelect.value = '';
                    if (currentValue) orgAccountFilter = '';
                }
            }

            const companies = orgAccountFilter
                ? accountNames.filter(name => normalizeCompanyKey(name) === normalizeCompanyKey(orgAccountFilter))
                : accountNames;

            const groupLabels = [...new Set(data.map(c => getOrgGroupLabel(c, orgGroupingMode)).filter(Boolean))]
                .sort((a, b) => {
                    const r = getCompanyImportanceRank(a) - getCompanyImportanceRank(b);
                    return r !== 0 ? r : a.localeCompare(b, 'pt-BR');
                });
            let html = '<div class="org-map-container"><div class="org-table-wrap"><table class="org-table"><thead><tr><th>Cliente/Empresa</th>' + groupLabels.map(label=>`<th>${escapeHtml(label)}</th>`).join('') + '</tr></thead><tbody>';
            companies.forEach(company => {
                const account = accountByCompany[normalizeCompanyKey(company)] || {};
                const companyLogo = account.logo_url || '/logo-coelho.png';
                html += `<tr><td><div style="display:flex; align-items:center; gap:8px;"><img src="${companyLogo}" style="width:24px; height:24px; border-radius:6px; object-fit:contain; border:1px solid rgba(96,187,217,.35); background:#fff;"><strong style="color:#fff;">${escapeHtml(company)}</strong></div></td>`;
                groupLabels.forEach(label => {
                    const people = data
                        .filter(c =>
                            String(c.company || '').toLowerCase() === String(company || '').toLowerCase()
                            && getOrgGroupLabel(c, orgGroupingMode) === label
                        )
                        .sort((a,b) => {
                            const targetDiff = Number(b.is_target || 0) - Number(a.is_target || 0);
                            if (targetDiff !== 0) return targetDiff;
                            return String(a.name || '').localeCompare(String(b.name || ''), 'pt-BR');
                        });
                    if (people.length) {
                        const cell = people.map(person => `<div class="occupant">${renderAvatar(person)}<button class="table-link-btn" onclick="openProfileModal(${person.id})">${escapeHtml(person.name)}</button></div>`).join('');
                        html += `<td>${cell}</td>`;
                    } else {
                        const safeCompany = escapeHtml(company);
                        const suggestedPosition = orgGroupingMode === 'position' ? label : '';
                        const safeSuggestedPosition = escapeHtml(suggestedPosition);
                        html += `<td><button class="org-add-btn" data-company="${safeCompany}" data-position="${safeSuggestedPosition}" title="Cadastrar novo contato em ${safeCompany}">+</button></td>`;
                    }
                });
                html += '</tr>';
            });
            html += '</tbody></table></div></div>';
            const container = document.getElementById('organizationalContent');
            container.innerHTML = html;
            const groupingSelect = document.getElementById('orgGroupingModeSelect');
            if (groupingSelect && groupingSelect.value !== orgGroupingMode) groupingSelect.value = orgGroupingMode;
            // Delegação de eventos para os botões +
            container.querySelectorAll('.org-add-btn').forEach(btn => {
                btn.addEventListener('click', function() {
                    // getAttribute já decodifica entidades HTML automaticamente
                    const company = this.dataset.company;
                    const position = this.dataset.position;
                    openClientModalFromOrgMap(company, position);
                });
            });
        }

        async function openClientModalFromOrgMap(company, position) {
            _orgMapOpenContext = { company, position };
            currentEditingClientId = null;
            document.getElementById('clientModalTitle').textContent = 'Novo Cliente';
            document.getElementById('clientForm').reset();
            resetClientPhotoField();
            await loadCompanyAndPositionOptions();
            // Pré-selecionar empresa
            const cSel = document.getElementById('clientCompanySelect');
            if (cSel && [...cSel.options].some(o => o.value === company)) {
                cSel.value = company;
            } else if (cSel) {
                cSel.value = '__other__';
                const cOther = document.getElementById('clientCompanyOther');
                if (cOther) cOther.value = company;
            }
            toggleOtherField('company');
            // Pré-selecionar cargo
            const pSel = document.getElementById('clientPositionSelect');
            if (pSel && !position) {
                pSel.value = '';
            } else if (pSel && [...pSel.options].some(o => o.value === position)) {
                pSel.value = position;
            } else if (pSel) {
                pSel.value = '__other__';
                const pOther = document.getElementById('clientPositionOther');
                if (pOther) pOther.value = position;
            }
            toggleOtherField('position');
            document.getElementById('clientModal').classList.add('active');
        }

        // === Exportação XLSX do Mapeamento Organizacional ===
        let _orgExportData = null; // { clients, positions }

        async function openOrgExportModal() {
            // Buscar dados atuais
            const response = await fetch(`${API_BASE}/clientes`);
            const data = response.ok ? await response.json() : [];
            const positions = [...new Set(data.map(c => c.position).filter(Boolean))].sort((a,b)=>{
                const r = getCompanyImportanceRank(a) - getCompanyImportanceRank(b);
                return r !== 0 ? r : a.localeCompare(b,'pt-BR');
            });
            _orgExportData = { clients: data, positions };
            // Renderizar checkboxes
            const list = document.getElementById('orgExportColumnList');
            list.innerHTML = positions.map(p => `
                <label class="org-export-col-item">
                    <input type="checkbox" name="orgExportCol" value="${escapeHtml(p)}" checked>
                    ${escapeHtml(p)}
                </label>
            `).join('');
            document.getElementById('orgExportModal').classList.add('active');
        }

        function closeOrgExportModal() {
            document.getElementById('orgExportModal').classList.remove('active');
            _orgExportData = null;
        }

        function orgExportSelectAll(checked) {
            document.querySelectorAll('#orgExportColumnList input[type=checkbox]').forEach(cb => cb.checked = checked);
        }

        function doOrgExport() {
            if (!_orgExportData) return;
            const { clients, positions } = _orgExportData;
            const selectedPositions = [...document.querySelectorAll('#orgExportColumnList input[type=checkbox]:checked')].map(cb => cb.value);
            if (!selectedPositions.length) { showError('Selecione ao menos uma coluna para exportar.'); return; }

            // Montar linhas: uma linha por cliente que está nas colunas selecionadas
            const rows = [];
            const companies = [...new Set(clients.map(c => c.company).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'pt-BR'));
            companies.forEach(company => {
                selectedPositions.forEach(position => {
                    const people = clients.filter(c => c.company === company && c.position === position);
                    people.forEach(person => {
                        rows.push({
                            'Cargo': person.position || '',
                            'Nome': person.name || '',
                            'Cliente/Empresa': person.company || '',
                            'Email': person.email || '',
                            'Telefone': person.phone || ''
                        });
                    });
                });
            });

            if (!rows.length) { showError('Nenhum cliente encontrado nas colunas selecionadas.'); return; }

            // Gerar XLSX sem dependência externa usando CSV-to-XLSX via Blob
            const headers = ['Cargo', 'Nome', 'Cliente/Empresa', 'Email', 'Telefone'];
            // Usar formato XML do Excel (SpreadsheetML) para compatibilidade
            const xmlRows = rows.map(row =>
                '<Row>' + headers.map(h => `<Cell><Data ss:Type="String">${String(row[h] || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}</Data></Cell>`).join('') + '</Row>'
            ).join('');
            const xmlHeader = '<Row>' + headers.map(h => `<Cell ss:StyleID="header"><Data ss:Type="String">${h}</Data></Cell>`).join('') + '</Row>';
            const xml = `<?xml version="1.0" encoding="UTF-8"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
  xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"
  xmlns:x="urn:schemas-microsoft-com:office:excel">
  <Styles>
    <Style ss:ID="header"><Font ss:Bold="1"/><Interior ss:Color="#60BBD9" ss:Pattern="Solid"/></Style>
  </Styles>
  <Worksheet ss:Name="Mapeamento Organizacional">
    <Table>${xmlHeader}${xmlRows}</Table>
  </Worksheet>
</Workbook>`;
            const blob = new Blob([xml], { type: 'application/vnd.ms-excel;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'mapeamento_organizacional.xls';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            closeOrgExportModal();
            showSuccess('Exportação concluída!');
        }

        async function saveTargetStatus() {
            const green_days = Number(document.getElementById('targetGreen').value);
            const yellow_days = Number(document.getElementById('targetYellow').value);
            const response = await fetch(`${API_BASE}/config/status/target`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ green_days, yellow_days })});
            if (response.ok) { showSuccess('Regra C por Target salva!'); await loadStatusConfig(); }
            else showError('Erro ao salvar regra C');
        }

        const _renderSettingsOriginal = renderSettings;
        renderSettings = function() {
            _renderSettingsOriginal();
            if (statusConfig?.target) {
                const tg = document.getElementById('targetGreen');
                const ty = document.getElementById('targetYellow');
                if (tg) tg.value = Number(statusConfig.target.green_days || 5);
                if (ty) ty.value = Number(statusConfig.target.yellow_days || 10);
            }
            if (statusConfig?.cold) {
                const cg = document.getElementById('coldGreen');
                const cy = document.getElementById('coldYellow');
                if (cg) cg.value = Number(statusConfig.cold.green_days || 45);
                if (cy) cy.value = Number(statusConfig.cold.yellow_days || 60);
            }
        }

        const _getStatusOriginal = getStatus;
        getStatus = function(lastActivityDate, position, isTarget = 0, isColdContact = 0) {
            if (Number(isColdContact) === 1 && statusConfig?.cold) {
                const greenDays = Number(statusConfig.cold.green_days || 45);
                const yellowDays = Number(statusConfig.cold.yellow_days || 60);
                if (!lastActivityDate) return 'red';
                const date = new Date(lastActivityDate);
                const days = Math.floor((new Date() - date) / (1000 * 60 * 60 * 24));
                if (days < greenDays) return 'green';
                if (days < yellowDays) return 'yellow';
                return 'red';
            }
            if (Number(isTarget) === 1 && statusConfig?.target) {
                const greenDays = Number(statusConfig.target.green_days || 5);
                const yellowDays = Number(statusConfig.target.yellow_days || 10);
                if (!lastActivityDate) return 'red';
                const date = new Date(lastActivityDate);
                const days = Math.floor((new Date() - date) / (1000 * 60 * 60 * 24));
                if (days < greenDays) return 'green';
                if (days < yellowDays) return 'yellow';
                return 'red';
            }
            return _getStatusOriginal(lastActivityDate, position);
        }

        function shouldAskOutlookCalendar() {
            return localStorage.getItem('skipOutlookCalendarPrompt') !== '1';
        }

        function markSkipOutlookPrompt(skip) {
            if (skip) localStorage.setItem('skipOutlookCalendarPrompt', '1');
        }

        async function openOutlookCalendarForCommitment(item) {
            let dueTime = item.due_time;
            if (!dueTime) {
                dueTime = await uiPrompt('Informe o horário do evento (HH:MM):', '09:00', 'Horário do evento');
                if (!dueTime) return;
                await fetch(`${API_BASE}/agenda/${item.id}/time`, { method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ due_time: dueTime })});
                item.due_time = dueTime;
                await loadAgenda();
            }

            const emailFromClientsCache = clients.find(c => Number(c.id) === Number(item.client_id))?.email || '';
            let attendee = item.client_email || emailFromClientsCache || '';
            if (!attendee) {
                const goSelf = await uiConfirm('Este cliente não possui e-mail cadastrado. Deseja criar o evento no Outlook usando seu próprio e-mail?');
                if (!goSelf) return;
                attendee = userProfile?.email || '';
                if (!attendee) {
                    showError('Para criar agenda direto no Outlook é necessário e-mail do cliente ou do usuário cadastrado.');
                    return;
                }
            }

            const [hh, mm] = dueTime.split(':');
            const startLocal = `${item.due_date}T${hh.padStart(2,'0')}:${(mm||'00').padStart(2,'0')}:00`;
            const start = new Date(startLocal);
            const end = new Date(start.getTime() + 60 * 60 * 1000);
            const pad = n => String(n).padStart(2,'0');
            const fmtLocal = d => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`;
            const subject = encodeURIComponent(item.title || `Compromisso ${item.client_name || ''}`);
            const body = encodeURIComponent(item.notes || 'Evento criado pelo Toca do Coelho');
            const to = encodeURIComponent(attendee);

            const desktopUrl = `outlook://calendar/compose?subject=${subject}&body=${body}&startdt=${encodeURIComponent(fmtLocal(start))}&enddt=${encodeURIComponent(fmtLocal(end))}&to=${to}`;
            const webUrl = `https://outlook.office.com/calendar/0/deeplink/compose?subject=${subject}&body=${body}&startdt=${encodeURIComponent(fmtLocal(start))}&enddt=${encodeURIComponent(fmtLocal(end))}&to=${to}`;

            const iframe = document.createElement('iframe');
            iframe.style.display = 'none';
            iframe.src = desktopUrl;
            document.body.appendChild(iframe);
            setTimeout(() => {
                try { iframe.remove(); } catch {}
                window.open(webUrl, '_blank');
            }, 1200);
        }

        async function askOutlookForCommitments(items) {
            if (!items || !items.length || !shouldAskOutlookCalendar()) return;
            let html = `<div class="modal active" id="outlookPromptModal" onclick="if(event.target===this) closeOutlookPromptModal()"><div class="modal-content" style="max-width:540px;">`;
            html += '<h2 style="margin-bottom:10px;">Adicionar ao calendário do Outlook?</h2>';
            html += '<p style="color:#6b7280; margin-bottom:12px;">Deseja criar este evento no Outlook para revisão antes de salvar?</p>';
            html += '<label style="display:flex; gap:8px; align-items:center; margin-bottom:16px;"><input type="checkbox" id="skipOutlookAsk"> Não perguntar novamente</label>';
            html += '<div class="modal-footer" style="grid-column:1/-1;"><button class="btn btn-secondary" onclick="closeOutlookPromptModal()">Não</button><button class="btn btn-primary" onclick="confirmOutlookPrompt()">Sim</button></div>';
            html += '</div></div>';
            document.body.insertAdjacentHTML('beforeend', html);
            window._pendingOutlookCommitments = items;
        }

        function closeOutlookPromptModal() { const m=document.getElementById('outlookPromptModal'); if(m) m.remove(); }
        async function confirmOutlookPrompt() {
            const skip = document.getElementById('skipOutlookAsk')?.checked;
            markSkipOutlookPrompt(skip);
            closeOutlookPromptModal();
            const items = window._pendingOutlookCommitments || [];
            if (items.length) await openOutlookCalendarForCommitment(items[0]);
            window._pendingOutlookCommitments = null;
        }

        async function openNewAgendaModal() {
            const companies = [...new Set(clients.map(c => c.company).filter(Boolean))].sort();
            const html = `
            <div class="modal active" id="newAgendaModalInner" onclick="if(event.target===this) closeNewAgendaModal()">
                <div class="modal-content" style="max-width:560px;">
                    <h2 style="color:#047857; margin-bottom:12px;">Nova Agenda</h2>
                    <div class="form-group"><label>Empresa</label><select id="newAgendaCompany" onchange="fillNewAgendaClients()"><option value="">Selecione</option>${companies.map(c=>`<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('')}</select></div>
                    <div class="form-group"><label>Cliente</label><select id="newAgendaClient"></select></div>
                    <div class="form-group"><label>Data</label><input type="date" id="newAgendaDate"></div>
                    <div class="form-group"><label>Horário</label><input type="time" id="newAgendaTime"></div>
                    <div class="form-group"><label>Descrição</label><textarea id="newAgendaNotes" rows="3" placeholder="Descrição do compromisso"></textarea></div>
                    <div class="modal-footer" style="justify-content:flex-start;"><button class="btn btn-primary" onclick="saveNewAgenda()">Salvar</button></div>
                </div>
            </div>`;
            document.body.insertAdjacentHTML('beforeend', html);
            fillNewAgendaClients();
        }

        function closeNewAgendaModal() { const m=document.getElementById('newAgendaModalInner'); if(m) m.remove(); }
        function fillNewAgendaClients() {
            const company = document.getElementById('newAgendaCompany')?.value || '';
            const filtered = clients.filter(c => !company || c.company === company);
            const sel = document.getElementById('newAgendaClient');
            if (!sel) return;
            sel.innerHTML = '<option value="">Selecione</option>' + filtered.map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
        }

        async function saveNewAgenda() {
            const client_id = Number(document.getElementById('newAgendaClient').value || 0);
            const due_date = document.getElementById('newAgendaDate').value;
            const due_time = document.getElementById('newAgendaTime').value;
            const notes = document.getElementById('newAgendaNotes').value;
            if (!client_id || !due_date) { showError('Preencha cliente e data.'); return; }
            const response = await fetch(`${API_BASE}/agenda`, {
                method:'POST', headers:{'Content-Type':'application/json'},
                body: JSON.stringify({ client_id, due_date, due_time, title: notes || 'Nova agenda', notes })
            });
            const payload = await response.json();
            if (!response.ok) { showError(payload.error || 'Erro ao salvar agenda'); return; }
            closeNewAgendaModal();
            showSuccess('Agenda criada com sucesso!');
            await loadAgenda();
            await askOutlookForCommitments([payload.item]);
        }

        const _saveActivityOriginal = saveActivity;
        saveActivity = async function(event) {
            event.preventDefault();
            const formData = new FormData(document.getElementById('activityForm'));
            const clientSelect = document.getElementById('clientSelect');
            if (clientSelect && clientSelect.disabled) formData.set('client_id', clientSelect.value);
            try {
                const url = currentEditingActivityId ? `${API_BASE}/atividades/${currentEditingActivityId}` : `${API_BASE}/atividades`;
                const response = await fetch(url, { method: currentEditingActivityId ? 'PUT' : 'POST', body: formData });
                const payload = await response.json();
                if (!response.ok) { showError(payload.error || 'Erro ao salvar atividade'); return; }
                showSuccess(currentEditingActivityId ? 'Atividade atualizada!' : 'Atividade registrada!');
                closeActivityModal();
                await Promise.all([loadActivities(), loadDashboard(), loadAgenda()]);
                if (!currentEditingActivityId && payload.commitments_created?.length) {
                    await askOutlookForCommitments(payload.commitments_created);
                }
            } catch (error) {
                showError('Erro ao salvar atividade: ' + error.message);
            }
        }


        let messageTemplates = [];
        let uiConfig = { iata_video_path: '/videos/TocaVideo.mp4' };
        let wikiEntries = [];
        let wikiDocuments = [];
        let accountsCache = [];

        function formatMoneyFromCents(cents) {
            const n = Number(cents || 0) / 100;
            return n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
        }

        function formatCompactCurrencyFromCents(cents) {
            const value = Number(cents || 0) / 100;
            if (!Number.isFinite(value) || value === 0) return 'R$0';
            const abs = Math.abs(value);
            let scaled = value;
            let suffix = '';
            if (abs >= 1_000_000_000) { scaled = value / 1_000_000_000; suffix = 'B'; }
            else if (abs >= 1_000_000) { scaled = value / 1_000_000; suffix = 'M'; }
            else if (abs >= 1_000) { scaled = value / 1_000; suffix = 'k'; }
            if (!suffix) return formatMoneyFromCents(cents);
            const rounded = Math.floor(scaled * 10) / 10;
            const oneDecimal = Math.abs(rounded % 1) > 0.001;
            const numStr = oneDecimal ? String(rounded).replace('.', '.') : String(Math.trunc(rounded));
            return `R$${numStr}${suffix}`;
        }

        async function loadUiConfig() {
            const response = await fetch(`${API_BASE}/config/ui`);
            if (response.ok) {
                uiConfig = await response.json();
                const src = document.getElementById('iataVideoSource');
                const vid = document.getElementById('iataVideoPlayer');
                if (src && vid && uiConfig.iata_video_path) { src.src = uiConfig.iata_video_path; vid.load(); }
            }
        }

        // ── Tema de Cores ──────────────────────────────────────────────────────
        function applyTheme(theme) {
            const el = document.documentElement;
            if (!theme || theme === 'verde-classico') {
                el.removeAttribute('data-theme');
            } else {
                el.setAttribute('data-theme', theme);
            }
            try { localStorage.setItem('toca_theme', theme || 'verde-classico'); } catch(e) {}
            window._currentTheme = theme || 'verde-classico';
            document.querySelectorAll('.theme-option-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.theme === (theme || 'verde-classico'));
            });
            // Troca de logo por tema (pearl e blue-space têm logos próprios)
            const isPearl = theme === 'baby-pink' || theme === 'white-pearl';
            const isBlueSpace = theme === 'blue-space';
            const logoExpanded  = document.querySelector('.sidebar-logo-expanded');
            const logoCollapsed = document.querySelector('.sidebar-logo-collapsed');
            if (logoExpanded) {
                logoExpanded.src = isBlueSpace ? '/logo-toca-blue-space.png'
                    : isPearl ? '/logo-coelho-pearl.png' : '/logo-coelho.png';
            }
            if (logoCollapsed) {
                logoCollapsed.src = isBlueSpace ? '/images/favicon-toca-blue-space.png'
                    : isPearl ? '/images/favicon-toca-pearl.png' : '/images/favicon-toca.png';
            }
        }

        async function loadThemeConfig() {
            try {
                const res = await fetch(`${API_BASE}/config/theme`);
                if (res.ok) {
                    const data = await res.json();
                    applyTheme(data.theme || 'verde-classico');
                }
            } catch(e) { /* mantém tema atual do localStorage */ }
        }

        async function selectTheme(theme) {
            applyTheme(theme);
            const statusEl = document.getElementById('themeStatus');
            if (statusEl) statusEl.textContent = 'Salvando...';
            try {
                const res = await fetch(`${API_BASE}/config/theme`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ theme })
                });
                if (res.ok) {
                    if (statusEl) { statusEl.textContent = 'Tema salvo com sucesso!'; setTimeout(() => { if(statusEl) statusEl.textContent = ''; }, 2000); }
                } else {
                    if (statusEl) statusEl.textContent = 'Erro ao salvar o tema.';
                }
            } catch(e) {
                if (statusEl) statusEl.textContent = 'Erro ao salvar o tema.';
            }
        }

        async function loadMessageTemplates() {
            const response = await fetch(`${API_BASE}/config/templates`);
            if (response.ok) messageTemplates = await response.json();
            renderTemplateList();
        }

        function renderTemplateList() {
            const el = document.getElementById('templateList');
            if (!el) return;
            if (!messageTemplates.length) { el.innerHTML = '<div style="color:#6b7280;">Nenhuma MSG padrão cadastrada.</div>'; return; }
            el.innerHTML = messageTemplates.map(t => `<div class="rule-item"><div><strong>${escapeHtml(t.title)}</strong><div style="font-size:12px;color:#6b7280;">${t.available_whatsapp?'<i class="fab fa-whatsapp"></i>':''} ${t.available_email?'<i class="fas fa-envelope"></i>':''}</div></div><div><button class="btn btn-secondary btn-small" onclick="editTemplate(${t.id})"><i class="fas fa-edit"></i></button><button class="btn btn-danger btn-small" onclick="deleteTemplate(${t.id})"><i class="fas fa-trash"></i></button></div></div>`).join('');
        }

        async function saveMessageTemplate(event) {
            event.preventDefault();
            const id = document.getElementById('templateId').value;
            const payload = {
                title: document.getElementById('templateTitle').value.trim(),
                description: document.getElementById('templateDescription').value.trim(),
                available_whatsapp: document.getElementById('templateWhatsapp').checked,
                available_email: document.getElementById('templateEmail').checked
            };
            const url = id ? `${API_BASE}/config/templates/${id}` : `${API_BASE}/config/templates`;
            const method = id ? 'PUT' : 'POST';
            const response = await fetch(url, { method, headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
            if (!response.ok) return showError('Erro ao salvar MSG padrão');
            document.getElementById('templateId').value='';
            document.getElementById('templateTitle').value='';
            document.getElementById('templateDescription').value='';
            document.getElementById('templateWhatsapp').checked=true;
            document.getElementById('templateEmail').checked=true;
            await loadMessageTemplates();
            showSuccess('MSG padrão salva');
        }

        function editTemplate(id) {
            const t = messageTemplates.find(v => Number(v.id)===Number(id));
            if (!t) return;
            document.getElementById('templateId').value = t.id;
            document.getElementById('templateTitle').value = t.title || '';
            document.getElementById('templateDescription').value = t.description || '';
            document.getElementById('templateWhatsapp').checked = Number(t.available_whatsapp) === 1;
            document.getElementById('templateEmail').checked = Number(t.available_email) === 1;
        }

        async function deleteTemplate(id) {
            const response = await fetch(`${API_BASE}/config/templates/${id}`, { method:'DELETE' });
            if (!response.ok) return showError('Erro ao excluir MSG padrão');
            await loadMessageTemplates();
            showSuccess('MSG padrão removida');
        }

        function insertTemplateVar(varText) {
            const ta = document.getElementById('templateDescription');
            if (!ta) return;
            const start = ta.selectionStart, end = ta.selectionEnd;
            const val = ta.value;
            ta.value = val.slice(0, start) + varText + val.slice(end);
            ta.selectionStart = ta.selectionEnd = start + varText.length;
            ta.focus();
        }

        function renderTemplateDrawer(channel, targetId) {
            const filtered = messageTemplates.filter(t => channel === 'whatsapp' ? Number(t.available_whatsapp) === 1 : Number(t.available_email) === 1);
            if (!filtered.length) return '<div style="font-size:12px;color:#6b7280;">Nenhum conteúdo padrão para este canal.</div>';
            return filtered.map(t => `<button class="btn btn-secondary btn-small" style="margin-bottom:8px; width:100%; text-align:left;" onclick="applyTemplateToField(${t.id}, '${targetId}')">${escapeHtml(t.title)}</button>`).join('');
        }

        function applyTemplateToField(id, targetId) {
            const t = messageTemplates.find(v => Number(v.id)===Number(id));
            if (!t) return;
            const el = document.getElementById(targetId);
            if (el) el.value = t.description || '';
        }

        openWhatsAppMessageModal = function(clientId) {
            const client = clients.find(c => c.id === clientId);
            if (!client || !client.phone) return openMissingContactModal();
            const prefDesktop = getWhatsAppPreference() === 'desktop';
            const wppTags = ['<nome do contato>', '<sobrenome>', '<conta>', '<cargo>', '<area de atuacao>'];
            const tagsBar = `<div style="display:flex; flex-wrap:wrap; gap:5px; margin-bottom:10px; padding:7px 10px; background:rgba(236,253,245,.6); border:1px solid rgba(16,185,129,.25); border-radius:8px; align-items:center;">
                <span style="font-size:11px; font-weight:700; color:#065f46; white-space:nowrap; margin-right:2px; text-transform:uppercase; letter-spacing:.04em;">Chaves:</span>
                ${wppTags.map(t => `<button type="button" class="btn btn-secondary btn-small" onclick="insertMergeTagInto('whatsMessageText','${t.replace(/'/g, "\\'")}')" style="font-size:11px;">${escapeHtml(t)}</button>`).join('')}
                <span style="font-size:11px; color:#6b7280; margin-left:4px;">→ substituídas pelo dado real ao enviar</span>
            </div>`;
            let html = `<div class="modal active" id="whatsAppModal">`;
            html += '<div class="modal-content" style="max-width: 760px; display:flex; gap:16px;">';
            html += `<div style="flex:1;">
                <h2 style="margin-bottom:8px; color:#047857;"><i class="fab fa-whatsapp"></i> Mensagem WhatsApp — ${escapeHtml(client.name || '-')}</h2>
                <div style="display:flex; gap:10px; align-items:center; padding:10px; border:1px solid rgba(16,185,129,.2); border-radius:10px; margin-bottom:10px; background:rgba(16,185,129,.06);">
                    <img src="${client.photo_url || '/logo-coelho.png'}" style="width:44px; height:44px; border-radius:999px; object-fit:cover; border:2px solid rgba(16,185,129,.35);">
                    <div>
                        <div style="font-weight:700; color:#065f46;">${escapeHtml(client.name || '-')}</div>
                        <div style="font-size:12px; color:#6b7280;">${escapeHtml(client.company || '-')}</div>
                        <div style="font-size:12px; color:#9ca3af;">${escapeHtml(client.position || '-')}${client.area_of_activity ? ' (' + escapeHtml(client.area_of_activity) + ')' : ''}</div>
                    </div>
                </div>
                ${tagsBar}
                <div class="form-group"><label>Mensagem</label><textarea id="whatsMessageText" rows="8" placeholder="Olá &lt;nome do contato&gt;! Tudo bem?"></textarea></div>
                <label style="display:flex; align-items:center; gap:8px; font-size:13px; color:#4b5563; margin-bottom:12px;">
                    <input type="checkbox" id="whatsUseDesktop" ${prefDesktop ? 'checked' : ''}> Abrir no WhatsApp Desktop (sem reload do Web)
                </label>
                <div style="display:flex; gap:10px; justify-content:flex-end; flex-wrap:wrap;">
                    <button class="btn btn-secondary" onclick="closeWhatsAppModal()">Cancelar</button>
                    <button class="btn btn-secondary" onclick="scheduleFromDashboardWhatsApp(${client.id})" title="Agendar o envio para uma data e horário"><i class="fas fa-clock"></i> Agendar</button>
                    <button class="btn btn-primary" onclick="openWhatsAppWeb(${client.id})">Enviar mensagem</button>
                </div>
            </div>`;
            html += `<div style="width:240px; border-left:1px solid rgba(16,185,129,.2); padding-left:12px;"><h4 style="color:#047857; margin-bottom:8px;">Conteúdo Padrão</h4>${renderTemplateDrawer('whatsapp','whatsMessageText')}</div>`;
            html += '</div></div>';
            document.body.insertAdjacentHTML('beforeend', html);
        }

        openEmailDraftModal = function(clientId) {
            const client = clients.find(c => c.id === clientId);
            if (!client || !client.email) return openMissingContactModal();
            const emailTags = ['<nome do contato>', '<conta>', '<cargo>', '<area de atuacao>', '<email>'];
            const tagsBar = `<div style="display:flex; flex-wrap:wrap; gap:5px; margin-bottom:10px; padding:7px 10px; background:rgba(236,253,245,.6); border:1px solid rgba(16,185,129,.25); border-radius:8px; align-items:center;">
                <span style="font-size:11px; font-weight:700; color:#065f46; white-space:nowrap; margin-right:2px; text-transform:uppercase; letter-spacing:.04em;">Chaves:</span>
                ${emailTags.map(t => `<button type="button" class="btn btn-secondary btn-small" onclick="insertEmailDraftMergeTag('${t.replace(/'/g, "\\'")}')" style="font-size:11px;">${escapeHtml(t)}</button>`).join('')}
                <span style="font-size:11px; color:#6b7280; margin-left:4px;">→ clique no campo antes de inserir</span>
            </div>`;
            let html = `<div class="modal active" id="emailDraftModal">`;
            html += '<div class="modal-content" style="max-width: 760px; display:flex; gap:16px;">';
            html += `<div style="flex:1;">
                <h2 style="margin-bottom:8px; color:#047857;"><i class="fas fa-envelope"></i> Novo e-mail — ${escapeHtml(client.name || '-')}</h2>
                <div style="display:flex; gap:10px; align-items:center; padding:10px; border:1px solid rgba(16,185,129,.2); border-radius:10px; margin-bottom:10px; background:rgba(16,185,129,.06);">
                    <img src="${client.photo_url || '/logo-coelho.png'}" style="width:44px; height:44px; border-radius:999px; object-fit:cover; border:2px solid rgba(16,185,129,.35);">
                    <div>
                        <div style="font-weight:700; color:#065f46;">${escapeHtml(client.name || '-')}</div>
                        <div style="font-size:12px; color:#6b7280;">${escapeHtml(client.company || '-')}</div>
                        <div style="font-size:12px; color:#9ca3af;">${escapeHtml(client.position || '-')}${client.area_of_activity ? ' (' + escapeHtml(client.area_of_activity) + ')' : ''}</div>
                    </div>
                </div>
                ${tagsBar}
                <div class="form-group"><label>Assunto</label><input id="emailDraftSubject" type="text" placeholder="Ex: Olá &lt;nome do contato&gt;, oportunidade para &lt;conta&gt;"></div>
                <div class="form-group"><label>Mensagem</label><textarea id="emailDraftBody" rows="8"></textarea></div>
                <div style="display:flex; gap:10px; justify-content:flex-end; flex-wrap:wrap;">
                    <button class="btn btn-secondary" onclick="closeEmailDraftModal()">Cancelar</button>
                    <button class="btn btn-secondary" onclick="scheduleFromDashboardEmail(${client.id})" title="Agendar o envio para uma data e horário"><i class="fas fa-clock"></i> Agendar</button>
                    <button class="btn btn-primary" onclick="openOutlookDraft(${client.id})">Abrir no Outlook</button>
                </div>
            </div>`;
            html += `<div style="width:240px; border-left:1px solid rgba(16,185,129,.2); padding-left:12px;"><h4 style="color:#047857; margin-bottom:8px;">Conteúdo Padrão</h4>${renderTemplateDrawer('email','emailDraftBody')}</div>`;
            html += '</div></div>';
            document.body.insertAdjacentHTML('beforeend', html);
        }

        openOutlookDraft = async function(clientId) {
            const client = clients.find(c => c.id === clientId);
            if (!client || !client.email) return openMissingContactModal();

            const rawSubject = document.getElementById('emailDraftSubject')?.value?.trim() || '';
            const rawBody    = document.getElementById('emailDraftBody')?.value?.trim() || '';
            // Substitui chaves de merge pelos dados reais do contato antes de abrir o Outlook
            const subject = applyMergeFields(rawSubject, client);
            const body    = applyMergeFields(rawBody, client);
            const cc = '';

            const queryParts = [
                `to=${encodeURIComponent(client.email)}`,
                `subject=${encodeURIComponent(subject)}`,
                `body=${encodeURIComponent(body)}`
            ];
            if (cc) queryParts.push(`cc=${encodeURIComponent(cc)}`);

            const outlookUrl = `https://outlook.office.com/mail/deeplink/compose?${queryParts.join('&')}`;
            emailWindowRef = window.open(outlookUrl, '_blank');
            askRegisterActivityFromCommunication(clientId, 'Email', body);
            closeEmailDraftModal();
        }

        async function loadAccounts() {
            const response = await fetch(`${API_BASE}/accounts`);
            const accounts = response.ok ? await response.json() : [];
            accountsCache = accounts;
            const el = document.getElementById('accountsContent');
            if (!el) return;
            if (!accounts.length) { el.innerHTML = '<div class="empty-state"><p>Nenhuma conta cadastrada.</p></div>'; return; }
            // Score de multithreading (Bloco 10) — badge de risco de concentração
            let threadScores = {};
            try { threadScores = await (await fetch(`${API_BASE}/accounts/thread-scores`)).json(); } catch (e) { threadScores = {}; }
            const showTerminated = document.getElementById('showTerminatedPresences')?.checked ?? false;
            el.innerHTML = `<div style="display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:12px;">${accounts.map(a => {
                const visiblePresences = (a.presences||[]).filter(p => showTerminated || !isPresenceTerminated(p));
                const badges = visiblePresences.map(p=>`<span onclick="event.stopPropagation();openPresenceModal(${a.id},${p.id})" style="${presenceBadgeStyle(p)}">${escapeHtml(p.delivery_name)}</span>`).join('');
                const ts = threadScores[String(a.id)];
                const riskFlag = ts && ts.single_threaded
                    ? `<span class="toca-risk-flag" onclick="event.stopPropagation();">!
                           <span class="toca-risk-tooltip"><b>Risco de concentração</b><br>
                           Esta conta é sustentada por <b>${ts.active_contacts} contato(s) ativo(s)</b>.
                           Se essa pessoa sair da empresa, o relacionamento inteiro fica exposto.
                           Mapeie mais decisores${(ts.missing_levels||[]).length ? ` — níveis ausentes: <b>${escapeHtml(ts.missing_levels.join(', '))}</b>` : ''}.
                           Use o Account Planning para encontrar novos contatos.</span>
                       </span>`
                    : '';
                return `<div onclick="openAccountViewModal(${a.id})" style="cursor:pointer; padding:14px; border-radius:16px; background:rgba(255,255,255,.45); border:1px solid rgba(16,185,129,.35); backdrop-filter:blur(8px); box-shadow:0 10px 24px rgba(4,120,87,.14);"><div style="display:flex; gap:10px; align-items:center;"><img src="${a.logo_url || '/logo-coelho.png'}" style="width:42px; height:42px; border-radius:12px; object-fit:contain; background:#fff; border:1px solid rgba(16,185,129,.2);"><div style="flex:1;"><div style="font-weight:700; color:#e2dfd5; display:flex; align-items:center; gap:6px;">${escapeHtml(a.name)}${riskFlag}</div><div style="font-size:12px; color:rgba(226,223,213,0.7);">${Number(a.is_target)===1?'Target':'Não target'}</div></div></div><div style="margin-top:10px; display:flex; flex-wrap:wrap; gap:6px;">${badges}</div></div>`;
            }).join('')}</div>`;
        }

        function formatIntegerPtBr(value) {
            const n = Number(value);
            if (!Number.isFinite(n)) return '-';
            return n.toLocaleString('pt-BR');
        }

        function getPositionGroupSortKey(position) {
            const normalized = String(position || '').toLowerCase().trim();
            if (!normalized) return { g: 9999, p: 9999 };
            for (let gi = 0; gi < positionGroupings.length; gi += 1) {
                const positions = positionGroupings[gi].positions || [];
                for (let pi = 0; pi < positions.length; pi += 1) {
                    if (String(positions[pi] || '').toLowerCase().trim() === normalized) {
                        return { g: gi, p: pi };
                    }
                }
            }
            return { g: 9998, p: 9998 };
        }

        function sortAccountContactsByRole(contacts) {
            return [...(contacts || [])].sort((a, b) => {
                const rankDiff = getCompanyImportanceRank(a.position) - getCompanyImportanceRank(b.position);
                if (rankDiff !== 0) return rankDiff;
                return String(a.name || '').localeCompare(String(b.name || ''), 'pt-BR');
            });
        }

        async function openAccountViewModal(accountId) {
            const account = await (await fetch(`${API_BASE}/accounts/${accountId}`)).json();
            if (!account || account.error) return showError('Conta não encontrada');
            const sortedContacts = sortAccountContactsByRole(account.contacts || []);
            let html = `<div class="modal active" id="accountViewModal" onclick="if(event.target===this) closeAccountViewModal()"><div class="modal-content" style="max-width:860px;">`;
            html += `<div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px;"><div><h2 style="color:#047857; margin-bottom:4px;">${escapeHtml(account.name)}</h2><div style="color:#6b7280; font-size:13px;">${Number(account.is_target)===1?'Target':'Não target'} • ${escapeHtml(account.sector || 'Sem setor')}</div></div><div style="display:flex; flex-direction:column; align-items:flex-end; gap:8px;"><img src="${account.logo_url || '/logo-coelho.png'}" style="width:120px; height:88px; object-fit:contain; background:#fff; border-radius:10px; border:1px solid rgba(16,185,129,.25);"><div style="display:flex; gap:8px;"><button class="btn btn-primary btn-small" onclick="openAccountModal(${account.id})"><i class="fas fa-edit"></i> Editar Conta</button><button class="btn btn-danger btn-small" onclick="deleteAccount(${account.id}, ${escapeHtml(JSON.stringify(account.name))})"><i class="fas fa-trash"></i> Excluir</button><button class="btn btn-secondary btn-small" onclick="closeAccountViewModal()">Fechar</button></div></div></div>`;
            html += `<div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:14px;"><div class="profile-field"><div class="profile-field-label">Nome da conta</div><div class="profile-field-value">${escapeHtml(account.name || '-')}</div></div><div class="profile-field"><div class="profile-field-label">Setor</div><div class="profile-field-value">${escapeHtml(account.sector || '-')}</div></div><div class="profile-field"><div class="profile-field-label">Faturamento Médio Anual</div><div class="profile-field-value">${account.average_revenue_cents?formatCompactCurrencyFromCents(account.average_revenue_cents):'-'}</div></div><div class="profile-field"><div class="profile-field-label">Quantidade de Profissionais</div><div class="profile-field-value">${formatIntegerPtBr(account.professionals_count)}</div></div><div class="profile-field"><div class="profile-field-label">Presença Global</div><div class="profile-field-value">${escapeHtml(account.global_presence || '-')}</div></div><div class="profile-field"><div class="profile-field-label">Ponto Focal Principal</div><div class="profile-field-value">${sortedContacts.filter(c => (account.main_contact_ids||[]).includes(c.id)).map(c=>escapeHtml(c.name)).join(', ') || '-'}</div></div></div>`;
            const mensalPresences = (account.presences || []).filter(p => (p.billing_type || 'Mensal') === 'Mensal' && !isPresenceTerminated(p));
            const unicoPresences = (account.presences || []).filter(p => p.billing_type === 'Unico' && !isPresenceTerminated(p));
            const totalMonthlyCents = mensalPresences.reduce((acc, p) => acc + Number(p.current_revenue_cents || 0), 0);
            const totalUnicoCents = unicoPresences.reduce((acc, p) => acc + Number(p.current_revenue_cents || 0), 0);
            const presenceButtons = (account.presences||[]).map(p=>{const terminated=isPresenceTerminated(p);const btnStyle=terminated?'border-radius:999px;font-weight:700;background:linear-gradient(135deg,#fed7aa,#fb923c);color:#7c2d12;border:1px solid rgba(255,255,255,0.25);box-shadow:0 4px 12px rgba(251,146,60,0.3);':'border-radius:999px;font-weight:700;';return `<button class='btn ${terminated?'':'btn-secondary'} btn-small' style='${btnStyle}' onclick='openPresenceModal(${account.id}, ${p.id})'>${escapeHtml(p.delivery_name)}</button>`;}).join('');
            html += `<div style="margin-top:14px;"><h4 style="color:#065f46; margin-bottom:8px;">Serviços Stefanini</h4><div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:8px;"><div class='rule-item' style='display:flex; justify-content:space-between; align-items:center; gap:8px; background:rgba(16,185,129,.12);'><strong>Total Mensal</strong><strong>${formatCompactCurrencyFromCents(totalMonthlyCents)}</strong></div><div class='rule-item' style='display:flex; justify-content:space-between; align-items:center; gap:8px; background:rgba(99,102,241,.12);'><strong style="color:#4338ca;">Faturamento Pontual</strong><strong style="color:#4338ca;">${formatCompactCurrencyFromCents(totalUnicoCents)}</strong></div></div>${(account.presences||[]).length?`<div style='display:flex; flex-wrap:wrap; gap:8px;'>${presenceButtons}</div>`:'<div style="color:#6b7280;">Nenhum serviço cadastrado.</div>'}</div>`;
            html += `<div style="margin-top:14px; display:grid; grid-template-columns:1fr 1fr; gap:10px;"><div><h4 style="color:#065f46; margin-bottom:8px;">Contatos da Conta</h4>${sortedContacts.length?`<div style='display:grid; grid-template-columns:1fr 1fr; gap:8px;'>${sortedContacts.map(c=>`<div class='history-item' style='margin-bottom:0; cursor:pointer;' onclick='closeAccountViewModal(); openProfileModal(${c.id})'><div class='history-meta'>${escapeHtml(c.name)}</div><div style='font-size:12px;color:#6b7280;'>${escapeHtml(c.position || '-')}</div><div style='display:flex; align-items:center; gap:8px; margin-top:5px;'>${c.email ? `<span style='font-size:11px; color:#6b7280;'><i class='fas fa-envelope' style='margin-right:4px;'></i>${escapeHtml(c.email)}</span>` : ''}${c.phone ? `<span style='font-size:11px; color:#6b7280;'><i class='fas fa-phone' style='margin-right:4px;'></i>${escapeHtml(c.phone)}</span>` : ''}${c.linkedin ? `<a href='${escapeHtml(c.linkedin)}' target='_blank' rel='noopener noreferrer' title='LinkedIn' onclick='event.stopPropagation()' style='font-size:13px; color:#0a66c2;'><i class='fab fa-linkedin'></i></a>` : ''}</div></div>`).join('')}</div>`:'<div style="color:#6b7280;">Sem contatos.</div>'}</div><div><div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;"><h4 style="color:#065f46; margin:0;">Histórico de Atividades</h4><button class="btn btn-primary btn-small" style="padding:2px 10px; border-radius:999px; font-size:18px; line-height:1; font-weight:700;" onclick="openAccountActivityModal(${account.id})" title="Registrar atividade da conta">+</button></div><div id="accountActivitiesWrap" style="max-height:230px; overflow:auto;"><div style="color:#6b7280;">Carregando...</div></div></div></div>`;
            html += '</div></div>';
            document.body.insertAdjacentHTML('beforeend', html);
            await refreshAccountActivitiesWrap(accountId, account);
        }

        async function refreshAccountActivitiesWrap(accountId, account) {
            const wrap = document.getElementById('accountActivitiesWrap');
            if (!wrap) return;
            try {
                // Carregar atividades de contatos vinculados à conta
                const [rContacts, rAccount] = await Promise.all([
                    fetch(`${API_BASE}/atividades`),
                    fetch(`${API_BASE}/accounts/${accountId}/activities`)
                ]);
                const acts = rContacts.ok ? await rContacts.json() : [];
                const accountGenericActs = rAccount.ok ? await rAccount.json() : [];
                const contactIds = new Set((account.contacts || []).map(c => Number(c.id)));
                // Atividades de contatos da conta
                const contactActs = acts
                    .filter(a => contactIds.has(Number(a.client_id)))
                    .map(a => ({
                        _date: new Date(a.activity_date || a.created_at),
                        _dateStr: (a.activity_date || '').slice(0, 10),
                        _label: a.client_name || (account.contacts || []).find(c => Number(c.id) === Number(a.client_id))?.name || '-',
                        _type: 'contact',
                        _id: null,
                        description: a.description || a.information || '-'
                    }));
                // Atividades genéricas da conta
                const genericActs = accountGenericActs.map(a => ({
                    _date: new Date(a.activity_date || a.created_at),
                    _dateStr: (a.activity_date || '').slice(0, 10),
                    _label: 'Conta',
                    _type: 'account',
                    _id: a.id,
                    description: a.description || '-'
                }));
                // Mesclar e ordenar por data decrescente
                const allActs = [...contactActs, ...genericActs]
                    .sort((a, b) => b._date - a._date)
                    .slice(0, 50);
                if (allActs.length) {
                    wrap.innerHTML = allActs.map(a => {
                        const badge = a._type === 'account'
                            ? `<span style="display:inline-block; background:rgba(16,185,129,.18); color:#065f46; border-radius:999px; font-size:10px; font-weight:700; padding:1px 7px; margin-left:4px;">Conta</span>`
                            : '';
                        const deleteBtn = a._type === 'account' && a._id
                            ? `<button class="btn btn-danger btn-small" style="padding:1px 7px; font-size:11px; margin-top:4px;" onclick="deleteAccountActivityItem(${accountId}, ${a._id})"><i class="fas fa-trash"></i></button>`
                            : '';
                        return `<div class='history-item' style='margin-bottom:8px;'><div class='history-meta'>${formatDateBr(a._dateStr)} • ${escapeHtml(a._label)}${badge}</div><div>${escapeHtml(a.description)}</div>${deleteBtn}</div>`;
                    }).join('');
                } else {
                    wrap.innerHTML = '<div style="color:#6b7280;">Nenhuma atividade para esta conta.</div>';
                }
            } catch (e) {
                wrap.innerHTML = '<div style="color:#6b7280;">Não foi possível carregar atividades.</div>';
            }
        }

        async function deleteAccountActivityItem(accountId, activityId) {
            if (!await uiConfirm('Excluir esta atividade da conta?', 'Excluir Atividade')) return;
            const r = await fetch(`${API_BASE}/accounts/${accountId}/activities/${activityId}`, { method: 'DELETE' });
            if (!r.ok) return showError('Erro ao excluir atividade');
            const account = await (await fetch(`${API_BASE}/accounts/${accountId}`)).json();
            await refreshAccountActivitiesWrap(accountId, account);
        }

        function openAccountActivityModal(accountId) {
            const today = new Date().toISOString().slice(0, 10);
            let html = `<div class="modal active" id="accountActivityModal" onclick="if(event.target===this) closeAccountActivityModal()">`;
            html += `<div class="modal-content" style="max-width:480px;">`;
            html += `<h2 style="color:#047857; margin-bottom:12px;">Registrar Atividade da Conta</h2>`;
            html += `<div class="form-group"><label>Data</label><input type="date" id="accountActivityDate" value="${today}"></div>`;
            html += `<div class="form-group"><label>Descrição *</label><textarea id="accountActivityDesc" rows="5" placeholder="Descreva o que aconteceu, reuniões, contatos, percepções..."></textarea></div>`;
            html += `<div style="display:flex; gap:10px; justify-content:flex-end;"><button class="btn btn-secondary" onclick="closeAccountActivityModal()">Cancelar</button><button class="btn btn-primary" onclick="saveAccountActivity(${accountId})">Salvar</button></div>`;
            html += `</div></div>`;
            document.body.insertAdjacentHTML('beforeend', html);
            setTimeout(() => document.getElementById('accountActivityDesc')?.focus(), 80);
        }

        function closeAccountActivityModal() {
            const m = document.getElementById('accountActivityModal');
            if (m) m.remove();
        }

        async function saveAccountActivity(accountId) {
            const description = document.getElementById('accountActivityDesc')?.value?.trim() || '';
            const activity_date = document.getElementById('accountActivityDate')?.value || '';
            if (!description) return showError('Informe a descrição da atividade');
            const payload = { description };
            if (activity_date) payload.activity_date = activity_date;
            const r = await fetch(`${API_BASE}/accounts/${accountId}/activities`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!r.ok) return showError('Erro ao registrar atividade');
            closeAccountActivityModal();
            showSuccess('Atividade registrada com sucesso');
            const account = await (await fetch(`${API_BASE}/accounts/${accountId}`)).json();
            await refreshAccountActivitiesWrap(accountId, account);
        }

        function closeAccountViewModal(){ const m=document.getElementById('accountViewModal'); if(m)m.remove(); }

        async function deleteAccount(accountId, accountName) {
            const nome = accountName || 'esta conta';
            if (!await uiConfirm(`Deseja realmente excluir a conta "${nome}"? Todos os contatos, atividades e dados serão arquivados e poderão ser restaurados depois em "Contas Arquivadas".`, 'Excluir Conta')) return;
            const r = await fetch(`${API_BASE}/accounts/${accountId}`, { method: 'DELETE' });
            if (!r.ok) {
                const data = await r.json().catch(() => ({}));
                return showError(data.error || 'Erro ao excluir conta');
            }
            closeAccountViewModal();
            showSuccess('Conta arquivada e excluída com sucesso');
            await loadAccounts();
        }

        async function openArchivedAccountsModal() {
            const r = await fetch(`${API_BASE}/accounts/archives`);
            const archives = r.ok ? await r.json() : [];
            let html = `<div class="modal active" id="archivedAccountsModal" onclick="if(event.target===this) closeArchivedAccountsModal()"><div class="modal-content" style="max-width:640px;">`;
            html += `<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;"><h2 style="color:#047857; margin:0;"><i class="fas fa-box-archive"></i> Contas Arquivadas</h2><button class="btn btn-secondary btn-small" onclick="closeArchivedAccountsModal()">Fechar</button></div>`;
            if (!archives.length) {
                html += `<div style="color:#6b7280;">Nenhuma conta arquivada.</div>`;
            } else {
                html += archives.map(a => `<div class='history-item' style='display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:8px;'><div><div class='history-meta'>${escapeHtml(a.account_name)}</div><div style='font-size:12px; color:#6b7280;'>Arquivada em ${formatDateBr((a.archived_at||'').slice(0,10))} • ${a.contacts_count||0} contato(s) • ${a.activities_count||0} atividade(s)</div></div><div style='display:flex; gap:6px;'><button class='btn btn-primary btn-small' onclick='restoreAccountArchive(${a.id})'><i class="fas fa-rotate-left"></i> Restaurar</button><button class='btn btn-danger btn-small' onclick='deleteAccountArchive(${a.id})'><i class="fas fa-trash"></i></button></div></div>`).join('');
            }
            html += `</div></div>`;
            document.body.insertAdjacentHTML('beforeend', html);
        }

        function closeArchivedAccountsModal(){ const m=document.getElementById('archivedAccountsModal'); if(m)m.remove(); }

        async function restoreAccountArchive(archiveId) {
            if (!await uiConfirm('Restaurar esta conta com todos os seus contatos e atividades?', 'Restaurar Conta')) return;
            const r = await fetch(`${API_BASE}/accounts/archives/${archiveId}/restore`, { method: 'POST' });
            const data = await r.json().catch(() => ({}));
            if (!r.ok) return showError(data.error || 'Erro ao restaurar conta');
            showSuccess('Conta restaurada com sucesso');
            closeArchivedAccountsModal();
            await loadAccounts();
        }

        async function deleteAccountArchive(archiveId) {
            if (!await uiConfirm('Excluir permanentemente esta conta arquivada? Esta ação não pode ser desfeita.', 'Excluir Arquivo')) return;
            const r = await fetch(`${API_BASE}/accounts/archives/${archiveId}`, { method: 'DELETE' });
            if (!r.ok) return showError('Erro ao excluir arquivo');
            showSuccess('Arquivo excluído');
            closeArchivedAccountsModal();
            await openArchivedAccountsModal();
        }

        function toggleMainContactSelection(clientId) {
            const hidden = document.getElementById('accountMainContactsHidden');
            const selected = new Set((hidden?.value || '').split(',').filter(Boolean));
            const key = String(clientId);
            if (selected.has(key)) selected.delete(key); else selected.add(key);
            if (hidden) hidden.value = [...selected].join(',');
            const item = document.querySelector(`[data-main-contact='${clientId}']`);
            if (item) {
                item.classList.toggle('active', selected.has(key));
                item.style.background = selected.has(key) ? 'rgba(16,185,129,.18)' : 'transparent';
                item.style.borderColor = selected.has(key) ? 'rgba(16,185,129,.45)' : 'rgba(16,185,129,.25)';
            }
        }

        async function openAccountModal(accountId=null) {
            closeAccountViewModal();
            const support = await (await fetch(`${API_BASE}/accounts/support-data`)).json();
            const account = accountId ? await (await fetch(`${API_BASE}/accounts/${accountId}`)).json() : null;
            const companyOptions = (support.companies || []).map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
            const sectorOptions = (support.sectors || []).map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
            const logoSrc = account?.logo_url || '/logo-coelho.png';
            const mainSelected = (account?.main_contact_ids || []).map(String).join(',');
            const sortedContacts = sortAccountContactsByRole(account?.contacts || []);
            const contactsList = sortedContacts.map(c => {
                const active = (account?.main_contact_ids || []).includes(c.id);
                return `<button type="button" data-main-contact="${c.id}" onclick="toggleMainContactSelection(${c.id})" style="padding:8px 10px; border-radius:10px; border:1px solid ${active?'rgba(16,185,129,.45)':'rgba(16,185,129,.25)'}; background:${active?'rgba(16,185,129,.18)':'transparent'}; color:#065f46; cursor:pointer; text-align:left;">${escapeHtml(c.name)}</button>`;
            }).join('') || '<div style="color:#6b7280; font-size:13px;">Sem contatos nesta conta.</div>';

            let html = `<div class="modal active" id="accountModal" onclick="if(event.target===this) closeAccountModal()"><div class="modal-content" style="max-width:860px;"><h2 style="color:#047857;">${account?'Editar':'Nova'} Conta</h2><form id="accountForm" onsubmit="saveAccount(event, ${accountId||'null'})"><div style="display:grid; grid-template-columns: 1.4fr .9fr; gap:14px; align-items:start;"><div><div class="form-group"><label>Nome da Conta</label><input list="accountCompanies" name="name" required value="${escapeHtml(account?.name||'')}"><datalist id="accountCompanies">${companyOptions}</datalist></div><div class="form-group"><label>Setor</label><input list="accountSectors" id="accountSectorInput" name="sector" value="${escapeHtml(account?.sector||'')}"><datalist id="accountSectors">${sectorOptions}</datalist></div><div class="form-group"><label>Target</label><select name="is_target"><option value="0" ${Number(account?.is_target)!==1?'selected':''}>Não</option><option value="1" ${Number(account?.is_target)===1?'selected':''}>Sim</option></select></div></div><div><img id="accountLogoPreview" src="${logoSrc}" style="width:100%; max-width:220px; height:150px; object-fit:contain; background:#fff; border-radius:14px; border:1px solid rgba(16,185,129,.25); display:block; margin-left:auto;"><div style="display:flex; gap:8px; justify-content:flex-end; margin-top:8px;"><label class="btn btn-secondary btn-small" for="accountLogoInput"><i class="fas fa-image"></i> Alterar</label><button type="button" class="btn btn-danger btn-small" onclick="removeAccountLogo()"><i class="fas fa-trash"></i> Excluir</button></div><div style="display:flex; justify-content:flex-end; margin-top:6px;"><button type="button" class="btn btn-auto-mapping btn-small" id="accountAutoFillBtn" onclick="autoFillAccount()"><span class="ai-star-icon">✦</span> AutoFill</button></div><input type="file" id="accountLogoInput" name="logo" accept="image/*" style="display:none;" onchange="previewAccountLogo(event)"><input type="hidden" id="removeAccountLogoFlag" name="remove_logo" value="0"><input type="hidden" id="accountAutoFillLogoUrl" name="autofill_logo_url" value=""></div></div><div class="form-group"><label>Ponto Focal Principal</label><input type="hidden" id="accountMainContactsHidden" value="${mainSelected}"><div style="display:flex; flex-wrap:wrap; gap:8px;">${contactsList}</div></div><div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;"><div class="form-group"><label>Faturamento Médio Anual</label><input name="average_revenue" value="${account?.average_revenue_cents?formatMoneyFromCents(account.average_revenue_cents):''}" placeholder="R$0,00"></div><div class="form-group"><label>Quantidade de Profissionais</label><input name="professionals_count" type="number" min="0" value="${account?.professionals_count||''}"></div></div><div class="form-group"><label>Presença Global</label><select name="global_presence"><option value="">Selecione</option><option ${account?.global_presence==='Brasil'?'selected':''}>Brasil</option><option ${account?.global_presence==='Latam'?'selected':''}>Latam</option><option ${account?.global_presence==='Global'?'selected':''}>Global</option></select></div><div style="display:flex; gap:8px;"><button class="btn btn-secondary" type="button" onclick="closeAccountModal()">Cancelar</button><button class="btn btn-primary" type="submit">Salvar</button></div></form><hr style="margin:16px 0;"><button class="btn btn-primary btn-small" onclick="openPresenceModal(${accountId||'null'})"><i class="fas fa-briefcase"></i> Serviço Stefanini</button><div id="accountPresenceList" style="margin-top:8px; display:flex; flex-direction:column; gap:8px;"><div class='rule-item' style='display:flex; justify-content:space-between; align-items:center; gap:8px; background:rgba(16,185,129,.12);'><strong>Total Mensal</strong><strong>${formatCompactCurrencyFromCents((account?.presences||[]).reduce((acc,p)=>acc+Number(p.current_revenue_cents||0),0))}</strong></div><div style='display:flex; flex-wrap:wrap; gap:8px;'>${(account?.presences||[]).map(p=>`<div style='display:inline-flex; align-items:center; gap:6px;'><button class='btn btn-secondary btn-small' style='border-radius:999px; font-weight:700;' onclick='openPresenceModal(${account.id}, ${p.id})'>${escapeHtml(p.delivery_name)}</button><button class='btn btn-danger btn-small' onclick='deletePresence(${account.id}, ${p.id})'>Excluir</button></div>`).join('')}</div></div></div></div>`;
            document.body.insertAdjacentHTML('beforeend', html);
        }

        function previewAccountLogo(event) {
            const file = event.target.files?.[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (e) => {
                const img = document.getElementById('accountLogoPreview');
                if (img) img.src = e.target.result;
                const flag = document.getElementById('removeAccountLogoFlag');
                if (flag) flag.value = '0';
            };
            reader.readAsDataURL(file);
        }

        function setPastedImageToAccountLogo(blob) {
            const input = document.getElementById('accountLogoInput');
            if (!input || !blob) return;
            const file = new File([blob], `logo_conta_${Date.now()}.png`, { type: blob.type || 'image/png' });
            const dt = new DataTransfer();
            dt.items.add(file);
            input.files = dt.files;
            const reader = new FileReader();
            reader.onload = (e) => {
                const img = document.getElementById('accountLogoPreview');
                if (img) img.src = e.target.result;
                const flag = document.getElementById('removeAccountLogoFlag');
                if (flag) flag.value = '0';
            };
            reader.readAsDataURL(file);
        }

        function removeAccountLogo() {
            const img = document.getElementById('accountLogoPreview');
            const flag = document.getElementById('removeAccountLogoFlag');
            const input = document.getElementById('accountLogoInput');
            if (img) img.src = '/logo-coelho.png';
            if (flag) flag.value = '1';
            if (input) input.value = '';
        }

        function _applyAutoFillResult(payload) {
            const form = document.getElementById('accountForm');
            if (!form) return;
            let filled = [];
            const revenueInput = form.querySelector('[name="average_revenue"]');
            if (revenueInput && payload.average_revenue) { revenueInput.value = payload.average_revenue; filled.push('Faturamento Médio Anual'); }
            const profInput = form.querySelector('[name="professionals_count"]');
            if (profInput && payload.professionals_count !== '' && payload.professionals_count !== null && payload.professionals_count !== undefined) { profInput.value = payload.professionals_count; filled.push('Quantidade de Profissionais'); }
            const presenceSelect = form.querySelector('[name="global_presence"]');
            if (presenceSelect && payload.global_presence) {
                const opt = Array.from(presenceSelect.options).find(o => o.value === payload.global_presence);
                if (opt) { presenceSelect.value = payload.global_presence; filled.push('Presença Global'); }
            }
            if (payload.logo_url) {
                const logoPreview = document.getElementById('accountLogoPreview');
                const logoUrlHidden = document.getElementById('accountAutoFillLogoUrl');
                const removeFlag = document.getElementById('removeAccountLogoFlag');
                if (logoPreview) logoPreview.src = payload.logo_url;
                if (logoUrlHidden) logoUrlHidden.value = payload.logo_url;
                if (removeFlag) removeFlag.value = '0';
                filled.push('Logo');
            }
            if (filled.length === 0) {
                showError('AutoFill não encontrou dados para esta empresa. Verifique se o SAI está configurado em Configurações > Integrações.');
            } else {
                showSuccess(`AutoFill preencheu: ${filled.join(', ')}.`);
            }
        }

        function _setAutoFillProgress(pct, step) {
            const bar = document.getElementById('autoFillProgressBar');
            const stepEl = document.getElementById('autoFillProgressStep');
            if (bar) bar.style.width = Math.max(5, pct) + '%';
            if (stepEl) stepEl.textContent = step || '';
        }

        async function autoFillAccount() {
            const form = document.getElementById('accountForm');
            if (!form) return;
            const nameInput = form.querySelector('[name="name"]');
            const accountName = (nameInput?.value || '').trim();
            if (!accountName) {
                await openSystemDialog({ title: 'AutoFill', message: 'Preencha o campo "Nome da Conta" antes de usar o AutoFill.' });
                return;
            }

            const btn = document.getElementById('accountAutoFillBtn');
            if (btn) { btn.disabled = true; btn.innerHTML = '<span class="ai-star-icon">✦</span> Processando...'; }

            // Mostra barra de progresso inline
            let progressWrap = document.getElementById('autoFillProgressWrap');
            if (!progressWrap) {
                progressWrap = document.createElement('div');
                progressWrap.id = 'autoFillProgressWrap';
                progressWrap.style.cssText = 'margin-top:8px;';
                progressWrap.innerHTML = `
                    <div style="font-size:11px; color:#6b7280; margin-bottom:4px; text-align:center;" id="autoFillProgressStep">Iniciando...</div>
                    <div style="position:relative; background:#d1fae5; border-radius:99px; height:8px; overflow:visible; margin:0 2px;">
                        <div id="autoFillProgressBar" style="position:relative; height:100%; width:5%; background:linear-gradient(90deg,#059669,#10b981,#34d399); border-radius:99px; transition:width .6s ease;">
                            <img src="/images/coelho-correndo.webp" class="coelho-run" alt="" style="height:18px;right:-14px;">
                        </div>
                    </div>`;
                btn?.parentNode?.insertAdjacentElement('afterend', progressWrap);
            }
            progressWrap.style.display = 'block';
            _setAutoFillProgress(5, 'Iniciando...');

            try {
                const response = await fetch(`${API_BASE}/accounts/autofill`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ account_name: accountName })
                });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.error || 'Não foi possível iniciar AutoFill.');
                const taskId = payload.task_id;
                if (!taskId) throw new Error('Resposta inesperada do servidor.');

                // Botões Cancelar / Minimizar no topo da barra de progresso inline
                _attachBgTaskControls(
                    progressWrap, taskId,
                    () => { if (progressWrap) progressWrap.style.display = 'none'; if (btn) { btn.disabled = false; btn.innerHTML = '<span class="ai-star-icon">✦</span> AutoFill'; } },
                    () => { if (progressWrap) progressWrap.style.display = 'none'; if (btn) { btn.disabled = false; btn.innerHTML = '<span class="ai-star-icon">✦</span> AutoFill'; } showError('AutoFill cancelado.'); }
                );

                const sourceTab = typeof _currentTab !== 'undefined' ? _currentTab : 'gestao-conta';
                BgTaskManager.register(
                    taskId,
                    `${API_BASE}/tasks/${taskId}`,
                    `AutoFill — ${accountName}`,
                    sourceTab,
                    (result) => {
                        if (progressWrap) progressWrap.style.display = 'none';
                        if (btn) { btn.disabled = false; btn.innerHTML = '<span class="ai-star-icon">✦</span> AutoFill'; }
                        _applyAutoFillResult(result);
                    },
                    (errMsg) => {
                        if (progressWrap) progressWrap.style.display = 'none';
                        if (btn) { btn.disabled = false; btn.innerHTML = '<span class="ai-star-icon">✦</span> AutoFill'; }
                        showError(errMsg || 'Falha ao executar o AutoFill.');
                    },
                    (pct, step) => _setAutoFillProgress(pct, step)
                );
            } catch (error) {
                if (progressWrap) progressWrap.style.display = 'none';
                if (btn) { btn.disabled = false; btn.innerHTML = '<span class="ai-star-icon">✦</span> AutoFill'; }
                showError(error.message || 'Falha ao executar o AutoFill.');
            }
        }

        function closeAccountModal(){ const m=document.getElementById('accountModal'); if(m)m.remove(); }

        async function saveAccount(event, accountId) {
            event.preventDefault();
            const form = document.getElementById('accountForm');
            const fd = new FormData(form);
            fd.set('is_target', form.querySelector('[name="is_target"]').value || '0');
            fd.set('main_contact_ids', document.getElementById('accountMainContactsHidden')?.value || '');
            const url = accountId ? `${API_BASE}/accounts/${accountId}` : `${API_BASE}/accounts`;
            const method = accountId ? 'PUT' : 'POST';
            const response = await fetch(url, { method, body: fd });
            if (!response.ok) return showError('Erro ao salvar conta');
            showSuccess('Conta salva com sucesso');
            closeAccountModal();
            await loadAccounts();
        }

        async function openAccountDetails(accountId) {
            await openAccountViewModal(accountId);
        }

        async function openPresenceModal(accountId, presenceId=null) {
            if (!accountId) return showError('Salve a conta antes de adicionar presença.');
            const account = await (await fetch(`${API_BASE}/accounts/${accountId}`)).json();
            const presence = (account.presences||[]).find(p => Number(p.id)===Number(presenceId));
            const billingType = presence?.billing_type || '';
            const hasRevenue = !!billingType;
            const isMensal = billingType === 'Mensal';
            const contractFieldsDisplay = isMensal ? '' : 'none';
            const earlyTerm = Number(presence?.early_terminated || 0);
            // Calcula encerramento previsto para exibição
            let contractEndPreview = '';
            if (presence?.validity_month && presence?.contract_duration_months) {
                const [y, m] = presence.validity_month.split('-').map(Number);
                const total = (y * 12 + m - 1) + Number(presence.contract_duration_months);
                contractEndPreview = `${String(Math.floor(total / 12)).padStart(4,'0')}-${String(total % 12 + 1).padStart(2,'0')}`;
            }
            const contractEndInfo = contractEndPreview
                ? `<div style="font-size:11px; color:#6b7280; margin-top:4px;"><i class="fas fa-calendar-check" style="margin-right:3px;"></i>Encerramento previsto: <strong>${contractEndPreview}</strong></div>`
                : '';
            let html = `<div class="modal active" id="presenceModal" onclick="if(event.target===this) closePresenceModal()"><div class="modal-content" style="max-width:780px;">
<h2 style="color:#047857;">${presence?'Editar Serviço Stefanini':'Serviço Stefanini'}</h2>
<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:12px 14px;">
  <div class="form-group"><label>Nome da Entrega *</label><input id="presenceDelivery" value="${escapeHtml(presence?.delivery_name||'')}"></div>
  <div class="form-group"><label>Responsável STF</label><input id="presenceOwner" value="${escapeHtml(presence?.stf_owner||'')}"></div>
  <div class="form-group"><label>Célula Delivery</label><input id="presenceDeliveryCell" value="${escapeHtml(presence?.delivery_cell||'')}"></div>
  <div class="form-group"><label>ID Serviço</label><input id="presenceServiceId" value="${escapeHtml(presence?.service_id||'')}"></div>
  <div class="form-group"><label>Tipo de Faturamento</label><select id="presenceBillingType" onchange="onPresenceBillingTypeChange(this.value)"><option value="">Selecione</option><option value="Mensal" ${billingType==='Mensal'?'selected':''}>Mensal</option><option value="Unico" ${billingType==='Unico'?'selected':''}>Único</option></select></div>
  <div class="form-group"><label id="presenceRevenueLabel">Faturamento</label><input id="presenceRevenue" value="${presence?.current_revenue_cents?formatMoneyFromCents(presence.current_revenue_cents):''}" placeholder="R$ 0,00" ${hasRevenue?'':'disabled style="background:#f3f4f6; color:#9ca3af; cursor:not-allowed;"'}></div>
</div>
<div id="presenceContractFieldsGroup" style="display:${contractFieldsDisplay}; margin-top:4px;">
  <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px 14px; align-items:end;">
    <div class="form-group" style="margin-bottom:0;">
      <label>Início do Contrato (mês/ano)</label>
      <input id="presenceValidity" type="month" value="${escapeHtml(presence?.validity_month||'')}" oninput="updateContractEndPreview()">
    </div>
    <div class="form-group" style="margin-bottom:0;">
      <label>Total de Meses</label>
      <input id="presenceContractDuration" type="number" min="1" step="1" value="${presence?.contract_duration_months||''}" placeholder="Ex: 12" oninput="updateContractEndPreview()">
      <div id="contractEndPreview" style="font-size:11px; color:#6b7280; margin-top:4px;">${contractEndInfo}</div>
    </div>
    <div class="form-group" style="margin-bottom:0;">
      <label>Encerrado Antecipado?</label>
      <select id="presenceEarlyTerminated">
        <option value="0" ${earlyTerm===0?'selected':''}>Não</option>
        <option value="1" ${earlyTerm===1?'selected':''}>Sim</option>
      </select>
    </div>
  </div>
</div>
<div style="display:grid; grid-template-columns:1fr; gap:12px 14px; margin-top:12px;">
  <div class="form-group"><label>Ponto Focal</label><select id="presenceFocal"><option value="">Selecione</option>${sortAccountContactsByRole(account.contacts||[]).map(c=>`<option value='${c.id}' ${Number(presence?.focal_client_id)===Number(c.id)?'selected':''}>${escapeHtml(c.name)}</option>`).join('')}</select></div>
</div>
<div style="display:flex; gap:8px; margin-top:12px;"><button class="btn btn-secondary" onclick="closePresenceModal()">Cancelar</button><button class="btn btn-primary" onclick="savePresence(${accountId}, ${presenceId||'null'})">Salvar</button></div>
</div></div>`;
            document.body.insertAdjacentHTML('beforeend', html);
        }

        function closePresenceModal(){ const m=document.getElementById('presenceModal'); if(m)m.remove(); }

        /** Retorna true se o serviço está encerrado (antecipado ou prazo expirado) */
        function isPresenceTerminated(p) {
            if (Number(p.early_terminated) === 1) return true;
            if (p.contract_end_date) {
                const now = new Date();
                const curMonth = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`;
                if (p.contract_end_date < curMonth) return true;
            }
            return false;
        }

        /** Estilo glass para badge de serviço Stefanini */
        function presenceBadgeStyle(p) {
            if (isPresenceTerminated(p)) {
                // Vermelho-alaranjado glass
                return 'display:inline-flex;width:auto;max-width:100%;padding:4px 9px;border-radius:999px;background:linear-gradient(135deg,#fed7aa 0%,#fb923c 100%);color:#7c2d12;border:1px solid rgba(255,255,255,0.25);box-shadow:0 4px 15px rgba(251,146,60,0.35);font-size:12px;font-weight:700;';
            }
            // Verde glass (padrão)
            return 'display:inline-flex;width:auto;max-width:100%;padding:4px 9px;border-radius:999px;background:linear-gradient(135deg,#bbf7d0 0%,#4ade80 100%);color:#064e3b;border:1px solid rgba(255,255,255,0.2);box-shadow:0 4px 15px rgba(74,222,128,0.3);font-size:12px;font-weight:700;'
        }

        function onPresenceBillingTypeChange(value) {
            const input = document.getElementById('presenceRevenue');
            const label = document.getElementById('presenceRevenueLabel');
            const contractGroup = document.getElementById('presenceContractFieldsGroup');
            if (!input) return;
            if (value) {
                input.disabled = false;
                input.style.background = '';
                input.style.color = '';
                input.style.cursor = '';
                if (label) label.textContent = value === 'Unico' ? 'Faturamento Único' : 'Faturamento Mensal';
            } else {
                input.disabled = true;
                input.style.background = '#f3f4f6';
                input.style.color = '#9ca3af';
                input.style.cursor = 'not-allowed';
                if (label) label.textContent = 'Faturamento';
            }
            if (contractGroup) contractGroup.style.display = value === 'Mensal' ? '' : 'none';
        }

        function updateContractEndPreview() {
            const startVal = document.getElementById('presenceValidity')?.value;
            const durVal = document.getElementById('presenceContractDuration')?.value;
            const preview = document.getElementById('contractEndPreview');
            if (!preview) return;
            if (startVal && durVal && Number(durVal) > 0) {
                const [y, m] = startVal.split('-').map(Number);
                const total = (y * 12 + m - 1) + Number(durVal);
                const endStr = `${String(Math.floor(total / 12)).padStart(4,'0')}-${String(total % 12 + 1).padStart(2,'0')}`;
                // Formatar como mês/ano legível
                const months = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];
                const endM = total % 12;
                const endY = Math.floor(total / 12);
                preview.innerHTML = `<i class="fas fa-calendar-check" style="margin-right:3px; color:#059669;"></i>Encerramento previsto: <strong style="color:#065f46;">${months[endM]}/${endY}</strong>`;
            } else {
                preview.innerHTML = '';
            }
        }

        async function refreshAccountPresencePanels(accountId) {
            try {
                const account = await (await fetch(`${API_BASE}/accounts/${accountId}`)).json();
                const list = document.getElementById('accountPresenceList');
                if (list) {
                    const mensalP = (account?.presences||[]).filter(p=>(p.billing_type||'Mensal')==='Mensal' && !isPresenceTerminated(p));
                    const unicoP = (account?.presences||[]).filter(p=>p.billing_type==='Unico' && !isPresenceTerminated(p));
                    const totalMensal = mensalP.reduce((acc,p)=>acc+Number(p.current_revenue_cents||0),0);
                    const totalUnico = unicoP.reduce((acc,p)=>acc+Number(p.current_revenue_cents||0),0);
                    const btns = (account?.presences||[]).map(p=>{const terminated=isPresenceTerminated(p);const btnStyle=terminated?'border-radius:999px;font-weight:700;background:linear-gradient(135deg,#fed7aa,#fb923c);color:#7c2d12;border:1px solid rgba(255,255,255,0.25);box-shadow:0 4px 12px rgba(251,146,60,0.3);':'border-radius:999px;font-weight:700;';return `<div style='display:inline-flex; align-items:center; gap:6px;'><button class='btn ${terminated?'':'btn-secondary'} btn-small' style='${btnStyle}' onclick='openPresenceModal(${account.id}, ${p.id})'>${escapeHtml(p.delivery_name)}</button><button class='btn btn-danger btn-small' onclick='deletePresence(${account.id}, ${p.id})'>Excluir</button></div>`;}).join('');
                    list.innerHTML = `<div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:8px;"><div class='rule-item' style='display:flex; justify-content:space-between; align-items:center; gap:8px; background:rgba(16,185,129,.12);'><strong>Total Mensal</strong><strong>${formatCompactCurrencyFromCents(totalMensal)}</strong></div><div class='rule-item' style='display:flex; justify-content:space-between; align-items:center; gap:8px; background:rgba(99,102,241,.12);'><strong style="color:#4338ca;">Faturamento Pontual</strong><strong style="color:#4338ca;">${formatCompactCurrencyFromCents(totalUnico)}</strong></div></div><div style='display:flex; flex-wrap:wrap; gap:8px;'>${btns}</div>`;
                }
                const view = document.getElementById('accountViewModal');
                if (view) {
                    view.remove();
                    await openAccountViewModal(accountId);
                }
                await loadAccounts();
            } catch (e) {}
        }

        async function savePresence(accountId, presenceId) {
            const payload = {
                delivery_name: document.getElementById('presenceDelivery').value,
                stf_owner: document.getElementById('presenceOwner').value,
                delivery_cell: document.getElementById('presenceDeliveryCell').value,
                service_id: document.getElementById('presenceServiceId').value,
                billing_type: document.getElementById('presenceBillingType').value,
                validity_month: document.getElementById('presenceValidity')?.value || '',
                contract_duration_months: document.getElementById('presenceContractDuration')?.value || '',
                early_terminated: document.getElementById('presenceEarlyTerminated')?.value || '0',
                current_revenue: document.getElementById('presenceRevenue').value,
                focal_client_id: document.getElementById('presenceFocal').value
            };
            const url = presenceId ? `${API_BASE}/accounts/${accountId}/presences/${presenceId}` : `${API_BASE}/accounts/${accountId}/presences`;
            const method = presenceId ? 'PUT' : 'POST';
            const r = await fetch(url, { method, headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
            if (!r.ok) return showError('Erro ao salvar presença');
            closePresenceModal();
            showSuccess('Presença salva');
            await refreshAccountPresencePanels(accountId);
        }

        async function deletePresence(accountId, presenceId) {
            const r = await fetch(`${API_BASE}/accounts/${accountId}/presences/${presenceId}`, { method:'DELETE' });
            if (!r.ok) return showError('Erro ao excluir presença');
            showSuccess('Presença excluída');
            await refreshAccountPresencePanels(accountId);
        }

        let portfolioOffers = [];
        const expandedPortfolioOffers = new Set();
        let _portfolioCurrentSubTab = 'stf';

        // ═══════════════════════════════════════════════════════════════════
        // CAMPANHA OFENSIVA — planejamento e plano de ação comercial (IA)
        // ═══════════════════════════════════════════════════════════════════
        let _campaignPlanData = null;
        let _campaignExpanded = new Set();
        let _cwData = {};

        const CAMP_BLOCK_META = {
            A: { n: '01', name: 'Pronto pra Ataque', icon: 'fa-bolt', color: '#10b981',
                 desc: 'Decisor mapeado e solução aderente. Partir para a apresentação.' },
            B: { n: '02', name: 'Aprofundar Relacionamento', icon: 'fa-user-plus', color: '#f59e0b',
                 desc: 'Há contatos, mas é preciso mapear os decisores da área.' },
            C: { n: '03', name: 'Iniciar do Zero', icon: 'fa-seedling', color: '#ef4444',
                 desc: 'Sem mapeamento relevante. Prospecção e identificação de decisores.' },
            D: { n: '04', name: 'Sem Solução no Portfólio', icon: 'fa-lightbulb', color: '#8b5cf6',
                 desc: 'Relacionamento forte, mas sem oferta aderente. Explorar portfólio interno.' }
        };
        const CAMP_ACTION_META = {
            apresentacao: { label: 'Apresentação', color: '#10b981', icon: 'fa-bullhorn' },
            mapeamento:   { label: 'Mapeamento', color: '#f59e0b', icon: 'fa-sitemap' },
            prospeccao:   { label: 'Prospecção', color: '#ef4444', icon: 'fa-magnifying-glass' },
            portfolio:    { label: 'Portfólio', color: '#8b5cf6', icon: 'fa-box-open' },
            outro:        { label: 'Ação', color: '#6b7280', icon: 'fa-flag' }
        };
        const CAMP_STATUS_META = {
            pending:     { label: 'Pendente', icon: 'fa-circle', cls: 'camp-st-pending', next: 'in_progress' },
            in_progress: { label: 'Em andamento', icon: 'fa-circle-half-stroke', cls: 'camp-st-prog', next: 'done' },
            done:        { label: 'Concluída', icon: 'fa-circle-check', cls: 'camp-st-done', next: 'pending' }
        };

        function _campDate(iso) {
            if (!iso) return '';
            const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})/);
            return m ? `${m[3]}/${m[2]}` : String(iso);
        }
        function _campActionMeta(t) { return CAMP_ACTION_META[t] || CAMP_ACTION_META.outro; }

        function _campLogo(name, url, size = 40) {
            const initials = (name || '?').trim().slice(0, 2).toUpperCase();
            if (url) {
                return `<img src="${escapeHtml(url)}" alt="" style="width:${size}px;height:${size}px;border-radius:10px;object-fit:cover;background:#fff;border:1px solid #e5e7eb;"
                        onerror="this.outerHTML='<div class=&quot;camp-logo-fallback&quot; style=&quot;width:${size}px;height:${size}px;font-size:${Math.round(size*0.34)}px;&quot;>${escapeHtml(initials)}</div>'">`;
            }
            return `<div class="camp-logo-fallback" style="width:${size}px;height:${size}px;font-size:${Math.round(size*0.34)}px;">${escapeHtml(initials)}</div>`;
        }

        function _campChips(arr, cls) {
            if (!arr || !arr.length) return '<span style="color:#9ca3af;font-size:12px;">—</span>';
            return arr.map(a => `<span class="${cls}">${escapeHtml(a)}</span>`).join('');
        }

        function _campaignEnsureStyles() {
            if (document.getElementById('campaign-styles')) return;
            const style = document.createElement('style');
            style.id = 'campaign-styles';
            style.textContent = `
                @keyframes camp-glow-pulse { 0%,100%{opacity:.55;transform:scale(1)} 50%{opacity:.9;transform:scale(1.06)} }
                @keyframes camp-fade-up { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:none} }

                /* ── Hero ── */
                .camp-hero { position:relative; overflow:hidden; border-radius:20px; padding:34px 36px;
                    background:radial-gradient(120% 140% at 85% 20%, #3b2d6b 0%, #1f1b3a 45%, #12101f 100%);
                    color:#fff; margin-bottom:20px; box-shadow:0 18px 50px -20px rgba(99,76,180,.6); }
                .camp-hero-glow { position:absolute; right:60px; top:50%; transform:translateY(-50%); width:230px; height:230px; border-radius:50%;
                    background:radial-gradient(circle, rgba(139,92,246,.55) 0%, rgba(59,130,246,.15) 45%, transparent 70%);
                    animation:camp-glow-pulse 4s ease-in-out infinite; pointer-events:none; }
                .camp-hero-rings { position:absolute; right:90px; top:50%; transform:translateY(-50%); pointer-events:none; opacity:.5; }
                .camp-hero-rings i { position:absolute; border:1px solid rgba(255,255,255,.18); border-radius:50%; }
                .camp-eyebrow { font-size:11px; letter-spacing:2px; text-transform:uppercase; color:#a99fe0; font-weight:700; }
                .camp-hero h1 { font-size:30px; line-height:1.15; margin:8px 0 6px; max-width:560px; font-weight:800; }
                .camp-hero h1 .accent { background:linear-gradient(90deg,#8b5cf6,#38bdf8); -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent; }
                .camp-hero p { color:#cdc8e6; font-size:14px; margin:0 0 18px; }
                .camp-feature-row { display:flex; gap:10px; flex-wrap:wrap; max-width:600px; }
                .camp-feature { display:flex; gap:10px; align-items:center; background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.1);
                    border-radius:12px; padding:10px 14px; backdrop-filter:blur(6px); }
                .camp-feature i { color:#a78bfa; font-size:15px; }
                .camp-feature b { font-size:12.5px; display:block; }
                .camp-feature span { font-size:11px; color:#aaa3cf; }

                /* ── Portfolio reminder banner ── */
                .camp-banner { display:flex; align-items:center; gap:14px; background:#fffbeb; border:1px solid #fde68a;
                    border-radius:12px; padding:12px 16px; margin-bottom:18px; }
                .camp-banner i.lead { color:#d97706; font-size:18px; }
                .camp-banner .txt { flex:1; font-size:13px; color:#92400e; }
                .camp-banner a { white-space:nowrap; }

                /* ── List cards ── */
                .camp-list-head { display:flex; align-items:center; justify-content:space-between; margin:6px 0 14px; }
                .camp-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(330px,1fr)); gap:16px; }
                .camp-card { background:#fff; border:1px solid #e5e7eb; border-radius:16px; padding:18px; cursor:pointer;
                    transition:transform .15s ease, box-shadow .15s ease, border-color .15s; position:relative; animation:camp-fade-up .35s ease both; }
                .camp-card:hover { transform:translateY(-3px); box-shadow:0 14px 34px -16px rgba(79,70,229,.45); border-color:#c7d2fe; }
                .camp-card h3 { font-size:16px; margin:0 0 6px; color:#111827; padding-right:60px; }
                .camp-card .camp-status-chip { position:absolute; top:16px; right:16px; }
                .camp-card .meta { font-size:12px; color:#6b7280; margin-bottom:14px; }
                .camp-card .meta b { color:#374151; }
                .camp-status-chip { font-size:10.5px; font-weight:700; padding:3px 10px; border-radius:99px; text-transform:uppercase; letter-spacing:.4px; }
                .camp-status-chip.ativo { background:#dcfce7; color:#166534; }
                .camp-status-chip.concluido { background:#e0e7ff; color:#3730a3; }
                .camp-status-chip.pausado { background:#fef3c7; color:#92400e; }
                .camp-prog-track { height:8px; border-radius:99px; background:#eef2f7; overflow:hidden; }
                .camp-prog-fill { height:100%; border-radius:99px; background:linear-gradient(90deg,#6366f1,#8b5cf6,#38bdf8); transition:width .5s ease; }

                /* ── Plan view ── */
                .camp-sticky { position:sticky; top:0; z-index:30; background:rgba(18,16,31,.92); backdrop-filter:blur(10px);
                    color:#fff; border-radius:14px; padding:14px 20px; margin-bottom:18px; display:flex; align-items:center; gap:18px; flex-wrap:wrap;
                    box-shadow:0 10px 30px -14px rgba(0,0,0,.5); }
                .camp-sticky .title { font-size:17px; font-weight:700; }
                .camp-sticky .sub { font-size:12px; color:#bcb6da; }
                .camp-sticky .spacer { flex:1; }
                .camp-mini-prog { min-width:160px; }
                .camp-mini-prog .lbl { font-size:11px; color:#bcb6da; display:flex; justify-content:space-between; margin-bottom:4px; }

                .camp-summary { background:#fff; border:1px solid #e5e7eb; border-radius:16px; padding:22px; margin-bottom:18px; }
                .camp-summary h2 { font-size:13px; text-transform:uppercase; letter-spacing:1px; color:#6366f1; margin:0 0 10px; }
                .camp-summary .obj { font-size:14.5px; color:#374151; line-height:1.55; margin-bottom:16px; }
                .camp-summary-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:14px 22px; }
                .camp-sg-label { font-size:11px; text-transform:uppercase; letter-spacing:.5px; color:#9ca3af; margin-bottom:6px; }
                .camp-chip { display:inline-block; background:#eef2ff; color:#4338ca; font-size:12px; font-weight:600; padding:4px 10px; border-radius:8px; margin:0 5px 5px 0; }
                .camp-chip.dec { background:#f0fdfa; color:#0f766e; }

                .camp-stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:14px; margin-bottom:18px; }
                .camp-stat { background:#fff; border:1px solid #e5e7eb; border-radius:14px; padding:16px 18px; display:flex; align-items:center; gap:14px; }
                .camp-stat .ic { width:42px; height:42px; border-radius:11px; display:flex; align-items:center; justify-content:center; font-size:17px; flex-shrink:0; }
                .camp-stat .big { font-size:22px; font-weight:800; color:#111827; line-height:1; }
                .camp-stat .cap { font-size:11.5px; color:#6b7280; margin-top:3px; }
                .camp-ring { --p:0; width:70px; height:70px; border-radius:50%; flex-shrink:0;
                    background:conic-gradient(#10b981 calc(var(--p)*1%), #eef2f7 0); display:flex; align-items:center; justify-content:center; }
                .camp-ring .inner { width:54px; height:54px; border-radius:50%; background:#fff; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:16px; color:#059669; }

                /* ── Blocks ── */
                .camp-block { background:#fff; border:1px solid #e5e7eb; border-left:5px solid var(--bc); border-radius:14px; margin-bottom:16px; overflow:hidden; }
                .camp-block-head { display:flex; align-items:center; gap:14px; padding:16px 20px; cursor:pointer; user-select:none; }
                .camp-block-head .num { font-size:22px; font-weight:800; color:var(--bc); opacity:.5; min-width:34px; }
                .camp-block-head .bicon { width:38px; height:38px; border-radius:10px; display:flex; align-items:center; justify-content:center; color:#fff; background:var(--bc); font-size:16px; }
                .camp-block-head h3 { margin:0; font-size:16px; color:#111827; }
                .camp-block-head .bdesc { font-size:12px; color:#6b7280; margin-top:2px; }
                .camp-block-count { margin-left:auto; background:var(--bc); color:#fff; font-size:12px; font-weight:700; padding:4px 12px; border-radius:99px; }
                .camp-block-body { padding:0 16px 12px; }
                .camp-acc { border:1px solid #eef0f4; border-radius:12px; margin-bottom:10px; overflow:hidden; }
                .camp-acc-row { display:flex; align-items:center; gap:14px; padding:12px 14px; cursor:pointer; }
                .camp-acc-row:hover { background:#fafbff; }
                .camp-acc .nm { font-weight:700; color:#111827; font-size:14px; }
                .camp-acc .rat { font-size:11.5px; color:#6b7280; margin-top:2px; max-width:520px; }
                .camp-acc .col-next { min-width:190px; font-size:12px; color:#374151; }
                .camp-acc .col-next .due { color:#9ca3af; font-size:11px; }
                .camp-acc .col-prog { width:120px; }
                .camp-acc .col-prog .pl { font-size:10.5px; color:#9ca3af; margin-bottom:3px; display:flex; justify-content:space-between; }
                .camp-readiness { font-size:10px; font-weight:700; color:#fff; padding:2px 8px; border-radius:6px; }
                .camp-act-type { display:inline-flex; align-items:center; gap:5px; font-size:11px; font-weight:600; padding:2px 8px; border-radius:6px; }
                .camp-status-btn { border:none; cursor:pointer; font-size:12px; font-weight:600; padding:6px 12px; border-radius:8px; display:inline-flex; align-items:center; gap:6px; white-space:nowrap; transition:filter .15s; }
                .camp-status-btn:hover { filter:brightness(.96); }
                .camp-st-pending { background:#f3f4f6; color:#6b7280; }
                .camp-st-prog { background:#fef3c7; color:#b45309; }
                .camp-st-done { background:#dcfce7; color:#166534; }
                .camp-acc-detail { padding:4px 16px 16px 16px; background:#fafbff; border-top:1px solid #eef0f4; animation:camp-fade-up .25s ease both; }
                .camp-acc-detail .desc { font-size:13px; color:#374151; line-height:1.55; margin:10px 0 14px; }
                .camp-logs { list-style:none; padding:0; margin:0 0 12px; }
                .camp-logs li { font-size:12.5px; color:#374151; padding:8px 12px; background:#fff; border:1px solid #eef0f4; border-radius:8px; margin-bottom:6px; }
                .camp-logs li .ts { color:#9ca3af; font-size:10.5px; }
                .camp-logs li.system { border-left:3px solid #8b5cf6; }
                .camp-log-add { display:flex; gap:8px; }
                .camp-log-add input { flex:1; padding:8px 12px; border:1px solid #d1d5db; border-radius:8px; font-size:13px; }
                .camp-logs li .ts { display:flex; align-items:center; gap:8px; margin-top:4px; }
                .camp-log-tools { display:inline-flex; gap:4px; margin-left:auto; }
                .camp-log-tools button { border:none; background:#f3f4f6; color:#6b7280; width:22px; height:22px; border-radius:6px; cursor:pointer; font-size:10px; display:inline-flex; align-items:center; justify-content:center; transition:background .15s,color .15s; }
                .camp-log-tools button:hover { background:#e5e7eb; color:#374151; }
                .camp-log-text { white-space:pre-wrap; }

                /* ── Múltiplas ações por conta ── */
                .camp-action-card { background:#fff; border:1px solid #eef0f4; border-radius:12px; padding:14px 16px; margin-bottom:12px; }
                .camp-action-head { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:8px; }
                .camp-action-due { font-size:11.5px; color:#6b7280; }
                .camp-angle-chip { font-size:10.5px; font-weight:700; color:#4338ca; background:#eef2ff; padding:2px 8px; border-radius:99px; text-transform:lowercase; }

                /* ── Insight de mercado ── */
                .camp-insight { background:linear-gradient(135deg,#f5f3ff,#eef2ff); border:1px solid #ddd6fe; border-radius:12px; padding:13px 16px; margin:10px 0 14px; -webkit-print-color-adjust:exact; print-color-adjust:exact; }
                .camp-insight-title { font-size:12px; font-weight:700; color:#6d28d9; margin-bottom:5px; display:flex; align-items:center; gap:6px; }
                .camp-insight-body { font-size:13px; color:#374151; line-height:1.6; }
                .camp-insight-src { font-size:11px; color:#8b5cf6; margin-top:7px; }
                .camp-insight-src a { color:#7c3aed; text-decoration:none; }
                .camp-insight-src a:hover { text-decoration:underline; }

                /* ── Badge do usuário (visível na tela e no PDF) ── */
                .camp-user-badge { display:flex; align-items:center; gap:8px; padding-left:10px; margin-left:4px; border-left:1px solid rgba(255,255,255,.18); }
                .camp-user-badge img { width:36px; height:36px; border-radius:50%; object-fit:cover; border:2px solid rgba(255,255,255,.3); }
                .camp-user-badge .camp-user-initial { width:36px; height:36px; border-radius:50%; background:rgba(255,255,255,.18); display:flex; align-items:center; justify-content:center; font-size:14px; font-weight:700; color:#fff; }
                .camp-user-badge .camp-user-name { font-size:12.5px; font-weight:600; color:#fff; max-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }

                /* ── Gantt ── */
                .camp-gantt { background:radial-gradient(120% 140% at 90% 0%, #241f44 0%, #15131f 60%); color:#fff; border-radius:16px; padding:22px; margin-bottom:20px; }
                .camp-gantt h2 { font-size:14px; margin:0 0 4px; }
                .camp-gantt .gsub { font-size:12px; color:#a9a3cf; margin:0 0 16px; }
                .camp-gantt-scroll { overflow-x:auto; padding-bottom:8px; }
                .camp-gantt-track { display:flex; gap:12px; min-width:min-content; }
                .camp-week { min-width:130px; flex:1; background:rgba(255,255,255,.05); border:1px solid rgba(255,255,255,.08); border-radius:12px; padding:12px; }
                .camp-week .wk { font-size:11px; color:#a9a3cf; font-weight:700; text-transform:uppercase; letter-spacing:.5px; }
                .camp-week .dt { font-size:13px; font-weight:700; margin:2px 0 10px; }
                .camp-week .dots { display:flex; flex-wrap:wrap; gap:5px; min-height:14px; }
                .camp-week .dot { width:11px; height:11px; border-radius:50%; }
                .camp-week .wtotal { font-size:11px; color:#cdc8e6; margin-top:10px; }
                .camp-milestone { display:flex; align-items:center; gap:6px; font-size:10.5px; color:#fcd34d; margin-top:8px; }
                .camp-legend { display:flex; gap:16px; flex-wrap:wrap; margin-top:16px; font-size:11.5px; color:#cdc8e6; }
                .camp-legend span { display:inline-flex; align-items:center; gap:6px; }
                .camp-legend i { width:10px; height:10px; border-radius:50%; display:inline-block; }

                .camp-logo-fallback { border-radius:10px; background:linear-gradient(135deg,#6366f1,#8b5cf6); color:#fff; display:flex; align-items:center; justify-content:center; font-weight:700; flex-shrink:0; }
                .camp-gap-banner { display:flex; gap:14px; align-items:flex-start; background:#faf5ff; border:1px solid #e9d5ff; border-radius:14px; padding:16px 18px; margin-bottom:18px; }
                .camp-gap-banner i.lead { color:#8b5cf6; font-size:20px; margin-top:2px; }

                /* ── Wizard ── */
                .cw-steps { display:flex; gap:8px; margin-bottom:18px; }
                .cw-step-dot { flex:1; height:5px; border-radius:99px; background:#e5e7eb; transition:background .3s; }
                .cw-step-dot.active { background:linear-gradient(90deg,#6366f1,#8b5cf6); }
                .cw-areas-suggest { display:flex; flex-wrap:wrap; gap:7px; margin-top:10px; }
                .cw-tag { font-size:12px; padding:5px 11px; border-radius:8px; border:1px solid #d1d5db; background:#fff; cursor:pointer; color:#374151; user-select:none; }
                .cw-tag.on { background:#eef2ff; border-color:#a5b4fc; color:#4338ca; font-weight:600; }
                .cw-confirm-box { background:#f8fafc; border:1px solid #e5e7eb; border-radius:12px; padding:16px; margin-bottom:12px; }
                .cw-confirm-box .lbl { font-size:11px; text-transform:uppercase; letter-spacing:.5px; color:#9ca3af; margin-bottom:7px; }
                .cw-acc-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:10px; max-height:280px; overflow-y:auto; padding:4px; margin-top:10px; }
                .cw-acc-pick { border:2px solid #e5e7eb; border-radius:12px; padding:12px; cursor:pointer; text-align:center; transition:all .15s; position:relative; }
                .cw-acc-pick:hover { border-color:#c7d2fe; }
                .cw-acc-pick.sel { border-color:#6366f1; background:#eef2ff; }
                .cw-acc-pick .check { position:absolute; top:6px; right:6px; color:#6366f1; opacity:0; }
                .cw-acc-pick.sel .check { opacity:1; }
                .cw-acc-pick .nm2 { font-size:12px; font-weight:600; color:#374151; margin-top:8px; word-break:break-word; }
                .cw-acc-pick .tgt { font-size:9px; font-weight:700; color:#166534; background:#dcfce7; padding:1px 6px; border-radius:5px; }

                @media print {
                    .sidebar, .main-topbar, #campaignListView, .camp-no-print, .bg-task-indicator { display:none !important; }
                    .main-content { margin:0 !important; padding:0 !important; width:100% !important; }
                    .tab-content:not(.active) { display:none !important; }
                    .camp-sticky { position:static !important; background:#1f1b3a !important; -webkit-print-color-adjust:exact; print-color-adjust:exact; }
                    .camp-block, .camp-summary, .camp-stat, .camp-gantt, .camp-acc-detail, .camp-action-card, .camp-insight { break-inside:avoid; -webkit-print-color-adjust:exact; print-color-adjust:exact; }
                    body { background:#fff !important; }
                    .camp-acc-detail { display:block !important; }
                    .camp-user-badge { display:flex !important; border-left:1px solid rgba(255,255,255,.3); }
                }
            `;
            document.head.appendChild(style);
        }

        function loadCampanha() {
            _campaignEnsureStyles();
            backToCampaignList();
        }

        function backToCampaignList() {
            const planView = document.getElementById('campaignPlanView');
            const listView = document.getElementById('campaignListView');
            if (planView) { planView.style.display = 'none'; planView.innerHTML = ''; }
            if (listView) listView.style.display = '';
            _campaignPlanData = null;
            _renderCampaignListShell();
            _loadCampaignList();
        }

        function _renderCampaignListShell() {
            const v = document.getElementById('campaignListView');
            if (!v) return;
            v.innerHTML = `
                <div class="camp-hero">
                    <div class="camp-hero-glow"></div>
                    <div class="camp-hero-rings">
                        <i style="width:90px;height:90px;left:-45px;top:-45px;"></i>
                        <i style="width:150px;height:150px;left:-75px;top:-75px;"></i>
                        <i style="width:215px;height:215px;left:-107px;top:-107px;"></i>
                    </div>
                    <div class="camp-eyebrow">Plano de Ação Comercial</div>
                    <h1>Inteligência para atacar as <span class="accent">oportunidades certas</span>.</h1>
                    <p>A IA cruza o seu desafio com o portfólio e o mapeamento das contas, e monta um plano de ataque com cronograma e execução guiada.</p>
                    <div class="camp-feature-row">
                        <div class="camp-feature"><i class="fas fa-brain"></i><div><b>IA Estratégica</b><span>Entende o desafio</span></div></div>
                        <div class="camp-feature"><i class="fas fa-layer-group"></i><div><b>Alinhado ao Portfólio</b><span>Cruza com Soluções STF</span></div></div>
                        <div class="camp-feature"><i class="fas fa-route"></i><div><b>Execução Guiada</b><span>Checklist + cronograma</span></div></div>
                    </div>
                    <div style="margin-top:28px;">
                        <button class="btn btn-auto-mapping" style="font-size:15px;padding:13px 28px;" onclick="openCampaignWizard()"><span class="ai-star-icon">✦</span> Nova Campanha Ofensiva</button>
                    </div>
                </div>
                <div class="camp-banner">
                    <i class="fas fa-circle-info lead"></i>
                    <div class="txt">Quanto mais completo o seu <b>Portfólio (Soluções STF)</b>, melhores as recomendações do plano. Cadastre suas ofertas para que a IA saiba o que você pode oferecer.</div>
                    <a class="btn btn-secondary btn-small" href="#" onclick="event.preventDefault(); switchTab(null,'portfolio');"><i class="fas fa-arrow-up-right-from-square"></i> Cadastrar ofertas</a>
                </div>
                <div class="camp-list-head">
                    <h2 style="margin:0;font-size:18px;color:#111827;">Minhas campanhas</h2>
                </div>
                <div id="campaignCards"><p style="color:#6b7280;">Carregando campanhas...</p></div>`;
        }

        async function _loadCampaignList() {
            const box = document.getElementById('campaignCards');
            if (!box) return;
            try {
                const res = await fetch(`${API_BASE}/campaigns`);
                const list = await res.json().catch(() => []);
                if (!res.ok) throw new Error(list.error || 'Erro ao carregar campanhas.');
                if (!Array.isArray(list) || !list.length) {
                    box.innerHTML = `<div class="empty-state"><div class="empty-state-icon">🎯</div><h3 style="color:#374151;">Nenhuma campanha ainda</h3><p style="color:#6b7280;">Crie sua primeira ofensiva comercial e deixe a IA montar o plano de ataque.</p><button class="btn btn-auto-mapping" onclick="openCampaignWizard()"><span class="ai-star-icon">✦</span> Nova Campanha Ofensiva</button></div>`;
                    return;
                }
                box.innerHTML = `<div class="camp-grid">${list.map(_campCardHTML).join('')}</div>`;
            } catch (e) {
                box.innerHTML = `<div class="alert alert-error" style="display:block;">${escapeHtml(e.message || 'Erro ao carregar campanhas.')}</div>`;
            }
        }

        function _campCardHTML(c) {
            const st = (c.status || 'Ativo').toLowerCase();
            const stCls = st.includes('conclu') ? 'concluido' : (st.includes('paus') ? 'pausado' : 'ativo');
            const areas = (c.areas || []).slice(0, 4);
            return `
                <div class="camp-card" onclick="openCampaignPlan(${c.id})">
                    <span class="camp-status-chip ${stCls}">${escapeHtml(c.status || 'Ativo')}</span>
                    <h3>${escapeHtml(c.title || 'Campanha')}</h3>
                    <div class="meta"><b>${c.accounts_count || 0}</b> contas · início ${_campDate(c.start_date) || '—'} · ${escapeHtml((c.areas || []).slice(0,3).join(', ') || 'sem áreas')}</div>
                    <div class="camp-prog-track"><div class="camp-prog-fill" style="width:${c.progress || 0}%"></div></div>
                    <div style="display:flex;justify-content:space-between;margin-top:6px;font-size:11px;color:#6b7280;">
                        <span>Progresso</span><span><b>${c.progress || 0}%</b></span>
                    </div>
                </div>`;
        }

        // ── Wizard ──────────────────────────────────────────────────────────
        function openCampaignWizard() {
            _campaignEnsureStyles();
            _cwData = { step: 1, analysis: null, selectedAccounts: new Set(), selectableAccounts: [], areaTags: new Set() };
            document.getElementById('campaignWizard')?.remove();
            const html = `
                <div class="modal active" id="campaignWizard">
                    <div class="modal-content" style="max-width:720px;">
                        <div class="modal-header">
                            <h2 class="modal-title"><span class="ai-star-icon">✦</span> Nova Campanha Ofensiva</h2>
                            <button class="modal-close" onclick="closeCampaignWizard()">&#215;</button>
                        </div>
                        <div class="cw-steps">
                            <div class="cw-step-dot active" id="cwDot1"></div>
                            <div class="cw-step-dot" id="cwDot2"></div>
                            <div class="cw-step-dot" id="cwDot3"></div>
                        </div>
                        <div id="cwError" style="display:none;background:#fef2f2;border:1px solid #fca5a5;color:#b91c1c;border-radius:8px;padding:10px;margin-bottom:12px;font-size:13px;"></div>

                        <div id="cwStep1">
                            <p style="margin:0 0 8px;font-weight:600;color:#374151;">Descreva o desafio ou o objetivo comercial que você quer atacar</p>
                            <textarea id="cwChallenge" rows="4" placeholder="Ex.: Quero aumentar a penetração da nossa solução de segurança digital em clientes do setor financeiro, atuando com os decisores de TI e Operações."
                                style="width:100%;padding:11px 14px;border:1px solid #d1d5db;border-radius:10px;font-size:13.5px;resize:vertical;font-family:inherit;box-sizing:border-box;"></textarea>
                            <p style="font-size:12px;color:#6b7280;margin:14px 0 0;">A IA vai identificar as áreas e decisores mais relevantes, e cruzar com o seu portfólio.</p>
                        </div>

                        <div id="cwProgress" style="display:none;padding:24px 4px 14px;">
                            <div style="font-size:13px;color:#6b7280;margin-bottom:12px;text-align:center;" id="cwProgressStep">Iniciando...</div>
                            <div style="position:relative;background:#ede9fe;border-radius:99px;height:12px;overflow:visible;margin:0 16px 6px;">
                                <div id="cwProgressBar" style="position:relative;height:100%;width:5%;background:linear-gradient(90deg,#6366f1,#8b5cf6,#38bdf8);border-radius:99px;transition:width .6s ease;">
                                    <img src="/images/coelho-correndo.webp" class="coelho-run" alt="">
                                </div>
                            </div>
                            <div style="text-align:right;padding:0 16px;font-size:11px;color:#8b5cf6;" id="cwProgressPct">5%</div>
                        </div>

                        <div id="cwStep2" style="display:none;"></div>
                        <div id="cwStep3" style="display:none;"></div>

                        <div id="cwFooter" style="display:flex;justify-content:flex-end;gap:8px;margin-top:18px;">
                            <button class="btn btn-secondary" onclick="closeCampaignWizard()">Cancelar</button>
                            <button class="btn btn-auto-mapping" id="cwPrimaryBtn" onclick="_cwAnalyze()"><span class="ai-star-icon">✦</span> Analisar com IA</button>
                        </div>
                    </div>
                </div>`;
            document.body.insertAdjacentHTML('beforeend', html);
        }
        function closeCampaignWizard() { document.getElementById('campaignWizard')?.remove(); }
        function _cwError(msg) {
            const el = document.getElementById('cwError');
            if (!el) return;
            if (msg) { el.textContent = msg; el.style.display = ''; } else { el.style.display = 'none'; }
        }
        function _cwSetDots(n) {
            [1,2,3].forEach(i => {
                const d = document.getElementById('cwDot' + i);
                if (d) d.classList.toggle('active', i <= n);
            });
        }
        function _cwProgress(pct, step) {
            const bar = document.getElementById('cwProgressBar');
            const s = document.getElementById('cwProgressStep');
            const p = document.getElementById('cwProgressPct');
            if (bar) bar.style.width = Math.max(5, pct) + '%';
            if (s) s.textContent = step || '';
            if (p) p.textContent = Math.round(pct) + '%';
        }
        function _cwShowProgress(on) {
            document.getElementById('cwStep1').style.display = on ? 'none' : '';
            document.getElementById('cwProgress').style.display = on ? '' : 'none';
            document.getElementById('cwFooter').style.display = on ? 'none' : '';
        }

        async function _cwAnalyze() {
            _cwError('');
            const challenge = (document.getElementById('cwChallenge').value || '').trim();
            if (challenge.length < 12) { _cwError('Descreva o desafio com um pouco mais de detalhe.'); return; }
            _cwData.challenge = challenge;
            _cwShowProgress(true);
            _cwProgress(10, 'Entendendo o desafio...');
            try {
                const res = await fetch(`${API_BASE}/campaigns/analyze`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ challenge_text: challenge })
                });
                const payload = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(payload.error || 'Falha ao analisar.');
                const taskId = payload.task_id;
                const poll = setInterval(async () => {
                    try {
                        const tr = await fetch(`${API_BASE}/tasks/${taskId}`);
                        const task = await tr.json();
                        if (task.progress) _cwProgress(task.progress, task.step || '');
                        if (task.status === 'done') {
                            clearInterval(poll);
                            _cwData.analysis = task.result;
                            _cwRenderStep2();
                        } else if (task.status === 'error' || task.status === 'not_found') {
                            clearInterval(poll);
                            _cwShowProgress(false);
                            _cwError(task.error || 'Erro ao analisar o desafio.');
                        }
                    } catch (e) { clearInterval(poll); _cwShowProgress(false); _cwError('Erro ao verificar status.'); }
                }, 800);
            } catch (e) { _cwShowProgress(false); _cwError(e.message); }
        }

        function _cwRenderStep2() {
            const a = _cwData.analysis || {};
            _cwShowProgress(false);
            document.getElementById('cwStep1').style.display = 'none';
            _cwSetDots(2);
            const s2 = document.getElementById('cwStep2');
            const offersHTML = (a.matched_offers && a.matched_offers.length)
                ? a.matched_offers.map(o => `<span class="camp-chip">${escapeHtml(o.title)}</span>`).join('')
                : '<span style="color:#9ca3af;font-size:12px;">Nenhuma oferta aderente encontrada</span>';
            const noteHTML = a.portfolio_note
                ? `<div class="camp-banner" style="margin:0 0 12px;"><i class="fas fa-triangle-exclamation lead"></i><div class="txt">${escapeHtml(a.portfolio_note)}</div><a class="btn btn-secondary btn-small" href="#" onclick="event.preventDefault(); closeCampaignWizard(); switchTab(null,'portfolio');">Abrir Portfólio</a></div>`
                : '';
            s2.innerHTML = `
                ${noteHTML}
                <div class="cw-confirm-box">
                    <div class="lbl">Entendimento da IA <span style="color:#8b5cf6;">(${escapeHtml(a.llm_source || 'heurística')})</span></div>
                    <div style="font-size:13.5px;color:#374151;line-height:1.55;">${escapeHtml(a.entendimento || '')}</div>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                    <div class="cw-confirm-box"><div class="lbl">Áreas identificadas</div>${_campChips(a.areas, 'camp-chip')}</div>
                    <div class="cw-confirm-box"><div class="lbl">Decisores</div>${_campChips(a.decisores, 'camp-chip dec')}</div>
                </div>
                <div class="cw-confirm-box"><div class="lbl">Soluções aderentes do portfólio</div>${offersHTML}</div>
                <div class="cw-confirm-box" style="display:flex;align-items:center;gap:10px;">
                    <i class="fas fa-bullseye" style="color:#6366f1;"></i>
                    <span style="font-size:13px;color:#374151;"><b>${a.target_count || 0}</b> contas marcadas como <b>target</b> no sistema.</span>
                </div>`;
            s2.style.display = '';
            const footer = document.getElementById('cwFooter');
            footer.style.display = '';
            footer.innerHTML = `
                <button class="btn btn-secondary" onclick="_cwBackToStep1()"><i class="fas fa-arrow-left"></i> Refazer</button>
                <button class="btn btn-auto-mapping" onclick="_cwRenderStep3()">Seguir para configuração <i class="fas fa-arrow-right"></i></button>`;
        }
        function _cwBackToStep1() {
            _cwSetDots(1);
            document.getElementById('cwStep2').style.display = 'none';
            document.getElementById('cwStep1').style.display = '';
            const footer = document.getElementById('cwFooter');
            footer.innerHTML = `<button class="btn btn-secondary" onclick="closeCampaignWizard()">Cancelar</button>
                <button class="btn btn-auto-mapping" onclick="_cwAnalyze()"><span class="ai-star-icon">✦</span> Analisar com IA</button>`;
        }

        function _cwRenderStep3() {
            _cwSetDots(3);
            document.getElementById('cwStep2').style.display = 'none';
            const a = _cwData.analysis || {};
            const today = new Date().toISOString().slice(0, 10);
            const s3 = document.getElementById('cwStep3');
            s3.innerHTML = `
                <div class="cw-confirm-box">
                    <div class="lbl">Título da campanha</div>
                    <input id="cwTitle" value="${escapeHtml('Ofensiva: ' + ((a.areas && a.areas[0]) ? a.areas[0] : 'Comercial'))}"
                        style="width:100%;padding:9px 12px;border:1px solid #d1d5db;border-radius:8px;font-size:13.5px;box-sizing:border-box;">
                </div>
                <div class="cw-confirm-box">
                    <div class="lbl">Quais contas atacar?</div>
                    <label style="display:flex;align-items:center;gap:8px;font-size:13px;color:#374151;cursor:pointer;margin-bottom:8px;">
                        <input type="radio" name="cwAccMode" value="targets" checked onchange="_cwToggleAccMode('targets')">
                        Todas as contas <b>target</b> (${a.target_count || 0})
                    </label>
                    <label style="display:flex;align-items:center;gap:8px;font-size:13px;color:#374151;cursor:pointer;">
                        <input type="radio" name="cwAccMode" value="manual" onchange="_cwToggleAccMode('manual')">
                        Selecionar contas uma a uma
                    </label>
                    <div id="cwAccGridWrap" style="display:none;">
                        <div style="display:flex;gap:8px;margin:8px 0 6px;align-items:center;">
                            <button class="btn btn-secondary btn-small" onclick="_cwSelectAll(true)"><i class="fas fa-check-square"></i> Selecionar Todos</button>
                            <button class="btn btn-secondary btn-small" onclick="_cwSelectAll(false)"><i class="fas fa-square"></i> Desselecionar Todos</button>
                            <span style="font-size:11px;color:#6b7280;margin-left:4px;"><span id="cwAccCount">0</span> selecionada(s)</span>
                        </div>
                        <div id="cwAccGrid" class="cw-acc-grid"><p style="color:#6b7280;font-size:12px;">Carregando contas...</p></div>
                    </div>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                    <div class="cw-confirm-box">
                        <div class="lbl">Data de início das ações</div>
                        <input type="date" id="cwStartDate" value="${today}" style="width:100%;padding:9px 12px;border:1px solid #d1d5db;border-radius:8px;font-size:13.5px;box-sizing:border-box;">
                    </div>
                    <div class="cw-confirm-box">
                        <div class="lbl">Ações / apresentações por semana</div>
                        <input type="number" id="cwCapacity" value="5" min="1" max="50" style="width:100%;padding:9px 12px;border:1px solid #d1d5db;border-radius:8px;font-size:13.5px;box-sizing:border-box;">
                    </div>
                </div>`;
            s3.style.display = '';
            const footer = document.getElementById('cwFooter');
            footer.innerHTML = `
                <button class="btn btn-secondary" onclick="_cwRenderStep2()"><i class="fas fa-arrow-left"></i> Voltar</button>
                <button class="btn btn-auto-mapping" id="cwGenBtn" onclick="_cwGenerate()"><span class="ai-star-icon">✦</span> Gerar Plano de Ação</button>`;
        }

        async function _cwToggleAccMode(mode) {
            const wrap = document.getElementById('cwAccGridWrap');
            if (mode !== 'manual') { wrap.style.display = 'none'; return; }
            wrap.style.display = '';
            if (_cwData.selectableAccounts.length) { _cwRenderAccGrid(); return; }
            try {
                const res = await fetch(`${API_BASE}/campaigns/selectable-accounts`);
                const list = await res.json().catch(() => []);
                _cwData.selectableAccounts = Array.isArray(list) ? list : [];
                _cwRenderAccGrid();
            } catch (e) {
                document.getElementById('cwAccGrid').innerHTML = `<p style="color:#b91c1c;font-size:12px;">Erro ao carregar contas.</p>`;
            }
        }
        function _cwRenderAccGrid() {
            const grid = document.getElementById('cwAccGrid');
            if (!grid) return;
            grid.innerHTML = _cwData.selectableAccounts.map(acc => {
                const sel = _cwData.selectedAccounts.has(acc.id);
                return `<div class="cw-acc-pick ${sel ? 'sel' : ''}" onclick="_cwToggleAcc(${acc.id})">
                    <i class="fas fa-circle-check check"></i>
                    ${_campLogo(acc.name, acc.logo_url, 44)}
                    <div class="nm2">${escapeHtml(acc.name)}</div>
                    ${acc.is_target ? '<span class="tgt">TARGET</span>' : ''}
                    <div style="font-size:10px;color:#9ca3af;margin-top:3px;">${acc.contact_count || 0} contato(s)</div>
                </div>`;
            }).join('') || '<p style="color:#6b7280;font-size:12px;">Nenhuma conta cadastrada.</p>';
            _cwUpdateCount();
        }
        function _cwToggleAcc(id) {
            if (_cwData.selectedAccounts.has(id)) _cwData.selectedAccounts.delete(id);
            else _cwData.selectedAccounts.add(id);
            _cwRenderAccGrid();
        }
        function _cwSelectAll(select) {
            if (select) {
                _cwData.selectableAccounts.forEach(acc => _cwData.selectedAccounts.add(acc.id));
            } else {
                _cwData.selectedAccounts.clear();
            }
            _cwRenderAccGrid();
        }
        function _cwUpdateCount() {
            const el = document.getElementById('cwAccCount');
            if (el) el.textContent = _cwData.selectedAccounts.size;
        }

        async function _cwGenerate() {
            _cwError('');
            const a = _cwData.analysis || {};
            const mode = (document.querySelector('input[name="cwAccMode"]:checked') || {}).value || 'targets';
            const title = (document.getElementById('cwTitle').value || '').trim() || 'Campanha Ofensiva';
            const startDate = document.getElementById('cwStartDate').value || new Date().toISOString().slice(0,10);
            const capacity = parseInt(document.getElementById('cwCapacity').value || '5', 10) || 5;
            const accountIds = Array.from(_cwData.selectedAccounts);
            if (mode === 'manual' && !accountIds.length) { _cwError('Selecione ao menos uma conta.'); return; }
            if (mode === 'targets' && !(a.target_count > 0)) { _cwError('Não há contas marcadas como target. Selecione contas manualmente ou marque targets em Gestão de Conta.'); return; }

            _cwShowProgress(true);
            document.getElementById('cwStep3').style.display = 'none';
            _cwProgress(15, 'Montando plano de ação...');
            try {
                const res = await fetch(`${API_BASE}/campaigns/generate`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        title, challenge_text: _cwData.challenge,
                        areas: a.areas || [], decisores: a.decisores || [], offer_ids: a.offer_ids || [],
                        account_mode: mode, account_ids: accountIds,
                        start_date: startDate, weekly_capacity: capacity,
                        llm_source: a.llm_source || '', summary: a.entendimento || '', portfolio_note: a.portfolio_note || ''
                    })
                });
                const payload = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(payload.error || 'Falha ao gerar plano.');
                const taskId = payload.task_id;
                const poll = setInterval(async () => {
                    try {
                        const tr = await fetch(`${API_BASE}/tasks/${taskId}`);
                        const task = await tr.json();
                        if (task.progress) _cwProgress(task.progress, task.step || '');
                        if (task.status === 'done') {
                            clearInterval(poll);
                            closeCampaignWizard();
                            openCampaignPlan(task.result.campaign_id);
                        } else if (task.status === 'error' || task.status === 'not_found') {
                            clearInterval(poll);
                            _cwShowProgress(false); document.getElementById('cwStep3').style.display = '';
                            _cwError(task.error || 'Erro ao gerar plano.');
                        }
                    } catch (e) { clearInterval(poll); _cwShowProgress(false); document.getElementById('cwStep3').style.display=''; _cwError('Erro ao verificar status.'); }
                }, 800);
            } catch (e) { _cwShowProgress(false); document.getElementById('cwStep3').style.display=''; _cwError(e.message); }
        }

        // ── Plano vivo ──────────────────────────────────────────────────────
        async function openCampaignPlan(cid) {
            _campaignEnsureStyles();
            const listView = document.getElementById('campaignListView');
            const planView = document.getElementById('campaignPlanView');
            if (listView) listView.style.display = 'none';
            if (planView) { planView.style.display = ''; planView.innerHTML = '<p style="color:#6b7280;padding:20px;">Carregando plano...</p>'; }
            try {
                const res = await fetch(`${API_BASE}/campaigns/${cid}`);
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Erro ao carregar o plano.');
                // Align blocks to reference the same objects as accounts so in-memory mutations propagate to render
                const _accById = {};
                (data.accounts || []).forEach(a => { _accById[a.id] = a; });
                Object.keys(data.blocks || {}).forEach(bk => {
                    data.blocks[bk] = (data.blocks[bk] || []).map(a => _accById[a.id] || a);
                });
                _campaignPlanData = data;
                _campaignExpanded = new Set();
                _renderCampaignPlan();
            } catch (e) {
                if (planView) planView.innerHTML = `<div class="alert alert-error" style="display:block;">${escapeHtml(e.message)}</div><button class="btn btn-secondary" onclick="backToCampaignList()">Voltar</button>`;
            }
        }

        function _renderCampaignPlan() {
            const data = _campaignPlanData;
            const planView = document.getElementById('campaignPlanView');
            if (!data || !planView) return;
            const scrollEl = document.querySelector('.main-content');
            const savedScroll = scrollEl ? scrollEl.scrollTop : window.scrollY;
            const st = data.stats || {};
            const ringColor = st.progress >= 100 ? '#10b981' : (st.progress >= 50 ? '#6366f1' : '#8b5cf6');

            const blocksHTML = ['A','B','C','D'].map(bk => {
                const accs = (data.blocks && data.blocks[bk]) || [];
                if (!accs.length) return '';
                return _campBlockHTML(bk, accs);
            }).join('');

            const gapBanner = !data.has_solution ? `
                <div class="camp-gap-banner">
                    <i class="fas fa-lightbulb lead"></i>
                    <div>
                        <div style="font-weight:700;color:#6b21a8;margin-bottom:3px;">Solução não encontrada no portfólio</div>
                        <div style="font-size:13px;color:#6b21a8;">${escapeHtml(data.portfolio_note || 'Não há oferta aderente cadastrada para este desafio. Vale aprofundar as soluções da empresa para este segmento.')}</div>
                        <button class="btn btn-secondary btn-small camp-no-print" style="margin-top:10px;" onclick="switchTab(null,'portfolio')"><i class="fas fa-box-open"></i> Explorar portfólio e oportunidades</button>
                    </div>
                </div>` : '';

            const _upPhoto = userProfile?.photo_url;
            const _upName = userProfile?.full_name || userProfile?.nickname || '';
            const _upAvatar = _upPhoto
                ? `<img src="${escapeHtml(_upPhoto)}" alt="${escapeHtml(_upName)}">`
                : (_upName ? `<div class="camp-user-initial">${escapeHtml(_upName[0] || '?')}</div>` : '');
            const _upHTML = (_upAvatar || _upName)
                ? `<div class="camp-user-badge" title="${escapeHtml(_upName)}">${_upAvatar}${_upName ? `<span class="camp-user-name">${escapeHtml(_upName)}</span>` : ''}</div>`
                : '';

            planView.innerHTML = `
                <div class="camp-sticky">
                    <div>
                        <div class="title">${escapeHtml(data.title || 'Campanha')}</div>
                        <div class="sub">Criado em ${_campDate(data.created_at) || ''} · ${st.accounts_count || 0} contas · ${data.weekly_capacity || 5} ações/semana · ${st.weeks || 0} semanas</div>
                    </div>
                    <div class="spacer"></div>
                    <div class="camp-mini-prog">
                        <div class="lbl"><span>Progresso geral</span><span>${st.progress || 0}%</span></div>
                        <div class="camp-prog-track" style="background:rgba(255,255,255,.15);"><div class="camp-prog-fill" style="width:${st.progress || 0}%"></div></div>
                    </div>
                    <div class="camp-no-print" style="display:flex;gap:8px;align-items:center;">
                        <button class="btn btn-secondary btn-small" onclick="backToCampaignList()"><i class="fas fa-arrow-left"></i></button>
                        <button class="btn btn-auto-mapping btn-small" onclick="regenerateCampaign(${data.id})"><span class="ai-star-icon">✦</span> Atualizar com IA</button>
                        <button class="btn btn-secondary btn-small" onclick="exportCampaignPDF()"><i class="fas fa-file-pdf"></i> PDF</button>
                        <button class="btn btn-secondary btn-small" onclick="deleteCampaign(${data.id})" title="Excluir campanha"><i class="fas fa-trash"></i></button>
                    </div>
                    ${_upHTML}
                </div>

                <div class="camp-summary">
                    <h2>Resumo da estratégia</h2>
                    <div class="obj">${escapeHtml(data.llm_summary || data.objective_text || '')}</div>
                    <div class="camp-summary-grid">
                        <div><div class="camp-sg-label">Áreas-alvo</div>${(data.areas||[]).map(x=>`<span class="camp-chip">${escapeHtml(x)}</span>`).join('') || '—'}</div>
                        <div><div class="camp-sg-label">Decisores</div>${(data.decisores||[]).map(x=>`<span class="camp-chip dec">${escapeHtml(x)}</span>`).join('') || '—'}</div>
                        <div><div class="camp-sg-label">Período</div><div style="font-size:14px;color:#374151;font-weight:600;">${_campDate(data.start_date)} → ${st.weeks||0} semanas</div></div>
                    </div>
                </div>

                <div class="camp-stats">
                    ${_campStat('fa-building','#6366f1','#eef2ff', st.accounts_count||0, 'Contas no plano')}
                    ${_campStat('fa-bullhorn','#10b981','#dcfce7', data.weekly_capacity||5, 'Ações por semana')}
                    ${_campStat('fa-calendar-week','#f59e0b','#fef3c7', st.weeks||0, 'Semanas de plano')}
                    ${_campStat('fa-list-check','#8b5cf6','#f3e8ff', st.total_actions||0, 'Ações planejadas')}
                    <div class="camp-stat">
                        <div class="camp-ring" style="--p:${st.progress||0}; background:conic-gradient(${ringColor} calc(var(--p)*1%), #eef2f7 0);">
                            <div class="inner" style="color:${ringColor};">${st.progress||0}%</div>
                        </div>
                        <div>
                            <div style="font-size:12px;color:#16a34a;">✓ ${st.done||0} concluídas</div>
                            <div style="font-size:12px;color:#b45309;">◐ ${st.in_progress||0} em andamento</div>
                            <div style="font-size:12px;color:#6b7280;">○ ${st.pending||0} pendentes</div>
                        </div>
                    </div>
                </div>

                ${gapBanner}
                ${blocksHTML || '<p style="color:#6b7280;">Nenhuma conta no plano.</p>'}
                ${_campGanttHTML(data)}`;

            if (scrollEl) scrollEl.scrollTop = savedScroll; else window.scrollTo(0, savedScroll);
        }

        function _campStat(icon, color, bg, big, cap) {
            return `<div class="camp-stat"><div class="ic" style="background:${bg};color:${color};"><i class="fas ${icon}"></i></div><div><div class="big">${big}</div><div class="cap">${cap}</div></div></div>`;
        }

        function _campBlockHTML(bk, accs) {
            const m = CAMP_BLOCK_META[bk];
            const rows = accs.map(_campAccHTML).join('');
            return `
                <div class="camp-block" style="--bc:${m.color};">
                    <div class="camp-block-head" onclick="this.parentElement.querySelector('.camp-block-body').classList.toggle('camp-collapsed'); var _c=this.querySelector('.chev'); _c.classList.toggle('fa-chevron-up'); _c.classList.toggle('fa-chevron-down');">
                        <div class="num">${m.n}</div>
                        <div class="bicon"><i class="fas ${m.icon}"></i></div>
                        <div>
                            <h3>${m.name}</h3>
                            <div class="bdesc">${m.desc}</div>
                        </div>
                        <div class="camp-block-count">${accs.length} ${accs.length === 1 ? 'conta' : 'contas'}</div>
                        <i class="fas fa-chevron-up chev" style="margin-left:12px;color:#9ca3af;"></i>
                    </div>
                    <div class="camp-block-body">${rows}</div>
                </div>`;
        }

        function _campAccHTML(acc) {
            const actions = acc.actions || [];
            const nextAct = actions.find(a => a.status !== 'done') || actions[0] || null;
            const expanded = _campaignExpanded.has(acc.id);
            const am = nextAct ? _campActionMeta(nextAct.action_type) : _campActionMeta('outro');
            const score = acc.readiness_score || 0;
            const scoreColor = score >= 70 ? '#10b981' : (score >= 40 ? '#f59e0b' : '#ef4444');
            const detail = expanded ? _campAccDetailHTML(acc) : '';
            const doneCount = actions.filter(a => a.status === 'done').length;
            return `
                <div class="camp-acc">
                    <div class="camp-acc-row" onclick="toggleCampaignAccountExpand(${acc.id})">
                        ${_campLogo(acc.account_name, acc.logo_url, 40)}
                        <div style="flex:1;min-width:160px;">
                            <div class="nm">${escapeHtml(acc.account_name)} <span class="camp-readiness" style="background:${scoreColor};">${score}%</span></div>
                            <div class="rat">${escapeHtml(acc.rationale || '')}</div>
                        </div>
                        <div class="col-next">
                            <span class="camp-act-type" style="background:${am.color}22;color:${am.color};"><i class="fas ${am.icon}"></i> ${escapeHtml(nextAct ? nextAct.title : '—')}</span>
                            <div class="due">${actions.length} ${actions.length === 1 ? 'ação' : 'ações'}${nextAct && nextAct.due_date ? ' · próx. até ' + _campDate(nextAct.due_date) : ''}</div>
                        </div>
                        <div class="col-prog">
                            <div class="pl"><span>${doneCount}/${actions.length} ações</span><span>${acc.progress||0}%</span></div>
                            <div class="camp-prog-track"><div class="camp-prog-fill" style="width:${acc.progress||0}%"></div></div>
                        </div>
                        <i class="fas fa-chevron-${expanded ? 'up' : 'down'}" style="color:#cbd0da;margin-left:8px;"></i>
                    </div>
                    ${detail}
                </div>`;
        }

        function _campLogHTML(l) {
            const isSystem = l.log_type === 'system';
            const ts = escapeHtml((l.created_at || '').replace('T', ' ').slice(0, 16));
            const tools = isSystem ? '' : `
                <span class="camp-log-tools camp-no-print">
                    <button title="Editar" onclick="event.stopPropagation(); editCampaignLog(${l.id})"><i class="fas fa-pen"></i></button>
                    <button title="Excluir" onclick="event.stopPropagation(); deleteCampaignLog(${l.id})"><i class="fas fa-trash"></i></button>
                </span>`;
            return `
                <li class="${isSystem ? 'system' : ''}" id="camplogli_${l.id}">
                    ${isSystem ? '<i class="fas fa-robot" style="color:#8b5cf6;margin-right:5px;"></i>' : ''}<span class="camp-log-text">${escapeHtml(l.log_text)}</span>
                    <div class="ts">${ts}${tools}</div>
                </li>`;
        }

        function _campActionCardHTML(acc, act) {
            const am = _campActionMeta(act.action_type);
            const stm = CAMP_STATUS_META[act.status] || CAMP_STATUS_META.pending;
            const logs = (act.logs || []).map(_campLogHTML).join('')
                || '<li style="color:#9ca3af;border:none;background:none;padding-left:0;">Nenhum update ainda.</li>';
            const contactHtml = act.contact_id
                ? `<a href="#" onclick="event.preventDefault(); openCampaignContact(${act.contact_id})" style="color:#6366f1;text-decoration:none;cursor:pointer;" title="Ver ficha do contato"><i class="fas fa-user"></i> ${escapeHtml(act.contact_name || '')}</a>`
                : (act.contact_name ? `<span style="color:#6366f1;"><i class="fas fa-user"></i> ${escapeHtml(act.contact_name)}</span>` : '');
            const angle = act.angle_area ? `<span class="camp-angle-chip">ângulo: ${escapeHtml(act.angle_area)}</span>` : '';
            return `
                <div class="camp-action-card">
                    <div class="camp-action-head">
                        <span class="camp-act-type" style="background:${am.color}22;color:${am.color};"><i class="fas ${am.icon}"></i> ${escapeHtml(act.title)}</span>
                        ${angle}
                        ${act.due_date ? `<span class="camp-action-due">até ${_campDate(act.due_date)} · sem. ${act.scheduled_week || 1}</span>` : ''}
                        <span style="flex:1;"></span>
                        <button class="camp-status-btn ${stm.cls} camp-no-print" onclick="toggleCampaignAction(${act.id})"><i class="fas ${stm.icon}"></i> ${stm.label}</button>
                    </div>
                    <div class="desc"><b>Abordagem:</b> ${escapeHtml(act.description || '')}${contactHtml ? ' · ' + contactHtml : ''}</div>
                    <div class="camp-sg-label" style="margin-top:12px;">Updates / log de execução</div>
                    <ul class="camp-logs">${logs}</ul>
                    <div class="camp-log-add camp-no-print">
                        <input type="text" id="camplog_${act.id}" placeholder="Escreva um update desta ação..." onkeydown="if(event.key==='Enter'){ event.preventDefault(); addCampaignLog(${act.id}); }">
                        <button class="btn btn-secondary btn-small" onclick="addCampaignLog(${act.id})"><i class="fas fa-plus"></i> Registrar</button>
                    </div>
                </div>`;
        }

        function _campAccDetailHTML(acc) {
            const actions = acc.actions || [];
            const challenge = (_campaignPlanData || {}).objective_text || '';
            const insight = (acc.market_insight || '').trim();
            const sources = acc.insight_sources || [];
            const srcHtml = sources.length
                ? `<div class="camp-insight-src camp-no-print">Fontes: ${sources.map(s => s.url ? `<a href="${escapeHtml(s.url)}" target="_blank" rel="noopener">${escapeHtml((s.title || s.url).slice(0, 40))}</a>` : '').filter(Boolean).join(' · ')}</div>`
                : '';
            const insightHtml = insight
                ? `<div class="camp-insight">
                       <div class="camp-insight-title"><i class="fas fa-chart-line"></i> Insight de mercado · motivo da abordagem</div>
                       <div class="camp-insight-body">${escapeHtml(insight)}</div>
                       ${srcHtml}
                   </div>`
                : '';
            const offerHtml = acc.offer_id
                ? `<a href="#" onclick="event.preventDefault(); openCampaignOfferModal(${acc.offer_id}, '${escapeHtml(acc.account_name||'')}', '${escapeHtml(challenge)}')" style="display:inline-flex;align-items:center;gap:5px;margin:4px 0 12px;color:#6366f1;font-size:12.5px;text-decoration:none;cursor:pointer;" title="Ver detalhes da solução recomendada"><i class="fas fa-box-open"></i> Solução recomendada: ${escapeHtml(acc.offer_title || '—')}</a>`
                : '';
            const cards = actions.map(act => _campActionCardHTML(acc, act)).join('')
                || '<p style="color:#9ca3af;font-size:13px;">Nenhuma ação planejada.</p>';
            return `
                <div class="camp-acc-detail">
                    ${insightHtml}
                    ${offerHtml}
                    ${cards}
                </div>`;
        }

        async function openCampaignOfferModal(offerId, accountName, challengeText) {
            document.getElementById('campOfferModal')?.remove();
            const el = document.createElement('div');
            el.id = 'campOfferModal';
            el.innerHTML = `
                <div class="modal active" id="campOfferModalInner" style="z-index:10002;">
                    <div class="modal-content" style="max-width:620px;">
                        <div class="modal-header">
                            <h2 class="modal-title"><i class="fas fa-box-open" style="color:#6366f1;"></i> Solução recomendada</h2>
                            <button class="modal-close" onclick="document.getElementById('campOfferModal')?.remove()">&#215;</button>
                        </div>
                        <div id="campOfferBody" style="padding:4px 0 8px;"><p style="color:#6b7280;">Carregando...</p></div>
                    </div>
                </div>`;
            document.body.appendChild(el);
            try {
                const res = await fetch(`${API_BASE}/portfolio/offers/${offerId}`);
                const offer = await res.json();
                if (!res.ok) throw new Error(offer.error || 'Erro ao carregar oferta.');
                const items = (offer.items || []).map(it => `
                    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px;margin-bottom:8px;">
                        <div style="font-size:12px;font-weight:700;color:#ef4444;margin-bottom:4px;"><i class="fas fa-exclamation-circle"></i> Dor</div>
                        <div style="font-size:13px;color:#374151;margin-bottom:8px;">${escapeHtml(it.pain || '')}</div>
                        <div style="font-size:12px;font-weight:700;color:#10b981;margin-bottom:4px;"><i class="fas fa-check-circle"></i> Solução</div>
                        <div style="font-size:13px;color:#374151;">${escapeHtml(it.solution || '')}</div>
                    </div>`).join('') || '<p style="color:#9ca3af;font-size:13px;">Sem itens cadastrados.</p>';
                document.getElementById('campOfferBody').innerHTML = `
                    <div style="margin-bottom:16px;">
                        <div style="font-size:18px;font-weight:800;color:#111827;margin-bottom:6px;">${escapeHtml(offer.title || '')}</div>
                        ${offer.summary ? `<div style="font-size:13.5px;color:#374151;line-height:1.6;">${escapeHtml(offer.summary)}</div>` : ''}
                    </div>
                    <div style="font-size:12px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px;">Dores e soluções</div>
                    ${items}
                    ${accountName ? `
                    <div style="margin-top:16px;padding:12px 14px;background:#eef2ff;border-radius:10px;border:1px solid #c7d2fe;">
                        <div style="font-size:12px;font-weight:700;color:#4338ca;margin-bottom:4px;"><span class="ai-star-icon">✦</span> Por que faz sentido para ${escapeHtml(accountName)}</div>
                        <div id="campOfferRationale" style="font-size:13px;color:#374151;">
                            <button class="btn btn-auto-mapping btn-small" onclick="generateCampaignOfferRationale(${offerId}, '${escapeHtml(accountName)}', '${escapeHtml(challengeText)}')"><span class="ai-star-icon">✦</span> Gerar análise de fit</button>
                        </div>
                    </div>` : ''}
                    <div style="margin-top:14px;text-align:right;">
                        <button class="btn btn-secondary btn-small" onclick="document.getElementById('campOfferModal')?.remove(); switchTab(null,'portfolio')"><i class="fas fa-arrow-up-right-from-square"></i> Abrir no Portfólio</button>
                    </div>`;
            } catch (e) {
                const b = document.getElementById('campOfferBody');
                if (b) b.innerHTML = `<p style="color:#b91c1c;">${escapeHtml(e.message)}</p>`;
            }
        }

        async function generateCampaignOfferRationale(offerId, accountName, challengeText) {
            const el = document.getElementById('campOfferRationale');
            if (!el) return;
            el.innerHTML = '<span style="color:#6b7280;font-size:13px;"><i class="fas fa-spinner fa-spin"></i> Gerando análise...</span>';
            try {
                const res = await fetch(`${API_BASE}/portfolio/offers/${offerId}`);
                const offer = await res.json();
                const itemTexts = (offer.items || []).map(it => `Dor: ${it.pain || ''}; Solução: ${it.solution || ''}`).join(' | ');
                const prompt = `Você é um consultor de vendas B2B. Explique em 3 frases DIRETAS e ESPECÍFICAS por que a oferta "${offer.title}" (${offer.summary || ''}) faz sentido para a conta "${accountName}" no contexto do desafio: "${challengeText}". Itens: ${itemTexts}. Seja objetivo e mencione conexões concretas.`;
                const analyzeRes = await fetch(`${API_BASE}/campaigns/analyze`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ challenge_text: `RATIONALE_REQUEST: ${prompt}` })
                });
                const taskData = await analyzeRes.json();
                if (!analyzeRes.ok) throw new Error(taskData.error || 'Erro');
                const poll = setInterval(async () => {
                    try {
                        const tr = await fetch(`${API_BASE}/tasks/${taskData.task_id}`);
                        const task = await tr.json();
                        if (task.status === 'done') {
                            clearInterval(poll);
                            const rationaleEl = document.getElementById('campOfferRationale');
                            if (rationaleEl) rationaleEl.innerHTML = `<div style="font-size:13px;color:#374151;line-height:1.6;">${escapeHtml((task.result && task.result.entendimento) || 'Análise gerada com sucesso.')}</div>`;
                        } else if (task.status === 'error' || task.status === 'not_found') {
                            clearInterval(poll);
                            const rationaleEl = document.getElementById('campOfferRationale');
                            if (rationaleEl) rationaleEl.innerHTML = `<span style="color:#b91c1c;font-size:12px;">${escapeHtml(task.error || 'Erro ao gerar análise.')}</span>`;
                        }
                    } catch (e2) { clearInterval(poll); }
                }, 900);
            } catch (e) {
                if (el) el.innerHTML = `<span style="color:#b91c1c;font-size:12px;">${escapeHtml(e.message)}</span>`;
            }
        }

        function _campGanttHTML(data) {
            const weeks = data.timeline || [];
            if (!weeks.length) return '';
            const totalWeeks = weeks.length;
            const midWeek = totalWeeks >= 4 ? Math.ceil(totalWeeks / 2) : 0;
            const cols = weeks.map(w => {
                const dots = Object.entries(w.counts || {}).map(([t, n]) => {
                    const m = _campActionMeta(t);
                    return Array.from({length: n}).map(() => `<span class="dot" style="background:${m.color};"></span>`).join('');
                }).join('');
                let milestone = '';
                if (w.week === 1) milestone = '<div class="camp-milestone"><i class="fas fa-flag"></i> Kickoff do plano</div>';
                else if (w.week === midWeek) milestone = '<div class="camp-milestone"><i class="fas fa-rotate"></i> Revisão de progresso</div>';
                else if (w.week === totalWeeks) milestone = '<div class="camp-milestone"><i class="fas fa-trophy"></i> Fechamento do ciclo</div>';
                return `
                    <div class="camp-week">
                        <div class="wk">Semana ${w.week}</div>
                        <div class="dt">${w.start} – ${w.end}</div>
                        <div class="dots">${dots || '<span style="font-size:11px;color:#6b6692;">—</span>'}</div>
                        <div class="wtotal">${w.total} ${w.total === 1 ? 'ação' : 'ações'}</div>
                        ${milestone}
                    </div>`;
            }).join('');
            const legend = Object.values(CAMP_ACTION_META).filter(m => m.label !== 'Ação').map(m =>
                `<span><i style="background:${m.color};"></i> ${m.label}</span>`).join('');
            return `
                <div class="camp-gantt">
                    <h2><i class="fas fa-stream"></i> Cronograma Macro</h2>
                    <p class="gsub">Distribuição das ações ao longo das semanas, respeitando a capacidade de ${data.weekly_capacity || 5} por semana.</p>
                    <div class="camp-gantt-scroll"><div class="camp-gantt-track">${cols}</div></div>
                    <div class="camp-legend">${legend}</div>
                </div>`;
        }

        function toggleCampaignAccountExpand(caId) {
            if (_campaignExpanded.has(caId)) _campaignExpanded.delete(caId);
            else _campaignExpanded.add(caId);
            _renderCampaignPlan();
        }

        async function toggleCampaignAction(actionId) {
            // localizar a ação no estado
            let target = null;
            (_campaignPlanData.accounts || []).forEach(a => (a.actions || []).forEach(act => { if (act.id === actionId) target = { a, act }; }));
            if (!target) return;
            const next = (CAMP_STATUS_META[target.act.status] || CAMP_STATUS_META.pending).next;
            try {
                const res = await fetch(`${API_BASE}/campaigns/actions/${actionId}`, {
                    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ status: next })
                });
                const payload = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(payload.error || 'Erro ao atualizar status.');
                target.act.status = next;
                _campRecomputeStats();
                _renderCampaignPlan();
            } catch (e) { showError(e.message); }
        }

        function _campRecomputeStats() {
            const data = _campaignPlanData;
            if (!data) return;
            let total = 0, done = 0, inprog = 0;
            (data.accounts || []).forEach(a => {
                let at = 0, ad = 0;
                (a.actions || []).forEach(act => {
                    total++; at++;
                    if (act.status === 'done') { done++; ad++; }
                    else if (act.status === 'in_progress') inprog++;
                });
                a.progress = at ? Math.round(100 * ad / at) : 0;
            });
            data.stats = Object.assign(data.stats || {}, {
                total_actions: total, done, in_progress: inprog, pending: total - done - inprog,
                progress: total ? Math.round(100 * done / total) : 0
            });
        }

        async function addCampaignLog(actionId) {
            const input = document.getElementById('camplog_' + actionId);
            const text = (input && input.value || '').trim();
            if (!text) { showError('Escreva um update antes de registrar.'); return; }
            try {
                const res = await fetch(`${API_BASE}/campaigns/actions/${actionId}/logs`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ log_text: text })
                });
                const log = await res.json();
                if (!res.ok) throw new Error(log.error || 'Erro ao registrar update.');
                (_campaignPlanData.accounts || []).forEach(a => (a.actions || []).forEach(act => {
                    if (act.id === actionId) { act.logs = act.logs || []; act.logs.unshift(log); }
                }));
                _renderCampaignPlan();
            } catch (e) { showError(e.message); }
        }

        async function openCampaignContact(clientId) {
            // Abre a ficha (visualização) do contato, não a edição.
            if (!Array.isArray(clients) || !clients.find(c => Number(c.id) === Number(clientId))) {
                try {
                    const r = await fetch(`${API_BASE}/clientes`);
                    clients = await r.json();
                } catch (e) { /* segue; openProfileModal trata ausência */ }
            }
            openProfileModal(Number(clientId));
        }

        async function editCampaignLog(logId) {
            let cur = '';
            (_campaignPlanData.accounts || []).forEach(a => (a.actions || []).forEach(act => (act.logs || []).forEach(l => {
                if (l.id === logId) cur = l.log_text || '';
            })));
            const next = await uiPrompt('Editar update de execução:', cur, 'Editar update');
            if (next === null || next === false || next === undefined) return;
            const text = (next || '').trim();
            if (!text) { showError('O update não pode ficar vazio. Para remover, use excluir.'); return; }
            try {
                const res = await fetch(`${API_BASE}/campaigns/logs/${logId}`, {
                    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ log_text: text })
                });
                const updated = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(updated.error || 'Erro ao editar update.');
                (_campaignPlanData.accounts || []).forEach(a => (a.actions || []).forEach(act => (act.logs || []).forEach(l => {
                    if (l.id === logId) { l.log_text = updated.log_text; }
                })));
                _renderCampaignPlan();
            } catch (e) { showError(e.message); }
        }

        async function deleteCampaignLog(logId) {
            if (!await uiConfirm('Excluir este update de execução?', 'Excluir update')) return;
            try {
                const res = await fetch(`${API_BASE}/campaigns/logs/${logId}`, { method: 'DELETE' });
                const payload = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(payload.error || 'Erro ao excluir update.');
                (_campaignPlanData.accounts || []).forEach(a => (a.actions || []).forEach(act => {
                    if (Array.isArray(act.logs)) act.logs = act.logs.filter(l => l.id !== logId);
                }));
                _renderCampaignPlan();
            } catch (e) { showError(e.message); }
        }

        async function regenerateCampaign(cid) {
            if (!await uiConfirm('A IA vai reavaliar o portfólio e o mapeamento atuais e atualizar o plano. Seus checkmarks e updates manuais serão preservados.', 'Atualizar plano com IA')) return;
            const planView = document.getElementById('campaignPlanView');
            const overlay = document.createElement('div');
            overlay.id = 'campRegenOverlay';
            overlay.style.cssText = 'position:fixed;inset:0;background:rgba(18,16,31,.55);z-index:9999;display:flex;align-items:center;justify-content:center;';
            overlay.innerHTML = `<div style="background:#fff;border-radius:14px;padding:26px 30px;text-align:center;min-width:320px;">
                <img src="/images/coelho-correndo.webp" alt="" style="height:40px;width:auto;">
                <div id="campRegenStep" style="font-size:13px;color:#6b7280;margin:10px 0;">Reanalisando...</div>
                <div style="position:relative;background:#ede9fe;border-radius:99px;height:10px;margin:0 8px;"><div id="campRegenBar" style="height:100%;width:10%;background:linear-gradient(90deg,#6366f1,#8b5cf6);border-radius:99px;transition:width .5s;"></div></div>
            </div>`;
            document.body.appendChild(overlay);
            try {
                const res = await fetch(`${API_BASE}/campaigns/${cid}/regenerate`, { method: 'POST' });
                const payload = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(payload.error || 'Erro ao atualizar.');
                const taskId = payload.task_id;
                const poll = setInterval(async () => {
                    try {
                        const tr = await fetch(`${API_BASE}/tasks/${taskId}`);
                        const task = await tr.json();
                        const bar = document.getElementById('campRegenBar');
                        const step = document.getElementById('campRegenStep');
                        if (bar && task.progress) bar.style.width = task.progress + '%';
                        if (step && task.step) step.textContent = task.step;
                        if (task.status === 'done') {
                            clearInterval(poll);
                            document.getElementById('campRegenOverlay')?.remove();
                            showSuccess('Plano atualizado pela IA.');
                            openCampaignPlan(cid);
                        } else if (task.status === 'error' || task.status === 'not_found') {
                            clearInterval(poll);
                            document.getElementById('campRegenOverlay')?.remove();
                            showError(task.error || 'Erro ao atualizar plano.');
                        }
                    } catch (e) { clearInterval(poll); document.getElementById('campRegenOverlay')?.remove(); showError('Erro ao verificar status.'); }
                }, 800);
            } catch (e) { document.getElementById('campRegenOverlay')?.remove(); showError(e.message); }
        }

        async function deleteCampaign(cid) {
            if (!await uiConfirm('Excluir esta campanha e todo o seu plano de ação? Esta ação não pode ser desfeita.', 'Excluir Campanha')) return;
            try {
                const res = await fetch(`${API_BASE}/campaigns/${cid}`, { method: 'DELETE' });
                const payload = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(payload.error || 'Erro ao excluir.');
                showSuccess('Campanha excluída.');
                backToCampaignList();
            } catch (e) { showError(e.message); }
        }

        function exportCampaignPDF() {
            showSuccess('Abrindo impressão — escolha "Salvar como PDF".');
            // Expande todas as contas para que o PDF inclua insights e todas as ações.
            const prevExpanded = _campaignExpanded;
            _campaignExpanded = new Set((_campaignPlanData?.accounts || []).map(a => a.id));
            _renderCampaignPlan();
            setTimeout(() => {
                window.print();
                // Restaura o estado de expansão após a impressão.
                _campaignExpanded = prevExpanded;
                _renderCampaignPlan();
            }, 400);
        }

        // Permite colapsar o corpo de um bloco
        (function(){
            const s = document.getElementById('campaign-collapse-style');
            if (!s) {
                const el = document.createElement('style');
                el.id = 'campaign-collapse-style';
                el.textContent = '.camp-block-body.camp-collapsed{display:none;}';
                document.head.appendChild(el);
            }
        })();

        function loadPortfolio() {
            switchPortfolioSubmodule(_portfolioCurrentSubTab || 'stf');
        }

        function switchPortfolioSubmodule(subTab) {
            const tabs = ['stf', 'iata', 'whitespace'];
            tabs.forEach(tab => {
                const panel = document.getElementById(`portfolioSubPanel_${tab}`);
                const btn = document.getElementById(`portfolioSubBtn_${tab}`);
                const isActive = tab === subTab;
                if (panel) panel.style.display = isActive ? '' : 'none';
                if (btn) btn.className = isActive ? 'btn btn-auto-mapping' : 'btn btn-secondary';
            });
            _portfolioCurrentSubTab = subTab;
            if (subTab === 'stf') _loadSTFSolutions();
            else if (subTab === 'iata') loadIAta();
            else if (subTab === 'whitespace') loadWhitespaceMatrix();
        }

        // Whitespace de ofertas (Bloco 12) — matriz contas target × ofertas
        async function loadWhitespaceMatrix() {
            const el = document.getElementById('whitespaceContent');
            if (!el) return;
            el.innerHTML = '<p class="toca-text">Carregando matriz...</p>';
            try {
                const resp = await fetch(`${API_BASE}/portfolio/whitespace-matrix`);
                const data = await resp.json();
                if (!resp.ok) throw new Error(data.error || 'Erro ao carregar a matriz.');
                if (!data.offers.length) { el.innerHTML = '<div class="empty-state"><p>Nenhuma oferta cadastrada no Portfólio.</p></div>'; return; }
                if (!data.rows.length) { el.innerHTML = '<div class="empty-state"><p>Nenhuma conta marcada como target.</p></div>'; return; }
                const head = data.offers.map(o => `<th style="padding:8px 6px; font-size:11px; max-width:110px; word-break:break-word;">${escapeHtml(o.title)}</th>`).join('');
                const body = data.rows.map(r => {
                    const cells = data.offers.map(o => {
                        const has = r.cells[String(o.id)];
                        return `<td style="text-align:center; padding:6px;" title="${escapeHtml(r.name)} × ${escapeHtml(o.title)}: ${has ? 'presente' : 'nunca explorada'}">${has ? '✅' : '⬜'}</td>`;
                    }).join('');
                    return `<tr><td class="toca-text-strong" style="font-weight:600; padding:6px 10px; white-space:nowrap;">${escapeHtml(r.name)}</td>${cells}</tr>`;
                }).join('');
                el.innerHTML = `<div style="overflow-x:auto;"><table class="data-table" style="min-width:520px;">
                    <thead><tr><th style="padding:8px 10px;">Conta target</th>${head}</tr></thead>
                    <tbody>${body}</tbody></table></div>`;
            } catch (e) {
                el.innerHTML = `<div class="alert alert-error" style="display:block;">${escapeHtml(e.message)}</div>`;
            }
        }

        async function _loadSTFSolutions() {
            const container = document.getElementById('portfolioContent');
            if (!container) return;
            container.innerHTML = '<p style="color:#6b7280;">Carregando ofertas...</p>';
            try {
                const response = await fetch(`${API_BASE}/portfolio/offers`);
                const payload = await response.json().catch(() => []);
                if (!response.ok) throw new Error(payload.error || 'Erro ao carregar ofertas.');
                portfolioOffers = Array.isArray(payload) ? payload : [];
                renderPortfolioOffers(portfolioOffers);
            } catch (error) {
                container.innerHTML = `<div class="alert alert-error" style="display:block;">${escapeHtml(error.message || 'Erro ao carregar portifólio.')}</div>`;
            }
        }

        function exportSTFSolutions() {
            if (!portfolioOffers || !portfolioOffers.length) return showError('Nenhuma solução para exportar.');
            window.location.href = `${API_BASE}/portfolio/offers/export-json`;
        }

        async function importSTFSolutions(event) {
            const file = event.target.files?.[0];
            event.target.value = '';
            if (!file) return;
            const formData = new FormData();
            formData.append('file', file);
            try {
                const res = await fetch(`${API_BASE}/portfolio/offers/import-json`, { method: 'POST', body: formData });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(data.error || 'Falha na importação.');
                showSuccess(`${data.imported} solução(ões) importada(s) com sucesso.`);
                await _loadSTFSolutions();
            } catch (err) {
                showError(err.message || 'Erro ao importar soluções STF.');
            }
        }

        function renderPortfolioOffers(offers = []) {
            const container = document.getElementById('portfolioContent');
            if (!container) return;
            if (!offers.length) {
                container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">📁</div><h3 style="color:#e2dfd5;">Nenhuma oferta cadastrada</h3><p style="color:#e2dfd5;">Clique em "Nova Oferta" para analisar um texto/PDF com IA.</p></div>`;
                return;
            }
            container.innerHTML = offers.map(offer => {
                const offerId = Number(offer.id);
                const isExpanded = expandedPortfolioOffers.has(offerId);
                const items = Array.isArray(offer.items) ? offer.items : [];
                const summary = offer.summary || '';
                return `
                    <div class="history-item" style="border:1px solid rgba(16,185,129,.25); border-radius:12px; margin-bottom:10px; background:#fff;">
                        <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:10px;">
                            <div style="flex:1; min-width:0;">
                                <div style="display:flex; align-items:center; gap:8px; color:#065f46;">
                                    <i class="fas fa-briefcase"></i>
                                    <h3 style="margin:0; font-size:16px;">${escapeHtml(offer.title || 'Oferta sem título')}</h3>
                                </div>
                                <p style="margin:6px 0 0; color:#4b5563; ${isExpanded ? '' : 'white-space:nowrap; overflow:hidden; text-overflow:ellipsis;'}">${escapeHtml(summary || 'Sem resumo.')}</p>
                            </div>
                            <div style="display:flex; gap:6px;">
                                <button class="btn btn-secondary btn-small" onclick="toggleOfferExpand(${offerId})" title="Expandir/Colapsar">${isExpanded ? '▲' : '▼'}</button>
                                <button class="btn btn-secondary btn-small" onclick="openEditOfferModal(${offerId})" title="Editar"><i class="fas fa-edit"></i></button>
                                <button class="btn btn-danger btn-small" onclick="deleteOffer(${offerId})" title="Excluir"><i class="fas fa-trash"></i></button>
                            </div>
                        </div>
                        ${isExpanded ? `
                            <div style="margin-top:10px;" class="table-container">
                                <table>
                                    <thead>
                                        <tr><th>Dor do Cliente</th><th>Solução</th></tr>
                                    </thead>
                                    <tbody>
                                        ${items.length ? items.map(item => `
                                            <tr>
                                                <td>${escapeHtml(item.pain || '-')}</td>
                                                <td>${escapeHtml(item.solution || '-')}</td>
                                            </tr>
                                        `).join('') : '<tr><td colspan="2">Nenhum par dor/solução cadastrado.</td></tr>'}
                                    </tbody>
                                </table>
                            </div>` : ''}
                    </div>
                `;
            }).join('');
        }

        function toggleOfferExpand(offerId) {
            const key = Number(offerId);
            if (expandedPortfolioOffers.has(key)) expandedPortfolioOffers.delete(key);
            else expandedPortfolioOffers.add(key);
            renderPortfolioOffers(portfolioOffers);
        }

        function closePortfolioModal(modalId) {
            const modal = document.getElementById(modalId);
            if (modal) modal.remove();
        }

        function openNewOfferModal() {
            closePortfolioModal('portfolioNewModal');
            const html = `
                <div class="modal active" id="portfolioNewModal" onclick="if(event.target===this&&!document.getElementById('portfolioProgressArea')?.offsetParent) closePortfolioModal('portfolioNewModal')">
                    <div class="modal-content" style="max-width:760px;">
                        <div class="modal-header">
                            <h2 class="modal-title">Nova Oferta</h2>
                            <button class="modal-close" onclick="closePortfolioModal('portfolioNewModal')">&#215;</button>
                        </div>
                        <div id="portfolioFormArea">
                            <div class="form-group">
                                <label>Cole o texto do material</label>
                                <textarea id="portfolioRawInput" rows="8" placeholder="Cole aqui o texto base para análise..."></textarea>
                            </div>
                            <div class="form-group">
                                <label>OU envie um PDF ou Imagem</label>
                                <input id="portfolioUploadFile" type="file" accept=".pdf,application/pdf,image/jpeg,image/png,image/webp,image/gif,.jpg,.jpeg,.png,.webp,.gif">
                            </div>
                        </div>
                        <div id="portfolioProgressArea" style="display:none; padding:20px 4px 8px;">
                            <div style="font-size:13px; color:var(--text-secondary,#888); margin-bottom:10px; text-align:center;" id="portfolioProgressStep">Iniciando análise...</div>
                            <div style="background:var(--border-color,#e5e7eb); border-radius:99px; height:10px; overflow:hidden;">
                                <div id="portfolioProgressBar" style="height:100%; width:0%; background:linear-gradient(90deg,#7c3aed,#a855f7); border-radius:99px; transition:width 0.5s ease;"></div>
                            </div>
                            <div style="font-size:11px; color:var(--text-secondary,#aaa); text-align:right; margin-top:5px;" id="portfolioProgressPct">0%</div>
                        </div>
                        <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:4px;">
                            <button id="portfolioCancelBtn" class="btn btn-secondary" onclick="closePortfolioModal('portfolioNewModal')">Cancelar</button>
                            <button id="portfolioSubmitBtn" class="btn btn-auto-mapping btn-small" onclick="submitNewOffer()"><span class="ai-star-icon">✦</span> Analisar com IA</button>
                        </div>
                    </div>
                </div>
            `;
            document.body.insertAdjacentHTML('beforeend', html);
        }

        function _portfolioSetProgress(pct, step) {
            const bar = document.getElementById('portfolioProgressBar');
            const stepEl = document.getElementById('portfolioProgressStep');
            const pctEl = document.getElementById('portfolioProgressPct');
            if (bar) bar.style.width = pct + '%';
            if (stepEl) stepEl.textContent = step || '';
            if (pctEl) pctEl.textContent = Math.round(pct) + '%';
        }

        async function submitNewOffer() {
            const input = (document.getElementById('portfolioRawInput')?.value || '').trim();
            const uploadFile = document.getElementById('portfolioUploadFile')?.files?.[0] || null;
            if (!input && !uploadFile) {
                showError('Informe um texto ou envie um PDF ou imagem.');
                return;
            }

            const btn = document.getElementById('portfolioSubmitBtn');
            const cancelBtn = document.getElementById('portfolioCancelBtn');
            const formArea = document.getElementById('portfolioFormArea');
            const progressArea = document.getElementById('portfolioProgressArea');

            if (btn) { btn.disabled = true; btn.style.display = 'none'; }
            if (cancelBtn) cancelBtn.style.display = 'none';
            if (formArea) formArea.style.display = 'none';
            if (progressArea) progressArea.style.display = 'block';
            _portfolioSetProgress(10, 'Enviando arquivo...');

            try {
                const fd = new FormData();
                if (input) fd.append('raw_input', input);
                if (uploadFile) fd.append('upload_file', uploadFile);

                const response = await fetch(`${API_BASE}/portfolio/offers`, { method: 'POST', body: fd });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.error || 'Erro ao iniciar análise.');

                const taskId = payload.task_id;
                if (!taskId) throw new Error('Resposta inesperada do servidor.');

                _portfolioSetProgress(15, 'Aguardando processamento...');

                // Expõe botão fechar para continuar em background
                const closePortfolioBtn = document.querySelector('#portfolioNewModal .modal-close');
                if (closePortfolioBtn) closePortfolioBtn.style.display = '';

                // Botões Cancelar / Minimizar no topo da barra de progresso
                const _portProgressEl = document.getElementById('portfolioProgressArea');
                _attachBgTaskControls(
                    _portProgressEl, taskId,
                    () => closePortfolioModal('portfolioNewModal'),
                    () => { closePortfolioModal('portfolioNewModal'); showError('Tarefa cancelada.'); }
                );

                const sourceTab = typeof _currentTab !== 'undefined' ? _currentTab : 'portfolio';
                BgTaskManager.register(
                    taskId,
                    `${API_BASE}/portfolio/offers/tasks/${taskId}`,
                    'Analisando Oferta com IA',
                    sourceTab,
                    (_offer) => {
                        closePortfolioModal('portfolioNewModal');
                        showSuccess('Oferta criada com sucesso.');
                        loadPortfolio();
                    },
                    (errMsg) => {
                        showError(errMsg || 'Erro ao analisar material com IA.');
                        if (btn) { btn.disabled = false; btn.style.display = ''; }
                        if (cancelBtn) cancelBtn.style.display = '';
                        if (formArea) formArea.style.display = '';
                        if (progressArea) progressArea.style.display = 'none';
                    },
                    (pct, step) => _portfolioSetProgress(pct, step)
                );
            } catch (error) {
                showError(error.message || 'Erro ao analisar material com IA.');
                if (btn) { btn.disabled = false; btn.style.display = ''; }
                if (cancelBtn) cancelBtn.style.display = '';
                if (formArea) formArea.style.display = '';
                if (progressArea) progressArea.style.display = 'none';
            }
        }

        function openEditOfferModal(offerId) {
            const offer = portfolioOffers.find(item => Number(item.id) === Number(offerId));
            if (!offer) return showError('Oferta não encontrada.');
            closePortfolioModal('portfolioEditModal');
            const items = Array.isArray(offer.items) ? offer.items : [];
            const html = `
                <div class="modal active" id="portfolioEditModal" onclick="if(event.target===this) closePortfolioModal('portfolioEditModal')">
                    <div class="modal-content" style="max-width:920px;">
                        <div class="modal-header">
                            <h2 class="modal-title">Editar Oferta</h2>
                            <button class="modal-close" onclick="closePortfolioModal('portfolioEditModal')">&#215;</button>
                        </div>
                        <input type="hidden" id="portfolioEditOfferId" value="${offer.id}">
                        <div class="form-group">
                            <label>Título</label>
                            <input id="portfolioEditTitle" type="text" value="${escapeHtml(offer.title || '')}">
                        </div>
                        <div class="form-group">
                            <label>Resumo</label>
                            <textarea id="portfolioEditSummary" rows="3">${escapeHtml(offer.summary || '')}</textarea>
                        </div>
                        <div class="table-container" style="margin-top:8px;">
                            <table>
                                <thead><tr><th>Dor do Cliente</th><th>Solução</th><th style="width:80px;">Ações</th></tr></thead>
                                <tbody id="portfolioEditItemsBody">
                                    ${items.map(item => `
                                        <tr data-item-id="${item.id}">
                                            <td><textarea rows="2" data-role="pain">${escapeHtml(item.pain || '')}</textarea></td>
                                            <td><textarea rows="2" data-role="solution">${escapeHtml(item.solution || '')}</textarea></td>
                                            <td><button class="btn btn-danger btn-small" onclick="deleteOfferItem(${offer.id}, ${item.id})"><i class="fas fa-trash"></i></button></td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                        <div style="display:flex; justify-content:space-between; margin-top:10px; gap:8px;">
                            <button class="btn btn-secondary btn-small" onclick="addOfferItemRow()">+ Adicionar linha</button>
                            <div style="display:flex; gap:8px;">
                                <button class="btn btn-secondary" onclick="closePortfolioModal('portfolioEditModal')">Cancelar</button>
                                <button class="btn btn-primary" onclick="saveOfferEdits()">Salvar</button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            document.body.insertAdjacentHTML('beforeend', html);
        }

        function addOfferItemRow() {
            const tbody = document.getElementById('portfolioEditItemsBody');
            if (!tbody) return;
            tbody.insertAdjacentHTML('beforeend', `
                <tr data-item-id="">
                    <td><textarea rows="2" data-role="pain"></textarea></td>
                    <td><textarea rows="2" data-role="solution"></textarea></td>
                    <td><button class="btn btn-danger btn-small" onclick="this.closest('tr').remove()"><i class="fas fa-trash"></i></button></td>
                </tr>
            `);
        }

        async function saveOfferEdits() {
            const offerId = Number(document.getElementById('portfolioEditOfferId')?.value || 0);
            const title = (document.getElementById('portfolioEditTitle')?.value || '').trim();
            const summary = (document.getElementById('portfolioEditSummary')?.value || '').trim();
            if (!offerId || !title) return showError('Título da oferta é obrigatório.');

            try {
                const offerRes = await fetch(`${API_BASE}/portfolio/offers/${offerId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title, summary })
                });
                const offerPayload = await offerRes.json().catch(() => ({}));
                if (!offerRes.ok) throw new Error(offerPayload.error || 'Erro ao salvar oferta.');

                const rows = Array.from(document.querySelectorAll('#portfolioEditItemsBody tr'));
                for (const [index, row] of rows.entries()) {
                    const itemId = Number(row.getAttribute('data-item-id') || 0);
                    const pain = (row.querySelector('[data-role="pain"]')?.value || '').trim();
                    const solution = (row.querySelector('[data-role="solution"]')?.value || '').trim();
                    if (!pain && !solution) continue;
                    const payload = { pain, solution, sort_order: index };
                    if (itemId > 0) {
                        await fetch(`${API_BASE}/portfolio/offers/${offerId}/items/${itemId}`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload)
                        });
                    } else {
                        await fetch(`${API_BASE}/portfolio/offers/${offerId}/items`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload)
                        });
                    }
                }

                closePortfolioModal('portfolioEditModal');
                showSuccess('Oferta atualizada com sucesso.');
                await loadPortfolio();
            } catch (error) {
                showError(error.message || 'Erro ao salvar alterações da oferta.');
            }
        }

        async function deleteOffer(offerId) {
            if (!await uiConfirm('Deseja realmente excluir esta oferta?', 'Excluir Oferta')) return;
            try {
                const response = await fetch(`${API_BASE}/portfolio/offers/${offerId}`, { method: 'DELETE' });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.error || 'Erro ao excluir oferta.');
                showSuccess('Oferta excluída com sucesso.');
                await loadPortfolio();
            } catch (error) {
                showError(error.message || 'Erro ao excluir oferta.');
            }
        }

        async function deleteOfferItem(offerId, itemId) {
            if (!await uiConfirm('Deseja excluir este item dor/solução?', 'Excluir Item')) return;
            try {
                const response = await fetch(`${API_BASE}/portfolio/offers/${offerId}/items/${itemId}`, { method: 'DELETE' });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.error || 'Erro ao remover item.');
                const offer = portfolioOffers.find(item => Number(item.id) === Number(offerId));
                if (offer && Array.isArray(offer.items)) {
                    offer.items = offer.items.filter(item => Number(item.id) !== Number(itemId));
                }
                openEditOfferModal(offerId);
                showSuccess('Item removido com sucesso.');
            } catch (error) {
                showError(error.message || 'Erro ao remover item.');
            }
        }

        // ─── iAta ──────────────────────────────────────────────────────────────
        let iataRecords = [];
        const expandedIAtaRecords = new Set();

        async function loadIAta() {
            const container = document.getElementById('iataContent');
            if (!container) return;
            container.innerHTML = '<p style="color:#6b7280;">Carregando histórico de atas...</p>';
            try {
                const response = await fetch(`${API_BASE}/portfolio/iata`);
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
                container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">📋</div><h3 style="color:#e2dfd5;">Nenhuma ata gerada</h3><p style="color:#e2dfd5;">Clique em "+ Nova Ata" para gerar a ata de uma reunião com IA.</p></div>`;
                return;
            }
            container.innerHTML = records.map(record => {
                const rid = Number(record.id);
                const isExpanded = expandedIAtaRecords.has(rid);
                const participants = Array.isArray(record.participants) ? record.participants : [];
                const insights = record.insights || {};
                const insightsList = Array.isArray(insights.insights) ? insights.insights : [];
                const hasUnmatched = insights.has_unmatched;
                const dateStr = record.meeting_date ? ` · ${escapeHtml(record.meeting_date)}` : '';
                const timeStr = record.meeting_time ? ` ${escapeHtml(record.meeting_time)}` : '';
                return `
                    <div class="history-item" style="border:1px solid rgba(16,185,129,.25); border-radius:12px; margin-bottom:10px; background:#fff;">
                        <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:10px;">
                            <div style="flex:1; min-width:0; cursor:pointer;" onclick="toggleIAtaExpand(${rid})">
                                <div style="display:flex; align-items:center; gap:8px; color:#065f46; flex-wrap:wrap;">
                                    <i class="fas fa-file-alt"></i>
                                    <h3 style="margin:0; font-size:15px;">${escapeHtml(record.title || 'Ata sem título')}</h3>
                                    <span style="font-size:12px; color:#6b7280; font-weight:400;">${dateStr}${timeStr}</span>
                                </div>
                                ${participants.length ? `<p style="margin:4px 0 0; color:#6b7280; font-size:12px;">Participantes: ${escapeHtml(participants.join(', '))}</p>` : ''}
                                ${insightsList.length ? `<p style="margin:3px 0 0; font-size:12px; color:${hasUnmatched ? '#b45309' : '#065f46'};">
                                    <i class="fas fa-${hasUnmatched ? 'exclamation-circle' : 'check-circle'}"></i>
                                    ${insightsList.length} insight${insightsList.length > 1 ? 's' : ''} de negócio${hasUnmatched ? ' · Oportunidades sem solução mapeada' : ''}
                                </p>` : ''}
                            </div>
                            <div style="display:flex; gap:6px; flex-shrink:0;">
                                <button class="btn btn-secondary btn-small" onclick="toggleIAtaExpand(${rid})" title="Expandir/Colapsar">${isExpanded ? '▲' : '▼'}</button>
                                <button class="btn btn-secondary btn-small" onclick="viewIAtaFull(${rid})" title="Ver ata completa"><i class="fas fa-eye"></i></button>
                                <button class="btn btn-danger btn-small" onclick="deleteIAtaRecord(${rid})" title="Excluir"><i class="fas fa-trash"></i></button>
                            </div>
                        </div>
                        ${isExpanded ? _renderIAtaExpanded(record) : ''}
                    </div>
                `;
            }).join('');
        }

        function _iataParticipantNames(ata, record) {
            const raw = Array.isArray(ata.participants) ? ata.participants : (Array.isArray(record.participants) ? record.participants : []);
            return raw.map(p => typeof p === 'object' && p !== null ? (p.name || '') : String(p || '')).filter(Boolean);
        }

        function _iataDeadline(s) {
            const d = s.deadline;
            return (!d || d === 'null' || d === 'none') ? null : d;
        }


        function _renderIAtaExpanded(record) {
            const ata = record.ata || {};
            const insights = record.insights || {};
            const insightsList = Array.isArray(insights.insights) ? insights.insights : [];
            const nextSteps = Array.isArray(ata.next_steps) ? ata.next_steps : [];
            const decisions = Array.isArray(ata.decisions) ? ata.decisions : [];

            return `
                <div style="margin-top:12px; padding-top:12px; border-top:1px solid #e5e7eb;">
                    ${record.topic ? `<p style="margin:0 0 8px; font-size:13px;"><strong style="color:#065f46;">Tema:</strong> ${escapeHtml(record.topic)}</p>` : ''}
                    ${ata.summary ? `<p style="margin:0 0 10px; font-size:13px; line-height:1.6; color:#374151;"><strong style="color:#065f46;">Resumo:</strong> ${escapeHtml(ata.summary)}</p>` : ''}
                    ${decisions.length ? `
                        <div style="margin-bottom:8px;">
                            <strong style="color:#065f46; font-size:13px;">Decisões:</strong>
                            <ul style="margin:4px 0 0; padding-left:18px; font-size:12px; color:#374151;">
                                ${decisions.map(d => `<li style="margin-bottom:3px;">${escapeHtml(d)}</li>`).join('')}
                            </ul>
                        </div>` : ''}
                    ${nextSteps.length ? `
                        <div style="margin-bottom:10px;">
                            <strong style="color:#065f46; font-size:13px;">Próximos Passos:</strong>
                            <div style="margin-top:6px; display:flex; flex-direction:column; gap:4px;">
                                ${nextSteps.map(s => {
                                    const dl = _iataDeadline(s);
                                    return `
                                    <div style="display:flex; gap:8px; align-items:flex-start; font-size:12px; padding:4px 8px; background:#f0fdf4; border-radius:6px; border-left:3px solid #10b981;">
                                        <div style="flex:1;"><strong>${escapeHtml(s.responsible || 'A definir')}</strong>: ${escapeHtml(s.action || '')}</div>
                                        ${dl ? `<div style="color:#6b7280; flex-shrink:0;">${escapeHtml(dl)}</div>` : ''}
                                    </div>`;
                                }).join('')}
                            </div>
                        </div>` : ''}
                    ${insightsList.length ? `
                        <div style="padding:10px; background:#fffbeb; border:1px solid #fcd34d; border-radius:8px;">
                            <div style="font-weight:600; color:#92400e; margin-bottom:8px; font-size:13px;"><i class="fas fa-lightbulb"></i> Insights de Negócios</div>
                            ${insightsList.map(ins => `
                                <div style="margin-bottom:5px; padding:6px 8px; background:${ins.matched_offer ? '#f0fdf4' : '#fff7ed'}; border-radius:6px; border-left:3px solid ${ins.matched_offer ? '#10b981' : '#f97316'}; font-size:12px;">
                                    <div style="font-weight:600; color:#1f2937; margin-bottom:2px;">${escapeHtml(ins.pain || '')}</div>
                                    ${ins.matched_offer
                                        ? `<div style="color:#065f46;"><i class="fas fa-check-circle"></i> <strong>${escapeHtml(ins.matched_offer)}</strong>${ins.matched_solution ? ': ' + escapeHtml(ins.matched_solution) : ''}</div>`
                                        : `<div style="color:#c2410c;"><i class="fas fa-info-circle"></i> ${escapeHtml(ins.observation || 'Busque outras soluções na Stefanini para esta demanda.')}</div>`
                                    }
                                </div>
                            `).join('')}
                            ${insights.has_unmatched ? `
                                <div style="margin-top:6px; padding:6px 8px; background:#fff7ed; border-radius:6px; font-size:12px; color:#c2410c; font-weight:500;">
                                    <i class="fas fa-exclamation-circle"></i> Há oportunidades sem solução mapeada no portfólio. Entre em contato com a Stefanini para explorar outras alternativas.
                                </div>` : ''}
                        </div>` : ''}
                </div>
            `;
        }

        function toggleIAtaExpand(rid) {
            const key = Number(rid);
            if (expandedIAtaRecords.has(key)) expandedIAtaRecords.delete(key);
            else expandedIAtaRecords.add(key);
            renderIAtaHistory(iataRecords);
        }

        async function viewIAtaFull(rid) {
            try {
                const response = await fetch(`${API_BASE}/portfolio/iata/${rid}`);
                const record = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(record.error || 'Erro ao carregar ata.');
                _openIAtaViewModal(record);
            } catch (error) {
                showError(error.message || 'Erro ao abrir ata.');
            }
        }

        function _openIAtaViewModal(record) {
            const modalId = 'iataViewModal';
            document.getElementById(modalId)?.remove();
            const ata = record.ata || {};
            const insights = record.insights || {};
            const insightsList = Array.isArray(insights.insights) ? insights.insights : [];
            const participantNames = _iataParticipantNames(ata, record);
            const participantObjs = Array.isArray(ata.participants) ? ata.participants : participantNames.map(n => ({name: n, role: ''}));
            const nextSteps = Array.isArray(ata.next_steps) ? ata.next_steps : [];
            const decisions = Array.isArray(ata.decisions) ? ata.decisions : [];
            const keyPoints = Array.isArray(ata.key_points) ? ata.key_points : [];
            const agenda = Array.isArray(ata.agenda) ? ata.agenda : [];

            const html = `
                <div class="modal active" id="${modalId}" onclick="if(event.target===this) this.remove()">
                    <div class="modal-content" style="max-width:840px; max-height:90vh; overflow-y:auto;">
                        <div class="modal-header" style="background:linear-gradient(135deg,#065f46,#10b981); border-radius:12px 12px 0 0; margin:-20px -20px 20px; padding:20px;">
                            <div style="flex:1;">
                                <h2 class="modal-title" style="color:#fff; margin:0 0 6px;">${escapeHtml(ata.title || record.title || 'Ata de Reunião')}</h2>
                                <div style="display:flex; gap:16px; font-size:13px; color:rgba(255,255,255,.85); flex-wrap:wrap;">
                                    ${ata.meeting_date ? `<span><i class="fas fa-calendar"></i> ${escapeHtml(ata.meeting_date)}</span>` : ''}
                                    ${ata.meeting_time ? `<span><i class="fas fa-clock"></i> ${escapeHtml(ata.meeting_time)}</span>` : ''}
                                    ${ata.location ? `<span><i class="fas fa-map-marker-alt"></i> ${escapeHtml(ata.location)}</span>` : ''}
                                </div>
                            </div>
                            <button class="modal-close" onclick="document.getElementById('${modalId}').remove()" style="color:#fff;">&#215;</button>
                        </div>

                        ${ata.topic ? `
                            <div style="margin-bottom:16px; padding:10px 14px; background:#f0fdf4; border-radius:8px; border-left:4px solid #10b981;">
                                <div style="font-size:11px; text-transform:uppercase; letter-spacing:.5px; color:#6b7280; margin-bottom:4px;">Tema da Reunião</div>
                                <div style="font-weight:600; color:#065f46; font-size:15px;">${escapeHtml(ata.topic)}</div>
                            </div>` : ''}

                        ${participantObjs.length ? `
                            <div style="margin-bottom:16px;">
                                <div style="font-size:11px; text-transform:uppercase; letter-spacing:.5px; color:#6b7280; margin-bottom:8px; font-weight:600;">Participantes</div>
                                <div style="display:flex; gap:6px; flex-wrap:wrap;">
                                    ${participantObjs.map(p => {
                                        const name = typeof p === 'object' ? (p.name || '') : String(p || '');
                                        const role = typeof p === 'object' ? (p.role || '') : '';
                                        return `<span style="padding:4px 12px; background:#e0f2fe; color:#0369a1; border-radius:20px; font-size:12px; font-weight:500;" title="${escapeHtml(role)}">${escapeHtml(name)}${role ? ' <span style="opacity:.7;font-weight:400;">· ' + escapeHtml(role) + '</span>' : ''}</span>`;
                                    }).join('')}
                                </div>
                            </div>` : ''}

                        ${ata.objective ? `
                            <div style="margin-bottom:16px; padding:12px 14px; background:#f0fdf4; border-radius:8px;">
                                <div style="font-size:11px; text-transform:uppercase; letter-spacing:.5px; color:#6b7280; margin-bottom:6px; font-weight:600;">Objetivo</div>
                                <p style="margin:0; color:#374151; line-height:1.6; font-size:14px;">${escapeHtml(ata.objective)}</p>
                            </div>` : ''}

                        ${ata.summary ? `
                            <div style="margin-bottom:16px; padding:12px 14px; background:#f8fafc; border-radius:8px;">
                                <div style="font-size:11px; text-transform:uppercase; letter-spacing:.5px; color:#6b7280; margin-bottom:6px; font-weight:600;">Resumo Executivo</div>
                                <p style="margin:0; color:#374151; line-height:1.7; font-size:14px;">${escapeHtml(ata.summary)}</p>
                            </div>` : ''}

                        ${agenda.length ? `
                            <div style="margin-bottom:16px;">
                                <div style="font-size:11px; text-transform:uppercase; letter-spacing:.5px; color:#6b7280; margin-bottom:8px; font-weight:600;">Pauta</div>
                                <ol style="margin:0; padding-left:20px; color:#374151; font-size:14px; line-height:2;">
                                    ${agenda.map(a => `<li>${escapeHtml(a)}</li>`).join('')}
                                </ol>
                            </div>` : ''}

                        ${keyPoints.length ? `
                            <div style="margin-bottom:16px;">
                                <div style="font-size:11px; text-transform:uppercase; letter-spacing:.5px; color:#6b7280; margin-bottom:10px; font-weight:600;">Desenvolvimento / Pontos Discutidos</div>
                                <div style="display:flex; flex-direction:column; gap:8px;">
                                    ${keyPoints.map((k, i) => `
                                        <div style="padding:10px 14px; background:#f8fafc; border-radius:8px; border-left:3px solid #10b981;">
                                            <div style="font-size:11px; color:#6b7280; margin-bottom:4px; font-weight:600;">Ponto ${i+1}</div>
                                            <p style="margin:0; color:#374151; line-height:1.7; font-size:14px;">${escapeHtml(k)}</p>
                                        </div>
                                    `).join('')}
                                </div>
                            </div>` : ''}

                        ${decisions.length ? `
                            <div style="margin-bottom:16px;">
                                <div style="font-size:11px; text-transform:uppercase; letter-spacing:.5px; color:#6b7280; margin-bottom:8px; font-weight:600;">Decisões Tomadas</div>
                                ${decisions.map(d => `
                                    <div style="display:flex; gap:8px; align-items:flex-start; padding:8px 12px; background:#f0fdf4; border-radius:6px; border-left:3px solid #10b981; margin-bottom:5px; font-size:13px; color:#374151; line-height:1.5;">
                                        <i class="fas fa-check" style="color:#10b981; margin-top:3px; flex-shrink:0;"></i>
                                        <span>${escapeHtml(d)}</span>
                                    </div>
                                `).join('')}
                            </div>` : ''}

                        ${nextSteps.length ? `
                            <div style="margin-bottom:16px;">
                                <div style="font-size:11px; text-transform:uppercase; letter-spacing:.5px; color:#6b7280; margin-bottom:8px; font-weight:600;">Próximos Passos &amp; Pendências</div>
                                <div class="table-container">
                                    <table>
                                        <thead><tr><th>Ação</th><th>Responsável</th><th>Prazo</th><th>Status</th></tr></thead>
                                        <tbody>
                                            ${nextSteps.map(s => {
                                                const dl = _iataDeadline(s);
                                                return `
                                                <tr>
                                                    <td style="line-height:1.5;">${escapeHtml(s.action || '')}</td>
                                                    <td><strong>${escapeHtml(s.responsible || 'A definir')}</strong></td>
                                                    <td>${escapeHtml(dl || '—')}</td>
                                                    <td><span style="padding:2px 8px; border-radius:12px; font-size:11px; font-weight:600; background:${s.status === 'concluído' ? '#d1fae5' : '#fef3c7'}; color:${s.status === 'concluído' ? '#065f46' : '#92400e'};">${escapeHtml(s.status || 'pendente')}</span></td>
                                                </tr>`;
                                            }).join('')}
                                        </tbody>
                                    </table>
                                </div>
                            </div>` : ''}

                        ${ata.observations ? `
                            <div style="margin-bottom:16px; padding:12px 14px; background:#fffbeb; border-radius:8px; border-left:4px solid #f59e0b;">
                                <div style="font-size:11px; text-transform:uppercase; letter-spacing:.5px; color:#6b7280; margin-bottom:6px; font-weight:600;">Observações</div>
                                <p style="margin:0; color:#374151; line-height:1.6; font-size:14px;">${escapeHtml(ata.observations)}</p>
                            </div>` : ''}


                        ${insightsList.length ? `
                            <div style="padding:14px; background:#fffbeb; border:1px solid #fcd34d; border-radius:10px;">
                                <div style="font-weight:700; color:#92400e; margin-bottom:12px; font-size:14px;">
                                    <i class="fas fa-lightbulb"></i> Insights de Negócios
                                </div>
                                ${insightsList.map(ins => `
                                    <div style="margin-bottom:8px; padding:10px 12px; background:${ins.matched_offer ? '#f0fdf4' : '#fff7ed'}; border-radius:8px; border-left:4px solid ${ins.matched_offer ? '#10b981' : '#f97316'};">
                                        <div style="font-weight:600; color:#1f2937; margin-bottom:4px; font-size:13px;">${escapeHtml(ins.pain || '')}</div>
                                        ${ins.matched_offer
                                            ? `<div style="font-size:12px; color:#065f46; display:flex; align-items:flex-start; gap:6px;">
                                                <i class="fas fa-check-circle" style="margin-top:2px; flex-shrink:0;"></i>
                                                <div><strong>${escapeHtml(ins.matched_offer)}</strong>${ins.matched_solution ? ' — ' + escapeHtml(ins.matched_solution) : ''}</div>
                                               </div>`
                                            : `<div style="font-size:12px; color:#c2410c; display:flex; align-items:flex-start; gap:6px;">
                                                <i class="fas fa-info-circle" style="margin-top:2px; flex-shrink:0;"></i>
                                                <div>${escapeHtml(ins.observation || 'Busque outras soluções na Stefanini para esta demanda.')}</div>
                                               </div>`
                                        }
                                        ${ins.confidence ? `<div style="font-size:11px; color:#9ca3af; margin-top:3px;">Relevância: ${escapeHtml(ins.confidence)}</div>` : ''}
                                    </div>
                                `).join('')}
                                ${insights.has_unmatched ? `
                                    <div style="margin-top:8px; padding:10px 12px; background:#fff7ed; border-radius:8px; border-left:4px solid #f97316; font-size:13px;">
                                        <div style="display:flex; gap:8px; align-items:flex-start; color:#c2410c; font-weight:500;">
                                            <i class="fas fa-exclamation-circle" style="margin-top:2px;"></i>
                                            <div>Há oportunidades identificadas que não possuem solução mapeada no portfólio atual. Entre em contato com a equipe da <strong>Stefanini</strong> para explorar outras alternativas.</div>
                                        </div>
                                    </div>` : ''}
                            </div>` : ''}

                        <div style="display:flex; justify-content:space-between; margin-top:20px; gap:8px; flex-wrap:wrap;">
                            <button id="iataCopyBtn_${record.id}" class="btn btn-secondary btn-small" onclick="_copyIAtaToClipboard(${record.id})">
                                <i class="fas fa-copy"></i> Copiar Ata
                            </button>
                            <button class="btn btn-secondary" onclick="document.getElementById('${modalId}').remove()">Fechar</button>
                        </div>
                    </div>
                </div>
            `;
            document.body.insertAdjacentHTML('beforeend', html);
        }

        async function _copyIAtaToClipboard(rid) {
            const btn = document.getElementById(`iataCopyBtn_${rid}`);
            let record = iataRecords.find(r => r.id === rid) || null;
            if (!record) {
                try {
                    const resp = await fetch(`/api/portfolio/iata/${rid}`);
                    record = await resp.json();
                } catch(e) { showError('Erro ao copiar ata.'); return; }
            }
            const ata = record.ata || {};
            const lines = [];
            lines.push(`ATA DE REUNIÃO`);
            lines.push(`=`.repeat(50));
            if (ata.title) lines.push(`Título: ${ata.title}`);
            const parts = [ata.meeting_date, ata.meeting_time, ata.location].filter(Boolean);
            if (parts.length) lines.push(`Data/Hora/Local: ${parts.join(' | ')}`);
            if (ata.topic) lines.push(`Assunto: ${ata.topic}`);
            lines.push('');
            const participantNames = _iataParticipantNames(ata, record);
            if (participantNames.length) {
                lines.push(`PARTICIPANTES`);
                lines.push(`-`.repeat(30));
                participantNames.forEach(p => lines.push(`• ${p}`));
                lines.push('');
            }
            if (ata.objective) {
                lines.push(`OBJETIVO`);
                lines.push(`-`.repeat(30));
                lines.push(ata.objective);
                lines.push('');
            }
            if (ata.summary) {
                lines.push(`RESUMO`);
                lines.push(`-`.repeat(30));
                lines.push(ata.summary);
                lines.push('');
            }
            if ((ata.agenda || []).length) {
                lines.push(`PAUTA`);
                lines.push(`-`.repeat(30));
                (ata.agenda || []).forEach((item, i) => lines.push(`${i+1}. ${item}`));
                lines.push('');
            }
            if ((ata.key_points || []).length) {
                lines.push(`PONTOS DISCUTIDOS`);
                lines.push(`-`.repeat(30));
                (ata.key_points || []).forEach((kp, i) => {
                    const title = typeof kp === 'object' ? (kp.title || '') : '';
                    const detail = typeof kp === 'object' ? (kp.detail || '') : String(kp);
                    lines.push(`${i+1}. ${title}`);
                    if (detail) lines.push(`   ${detail}`);
                });
                lines.push('');
            }
            if ((ata.decisions || []).length) {
                lines.push(`DECISÕES`);
                lines.push(`-`.repeat(30));
                (ata.decisions || []).forEach((d, i) => lines.push(`${i+1}. ${d}`));
                lines.push('');
            }
            if ((ata.next_steps || []).length) {
                lines.push(`PRÓXIMOS PASSOS`);
                lines.push(`-`.repeat(30));
                (ata.next_steps || []).forEach((ns, i) => {
                    const action = typeof ns === 'object' ? (ns.action || ns.task || '') : String(ns);
                    const resp = typeof ns === 'object' ? (ns.responsible || '') : '';
                    const dl = typeof ns === 'object' ? _iataDeadline(ns.deadline) : null;
                    let line = `${i+1}. ${action}`;
                    if (resp) line += ` [${resp}]`;
                    if (dl) line += ` — Prazo: ${dl}`;
                    lines.push(line);
                });
                lines.push('');
            }
            if (ata.observations) {
                lines.push(`OBSERVAÇÕES`);
                lines.push(`-`.repeat(30));
                lines.push(ata.observations);
                lines.push('');
            }
            const text = lines.join('\n');
            try {
                await navigator.clipboard.writeText(text);
                if (btn) { btn.innerHTML = '<i class="fas fa-check"></i> Copiado!'; btn.disabled = true; setTimeout(() => { btn.innerHTML = '<i class="fas fa-copy"></i> Copiar Ata'; btn.disabled = false; }, 2500); }
            } catch(e) {
                showError('Não foi possível copiar. Verifique permissões do navegador.');
            }
        }

        function openIAtaModal() {
            const modalId = 'iataNewModal';
            document.getElementById(modalId)?.remove();
            if (!document.getElementById('iata-bunny-style')) {
                const style = document.createElement('style');
                style.id = 'iata-bunny-style';
                style.textContent = `
                    @keyframes iata-paw-fade { 0%,100%{opacity:.25} 50%{opacity:.7} }
                    .iata-paw { display:inline-block; font-size:10px; animation:iata-paw-fade 1s ease-in-out infinite; }
                    .iata-paw:nth-child(2){animation-delay:.2s} .iata-paw:nth-child(3){animation-delay:.4s}
                `;
                document.head.appendChild(style);
            }
            const html = `
                <div class="modal active" id="${modalId}" onclick="if(event.target===this&&!document.getElementById('iataProgressArea').offsetParent) this.remove()">
                    <div class="modal-content" style="max-width:680px;">
                        <div class="modal-header">
                            <h2 class="modal-title"><i class="fas fa-file-alt"></i> Nova Ata — iAta</h2>
                            <button class="modal-close" id="iataModalCloseBtn" onclick="document.getElementById('${modalId}').remove()">&#215;</button>
                        </div>
                        <div id="iataFormArea">
                            <p style="margin:0 0 16px; color:#6b7280; font-size:13px;">
                                Envie um arquivo de reunião ou cole o texto. A IA gera a ata completa e identifica insights de negócio cruzando com as Soluções STF.
                            </p>
                            <div class="form-group">
                                <label>Arquivo da reunião</label>
                                <input id="iataFileInput" type="file" accept=".pdf,.doc,.docx,.txt,.vtt,.srt,.csv,text/plain,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document">
                                <small style="color:#9ca3af; font-size:11px; display:block; margin-top:4px;">Suportado: PDF, DOCX, TXT, VTT (Teams), SRT e outros formatos de texto</small>
                            </div>
                            <div class="form-group">
                                <label>OU cole o texto da reunião</label>
                                <textarea id="iataRawTextInput" rows="7" placeholder="Cole aqui a transcrição, notas ou chat da reunião..."></textarea>
                            </div>
                        </div>
                        <div id="iataProgressArea" style="display:none; padding:20px 4px 12px;">
                            <div style="font-size:13px; color:#6b7280; margin-bottom:12px; text-align:center;" id="iataProgressStep">Iniciando...</div>
                            <div style="position:relative; background:#d1fae5; border-radius:99px; height:12px; overflow:visible; margin:0 16px 6px;">
                                <div id="iataProgressBar" style="position:relative; height:100%; width:5%; background:linear-gradient(90deg,#059669,#10b981,#34d399); border-radius:99px; transition:width .6s ease;">
                                    <img src="/images/coelho-correndo.webp" class="coelho-run" alt="">
                                </div>
                            </div>
                            <div style="display:flex; justify-content:space-between; align-items:center; padding:0 16px;">
                                <div style="font-size:12px; color:#10b981;">
                                    <span class="iata-paw">🐾</span><span class="iata-paw">🐾</span><span class="iata-paw">🐾</span>
                                </div>
                                <div style="font-size:11px; color:#6b7280;" id="iataProgressPct">5%</div>
                            </div>
                        </div>
                        <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:8px;">
                            <button id="iataCancelBtn" class="btn btn-secondary" onclick="document.getElementById('${modalId}').remove()">Cancelar</button>
                            <button id="iataSubmitBtn" class="btn btn-auto-mapping btn-small" onclick="submitIAta()">
                                <span class="ai-star-icon">✦</span> Gerar Ata com IA
                            </button>
                        </div>
                    </div>
                </div>
            `;
            document.body.insertAdjacentHTML('beforeend', html);
        }

        function _iataSetProgress(pct, step) {
            const bar = document.getElementById('iataProgressBar');
            const stepEl = document.getElementById('iataProgressStep');
            const pctEl = document.getElementById('iataProgressPct');
            if (bar) bar.style.width = Math.max(5, pct) + '%';
            if (stepEl) stepEl.textContent = step || '';
            if (pctEl) pctEl.textContent = Math.round(pct) + '%';
        }


        async function submitIAta() {
            const fileInput = document.getElementById('iataFileInput');
            const file = fileInput?.files?.[0] || null;
            const rawText = (document.getElementById('iataRawTextInput')?.value || '').trim();
            if (!file && !rawText) {
                showError('Envie um arquivo ou cole o texto da reunião.');
                return;
            }
            const btn = document.getElementById('iataSubmitBtn');
            const cancelBtn = document.getElementById('iataCancelBtn');
            const closeBtn = document.getElementById('iataModalCloseBtn');
            const formArea = document.getElementById('iataFormArea');
            const progressArea = document.getElementById('iataProgressArea');

            if (btn) { btn.disabled = true; btn.style.display = 'none'; }
            if (cancelBtn) cancelBtn.style.display = 'none';
            if (closeBtn) closeBtn.style.display = 'none';
            if (formArea) formArea.style.display = 'none';
            if (progressArea) progressArea.style.display = 'block';
            _iataSetProgress(5, 'Enviando arquivo...');

            try {
                const fd = new FormData();
                if (file) fd.append('meeting_file', file);
                if (rawText) fd.append('raw_text', rawText);
                const response = await fetch(`${API_BASE}/portfolio/iata`, { method: 'POST', body: fd });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.error || 'Erro ao iniciar processamento.');
                const taskId = payload.task_id;
                if (!taskId) throw new Error('Resposta inesperada do servidor.');
                _iataSetProgress(10, 'Aguardando processamento...');

                // Permite fechar o modal e continuar em background
                if (closeBtn) { closeBtn.style.display = ''; }
                document.getElementById('iataModalCloseBtn')?.removeAttribute('onclick');
                document.getElementById('iataModalCloseBtn')?.addEventListener('click', () => {
                    document.getElementById('iataNewModal')?.remove();
                }, { once: true });

                // Botões Cancelar / Minimizar no topo da barra de progresso
                const _iataProgressEl = document.getElementById('iataProgressArea');
                _attachBgTaskControls(
                    _iataProgressEl, taskId,
                    () => document.getElementById('iataNewModal')?.remove(),
                    () => { document.getElementById('iataNewModal')?.remove(); showError('Tarefa cancelada.'); }
                );

                const sourceTab = typeof _currentTab !== 'undefined' ? _currentTab : 'iata';
                BgTaskManager.register(
                    taskId,
                    `${API_BASE}/portfolio/iata/tasks/${taskId}`,
                    'Gerando Ata com IA',
                    sourceTab,
                    (record) => {
                        document.getElementById('iataNewModal')?.remove();
                        showSuccess('Ata gerada com sucesso!');
                        loadIAta().then(() => {
                            if (record && record.id) {
                                expandedIAtaRecords.add(Number(record.id));
                                renderIAtaHistory(iataRecords);
                            }
                        });
                    },
                    (errMsg) => {
                        showError(errMsg || 'Erro ao processar reunião com IA.');
                        if (btn) { btn.disabled = false; btn.style.display = ''; }
                        if (cancelBtn) cancelBtn.style.display = '';
                        if (formArea) formArea.style.display = '';
                        if (progressArea) progressArea.style.display = 'none';
                    },
                    (pct, step) => _iataSetProgress(pct, step)
                );
            } catch (error) {
                showError(error.message || 'Erro ao processar reunião com IA.');
                if (btn) { btn.disabled = false; btn.style.display = ''; }
                if (cancelBtn) cancelBtn.style.display = '';
                if (closeBtn) closeBtn.style.display = '';
                if (formArea) formArea.style.display = '';
                if (progressArea) progressArea.style.display = 'none';
            }
        }

        async function deleteIAtaRecord(rid) {
            if (!await uiConfirm('Deseja realmente excluir esta ata?', 'Excluir Ata')) return;
            try {
                const response = await fetch(`${API_BASE}/portfolio/iata/${rid}`, { method: 'DELETE' });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.error || 'Erro ao excluir ata.');
                showSuccess('Ata excluída com sucesso.');
                expandedIAtaRecords.delete(Number(rid));
                await loadIAta();
            } catch (error) {
                showError(error.message || 'Erro ao excluir ata.');
            }
        }

        async function loadWikiTocaData() {
            const query = (document.getElementById('wikiSearchInput')?.value || '').trim();
            const params = query ? `?q=${encodeURIComponent(query)}` : '';
            const results = await Promise.allSettled([loadWikiEntries(params), loadWikiDocuments(params)]);
            const failed = results.some(result => result.status === 'rejected');
            if (failed) {
                showError('Não foi possível atualizar todos os dados do WikiToca. Tente novamente.');
            }
        }

        function getWikiApiErrorDetails(err, fallbackMessage) {
            const message = err?.error || fallbackMessage;
            const code = err?.error_code ? `Código: ${err.error_code}` : '';
            const details = err?.details ? `Detalhes técnicos: ${err.details}` : '';
            const hint = err?.hint ? `Como corrigir: ${err.hint}` : '';
            return [message, code, details, hint].filter(Boolean);
        }

        function renderWikiErrorBlock(lines) {
            return `<div style="background:#fef2f2; border:1px solid #fecaca; color:#991b1b; border-radius:10px; padding:10px;">${lines.map(line => `<div>${escapeHtml(line)}</div>`).join('')}</div>`;
        }

        async function loadWikiEntries(params = '') {
            const el = document.getElementById('wikiEntriesList');
            if (!el) return;
            let response;
            try {
                response = await fetch(`${API_BASE}/wikitoca/entries${params}`);
            } catch (error) {
                wikiEntries = [];
                const lines = [
                    'Falha de conexão ao carregar conhecimentos do WikiToca.',
                    `Detalhes técnicos: ${error.message}`,
                    'Como corrigir: verifique se o backend está ativo e acessível em /api/wikitoca/entries.'
                ];
                el.innerHTML = renderWikiErrorBlock(lines);
                showError(lines.join(' | '));
                return;
            }
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                wikiEntries = [];
                const lines = getWikiApiErrorDetails(err, 'Não foi possível carregar os conhecimentos do WikiToca.');
                el.innerHTML = renderWikiErrorBlock(lines);
                showError(lines.join(' | '));
                return;
            }
            wikiEntries = await response.json();
            updateWikiSortButtonLabel();
            wikiEntries = [...wikiEntries].sort((a, b) => {
                const at = (a.title || "").toLowerCase();
                const bt = (b.title || "").toLowerCase();
                if (wikiEntriesSortOrder === "za") return bt.localeCompare(at, "pt-BR");
                return at.localeCompare(bt, "pt-BR");
            });
            if (!wikiEntries.length) {
                el.innerHTML = '<p style="color:#6b7280;">Nenhum conhecimento registrado ainda.</p>';
                return;
            }
            el.innerHTML = wikiEntries.map(item => `
                <div class="wiki-entry-item" onclick="toggleWikiEntry(event, ${item.id})" data-entry-id="${item.id}">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                        <h4 style="margin:0; flex:1;">${escapeHtml(item.title || '')}</h4>
                        <i class="fas fa-chevron-down" style="color:#9ca3af; font-size:11px; margin-left:8px; margin-top:3px; transition:transform 0.2s;" id="wiki-chevron-${item.id}"></i>
                    </div>
                    <div class="wiki-meta" style="margin-top:4px;">${escapeHtml(item.category || 'Sem categoria')} • Atualizado em ${formatDateBr(item.updated_at)}${item.tags ? ` • Tags: ${escapeHtml(item.tags)}` : ''}</div>
                    <div class="wiki-entry-body" id="wiki-body-${item.id}">${escapeHtml(item.content || '')}</div>
                    <div class="wiki-entry-actions" id="wiki-actions-${item.id}">
                        <button class="btn-wiki-edit" onclick="event.stopPropagation(); openWikiEntryModal(${item.id})"><i class="fas fa-edit"></i> Editar</button>
                        <button class="btn btn-danger btn-small" onclick="event.stopPropagation(); deleteWikiEntry(${item.id})"><i class="fas fa-trash"></i> Excluir</button>
                    </div>
                </div>
            `).join('');
        }

        async function loadWikiDocuments(params = '') {
            const el = document.getElementById('wikiDocumentsList');
            if (!el) return;
            let response = await fetch(`${API_BASE}/wikitoca/documents${params}`);
            if (!response.ok) {
                await new Promise(resolve => setTimeout(resolve, 250));
                response = await fetch(`${API_BASE}/wikitoca/documents${params}`);
            }
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                wikiDocuments = [];
                el.innerHTML = '<p style="color:#ef4444;">Erro ao carregar documentos.</p>';
                showError(err.error || 'Não foi possível carregar os documentos do WikiToca.');
                return;
            }
            wikiDocuments = await response.json();
            if (!wikiDocuments.length) {
                el.innerHTML = '<p style="color:#6b7280;">Nenhum documento cadastrado ainda.</p>';
                return;
            }
            el.innerHTML = wikiDocuments.map(doc => `
                <div class="wiki-doc-item">
                    <h4>${escapeHtml(doc.title || doc.original_name || 'Documento')}</h4>
                    <div class="wiki-meta">${formatFileSize(doc.file_size)} • ${formatDateBr(doc.updated_at)}</div>
                    <div style="display:flex; gap:8px;">
                        <a class="btn btn-primary btn-small" href="${doc.file_url}" target="_blank"><i class="fas fa-eye"></i> Visualizar</a>
                        <a class="btn btn-primary btn-small" href="${doc.file_url}" download="${escapeHtml(doc.original_name || '')}"><i class="fas fa-download"></i> Baixar</a>
                        <button class="btn btn-danger btn-small" onclick="deleteWikiDocument(${doc.id})"><i class="fas fa-trash"></i></button>
                    </div>
                </div>
            `).join('');
        }

        function openWikiEntryModal(entryId = null) {
            const modal = document.getElementById('wikiEntryModal');
            if (!modal) return;
            const entry = wikiEntries.find(item => Number(item.id) === Number(entryId));
            document.getElementById('wikiEntryModalTitle').textContent = entry ? 'Editar conhecimento' : 'Novo conhecimento';
            document.getElementById('wikiEntryId').value = entry ? entry.id : '';
            document.getElementById('wikiEntryTitle').value = entry?.title || '';
            document.getElementById('wikiEntryCategory').value = entry?.category || '';
            document.getElementById('wikiEntryTags').value = entry?.tags || '';
            document.getElementById('wikiEntryContent').value = entry?.content || '';
            modal.classList.add('active');
        }

        function closeWikiEntryModal() {
            const modal = document.getElementById('wikiEntryModal');
            if (modal) modal.classList.remove('active');
        }

        async function saveWikiEntry(event) {
            event.preventDefault();
            const id = document.getElementById('wikiEntryId').value;
            const payload = {
                title: document.getElementById('wikiEntryTitle').value.trim(),
                category: document.getElementById('wikiEntryCategory').value.trim(),
                tags: document.getElementById('wikiEntryTags').value.trim(),
                content: document.getElementById('wikiEntryContent').value.trim()
            };
            const url = id ? `${API_BASE}/wikitoca/entries/${id}` : `${API_BASE}/wikitoca/entries`;
            const method = id ? 'PUT' : 'POST';
            let response;
            try {
                response = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            } catch (error) {
                return showError(`Falha de conexão ao salvar conhecimento. Detalhes técnicos: ${error.message}`);
            }
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                const lines = getWikiApiErrorDetails(err, 'Não foi possível salvar o conhecimento.');
                return showError(lines.join(' | '));
            }
            document.getElementById('wikiSearchInput').value = '';
            closeWikiEntryModal();
            showSuccess('Conhecimento salvo com sucesso!');
            await loadWikiTocaData();
        }

        function toggleWikiEntry(event, entryId) {
            const body = document.getElementById(`wiki-body-${entryId}`);
            const actions = document.getElementById(`wiki-actions-${entryId}`);
            const chevron = document.getElementById(`wiki-chevron-${entryId}`);
            if (!body) return;
            const isOpen = body.classList.contains('open');
            body.classList.toggle('open', !isOpen);
            actions.classList.toggle('open', !isOpen);
            if (chevron) chevron.style.transform = isOpen ? '' : 'rotate(180deg)';
        }

        async function deleteWikiEntry(entryId) {
            const confirmed = await uiConfirm('Deseja remover este conhecimento? Esta ação não pode ser desfeita.', 'Excluir conhecimento');
            if (!confirmed) return;
            const response = await fetch(`${API_BASE}/wikitoca/entries/${entryId}`, { method: 'DELETE' });
            if (!response.ok) return showError('Não foi possível excluir o conhecimento.');
            showSuccess('Conhecimento excluído.');
            await loadWikiTocaData();
        }

        async function uploadWikiDocument() {
            const fileInput = document.getElementById('wikiDocumentFile');
            const files = Array.from(fileInput?.files || []);
            if (!files.length) return showError('Selecione ao menos um arquivo para upload.');
            const formData = new FormData();
            files.forEach((file) => formData.append('files', file));
            formData.append('title', '');
            const response = await fetch(`${API_BASE}/wikitoca/documents`, { method: 'POST', body: formData });
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                return showError(err.error || 'Falha ao enviar documento(s).');
            }
            if (fileInput) fileInput.value = '';
            const fileName = document.getElementById('wikiFileName');
            if (fileName) fileName.textContent = '';
            document.getElementById('wikiUploadBtn')?.classList.remove('wiki-upload-btn-pending');
            document.getElementById('wikiFileClearBtn')?.style && (document.getElementById('wikiFileClearBtn').style.display = 'none');
            document.getElementById('wikiSearchInput').value = '';
            showSuccess(files.length > 1 ? 'Documentos enviados com sucesso!' : 'Documento enviado com sucesso!');
            await loadWikiTocaData();
        }

        async function deleteWikiDocument(documentId) {
            const confirmed = await uiConfirm('Deseja remover este documento? Esta ação não pode ser desfeita.', 'Excluir documento');
            if (!confirmed) return;
            const response = await fetch(`${API_BASE}/wikitoca/documents/${documentId}`, { method: 'DELETE' });
            if (!response.ok) return showError('Não foi possível remover o documento.');
            showSuccess('Documento removido.');
            await loadWikiTocaData();
        }

        function onWikiFileSelected(event) {
            const fileName = document.getElementById('wikiFileName');
            const uploadBtn = document.getElementById('wikiUploadBtn');
            const clearBtn = document.getElementById('wikiFileClearBtn');
            const files = Array.from(event?.target?.files || []);
            if (!fileName) return;
            if (!files.length) {
                fileName.textContent = '';
                uploadBtn?.classList.remove('wiki-upload-btn-pending');
                if (clearBtn) clearBtn.style.display = 'none';
            } else if (files.length === 1) {
                fileName.textContent = files[0].name;
                uploadBtn?.classList.add('wiki-upload-btn-pending');
                if (clearBtn) clearBtn.style.display = '';
            } else {
                fileName.textContent = `${files.length} arquivos selecionados`;
                uploadBtn?.classList.add('wiki-upload-btn-pending');
                if (clearBtn) clearBtn.style.display = '';
            }
        }

        function clearWikiFileSelection() {
            const fileInput = document.getElementById('wikiDocumentFile');
            if (fileInput) fileInput.value = '';
            const fileName = document.getElementById('wikiFileName');
            if (fileName) fileName.textContent = '';
            const clearBtn = document.getElementById('wikiFileClearBtn');
            if (clearBtn) clearBtn.style.display = 'none';
            document.getElementById('wikiUploadBtn')?.classList.remove('wiki-upload-btn-pending');
        }

        function suggestTagsFromKnowledge(title, content) {
            const stopwords = new Set(['a','o','os','as','de','da','do','das','dos','e','é','em','no','na','nos','nas','um','uma','uns','umas','para','por','com','sem','que','se','ao','aos','à','às','ou','como','mais','menos','ja','não','sim']);
            const words = `${title || ''} ${content || ''}`.toLowerCase().match(/[a-zà-ÿ0-9-]{3,}/g) || [];
            const rank = {};
            words.forEach((word) => {
                if (stopwords.has(word) || /^\d+$/.test(word)) return;
                rank[word] = (rank[word] || 0) + 1;
            });
            return Object.entries(rank)
                .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
                .slice(0, 6)
                .map(([word]) => word);
        }

        function autoFillWikiTags() {
            const title = document.getElementById('wikiEntryTitle')?.value || '';
            const content = document.getElementById('wikiEntryContent')?.value || '';
            const tagsInput = document.getElementById('wikiEntryTags');
            if (!tagsInput) return;
            const current = (tagsInput.value || '').split(',').map(tag => tag.trim()).filter(Boolean);
            const suggested = suggestTagsFromKnowledge(title, content);
            const merged = [...new Set([...current, ...suggested])].slice(0, 10);
            tagsInput.value = merged.join(', ');
        }

        function updateWikiSortButtonLabel() {
            const sortBtn = document.getElementById('wikiSortToggleBtn');
            if (!sortBtn) return;
            sortBtn.textContent = wikiEntriesSortOrder === 'za' ? 'Z-A' : 'A-Z';
        }

        function toggleWikiEntriesSort() {
            wikiEntriesSortOrder = wikiEntriesSortOrder === 'az' ? 'za' : 'az';
            updateWikiSortButtonLabel();
            loadWikiEntries();
        }

        function clearWikiSearch() {
            const input = document.getElementById('wikiSearchInput');
            if (input) input.value = '';
            loadWikiTocaData();
        }

        function exportWikiEntries() {
            if (!wikiEntries || !wikiEntries.length) return showError('Nenhum conhecimento para exportar.');
            window.location.href = `${API_BASE}/wikitoca/entries/export-xlsx`;
        }

        function openWikiImportModal() {
            const modal = document.getElementById('wikiImportModal');
            if (!modal) return;
            const fileInput = document.getElementById('wikiXlsxInput');
            const fileLabel = document.getElementById('wikiXlsxFileName');
            const progress = document.getElementById('wikiImportProgress');
            const btn = document.getElementById('wikiImportConfirmBtn');
            if (fileInput) fileInput.value = '';
            if (fileLabel) fileLabel.textContent = 'Nenhum arquivo selecionado';
            if (progress) { progress.style.display = 'none'; progress.textContent = ''; }
            if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
            modal.classList.add('active');
        }

        function closeWikiImportModal() {
            const modal = document.getElementById('wikiImportModal');
            if (modal) modal.classList.remove('active');
        }

        function onWikiXlsxSelected(event) {
            const file = event.target.files?.[0];
            const label = document.getElementById('wikiXlsxFileName');
            const btn = document.getElementById('wikiImportConfirmBtn');
            if (file) {
                if (label) label.textContent = file.name;
                if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
            } else {
                if (label) label.textContent = 'Nenhum arquivo selecionado';
                if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
            }
        }

        async function confirmWikiXlsxImport() {
            const fileInput = document.getElementById('wikiXlsxInput');
            const file = fileInput?.files?.[0];
            if (!file) return showError('Selecione um arquivo .xlsx para importar.');
            const progress = document.getElementById('wikiImportProgress');
            const btn = document.getElementById('wikiImportConfirmBtn');
            if (progress) { progress.style.display = 'block'; progress.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Importando...'; }
            if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
            const formData = new FormData();
            formData.append('file', file);
            try {
                const res = await fetch(`${API_BASE}/wikitoca/entries/import-xlsx`, { method: 'POST', body: formData });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    if (progress) progress.innerHTML = `<span style="color:#ef4444;"><i class="fas fa-times-circle"></i> Erro: ${data.error || 'Falha na importação'}</span>`;
                    if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
                    return;
                }
                const msg = `${data.imported} conhecimento(s) importado(s) com sucesso${data.failed ? `, ${data.failed} com erro` : ''}.`;
                if (progress) progress.innerHTML = `<span style="color:#065f46;"><i class="fas fa-check-circle"></i> ${msg}</span>`;
                showSuccess(msg);
                await loadWikiTocaData();
                setTimeout(() => closeWikiImportModal(), 1800);
            } catch (err) {
                if (progress) progress.innerHTML = `<span style="color:#ef4444;"><i class="fas fa-times-circle"></i> Erro de conexão: ${err.message}</span>`;
                if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
            }
        }

        function exportWikiDocuments() {
            if (!wikiDocuments || !wikiDocuments.length) return showError('Nenhum documento para exportar.');
            window.location.href = `${API_BASE}/wikitoca/documents/export-zip`;
        }

        function openWikiDocImportModal() {
            const modal = document.getElementById('wikiDocImportModal');
            if (!modal) return;
            const fileInput = document.getElementById('wikiDocZipInput');
            const fileLabel = document.getElementById('wikiDocZipFileName');
            const progress = document.getElementById('wikiDocImportProgress');
            const btn = document.getElementById('wikiDocImportConfirmBtn');
            if (fileInput) fileInput.value = '';
            if (fileLabel) fileLabel.textContent = 'Nenhum arquivo selecionado';
            if (progress) { progress.style.display = 'none'; progress.textContent = ''; }
            if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
            modal.classList.add('active');
        }

        function closeWikiDocImportModal() {
            const modal = document.getElementById('wikiDocImportModal');
            if (modal) modal.classList.remove('active');
        }

        function onWikiDocZipSelected(event) {
            const file = event.target.files?.[0];
            const label = document.getElementById('wikiDocZipFileName');
            const btn = document.getElementById('wikiDocImportConfirmBtn');
            if (file) {
                if (label) label.textContent = file.name;
                if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
            } else {
                if (label) label.textContent = 'Nenhum arquivo selecionado';
                if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
            }
        }

        async function confirmWikiDocZipImport() {
            const fileInput = document.getElementById('wikiDocZipInput');
            const file = fileInput?.files?.[0];
            if (!file) return showError('Selecione um arquivo .zip para importar.');
            const progress = document.getElementById('wikiDocImportProgress');
            const btn = document.getElementById('wikiDocImportConfirmBtn');
            if (progress) { progress.style.display = 'block'; progress.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Importando...'; }
            if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
            const formData = new FormData();
            formData.append('file', file);
            try {
                const res = await fetch(`${API_BASE}/wikitoca/documents/import-zip`, { method: 'POST', body: formData });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    if (progress) progress.innerHTML = `<span style="color:#ef4444;"><i class="fas fa-times-circle"></i> Erro: ${data.error || 'Falha na importação'}</span>`;
                    if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
                    return;
                }
                const msg = `${data.imported} documento(s) importado(s) com sucesso.`;
                if (progress) progress.innerHTML = `<span style="color:#065f46;"><i class="fas fa-check-circle"></i> ${msg}</span>`;
                showSuccess(msg);
                await loadWikiDocuments();
                setTimeout(() => closeWikiDocImportModal(), 1800);
            } catch (err) {
                if (progress) progress.innerHTML = `<span style="color:#ef4444;"><i class="fas fa-times-circle"></i> Erro de conexão: ${err.message}</span>`;
                if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
            }
        }

        function formatFileSize(bytes) {
            const size = Number(bytes || 0);
            if (size < 1024) return `${size} B`;
            if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
            return `${(size / (1024 * 1024)).toFixed(1)} MB`;
        }

        // Initialize
        window.addEventListener('click', (event) => {
            if (event.target.id === 'profileModal') closeProfileModal();
            if (event.target.id === 'groupModal') closeGroupModal();
            if (event.target.id === 'statusRuleModal') closeStatusRuleModal();
            if (event.target.id === 'wikiEntryModal') closeWikiEntryModal();
        });

        window.addEventListener('DOMContentLoaded', async () => {
            ensureAutoTocaPresence();
            await loadSystemConfig();
            loadThemeConfig();
            window.addEventListener(AUTOTOCA_EXTENSION_PING_EVENT, handleAutoTocaExtensionPong);
            window.addEventListener(AUTOTOCA_EXTENSION_RESULT_EVENT, handleAutoTocaExtensionResult);
            await Promise.all([loadStatusConfig(), loadUserProfile(), loadPositions(), loadPositionGroupings(), loadMessageTemplates(), loadUiConfig(), loadITocaBaseStatus()]);
            const wikiSearchInput = document.getElementById('wikiSearchInput');
            if (wikiSearchInput) {
                wikiSearchInput.addEventListener('keydown', (event) => {
                    if (event.key === 'Enter') {
                        event.preventDefault();
                        loadWikiTocaData();
                    }
                });
            }
            const wikiTitle = document.getElementById('wikiEntryTitle');
            const wikiContent = document.getElementById('wikiEntryContent');
            if (wikiTitle) wikiTitle.addEventListener('blur', autoFillWikiTags);
            if (wikiContent) wikiContent.addEventListener('blur', autoFillWikiTags);
            loadDashboard();
            loadHome();
            setTimeout(checkForUpdatesOnStartup, 3000);
        });

