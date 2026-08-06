// ============================================================================
// AutoToca — Relatório Semanal
// Modal de seleção (contas + período) → task assíncrona com barra de progresso
// → relatório por conta, agrupado por assunto, com nome e foto dos contatos.
// Fontes compiladas no backend: atividades, Agenda e Kanban.
// ============================================================================

let _relSemanalAccounts = [];
let _relSemanalLastResult = null;

const REL_SEMANAL_STATUS_LABELS = {
    avancou: { label: 'Avançou', bg: '#ecfdf5', color: '#065f46', border: '#a7f3d0' },
    em_andamento: { label: 'Em andamento', bg: '#eff6ff', color: '#1e40af', border: '#bfdbfe' },
    parado: { label: 'Parado', bg: '#fef2f2', color: '#991b1b', border: '#fecaca' }
};

const REL_SEMANAL_SOURCE_ICONS = {
    'Atividade': 'fa-comments',
    'Atividade da conta': 'fa-building',
    'Agenda': 'fa-calendar-day',
    'Kanban': 'fa-columns'
};

function _relSemanalIsoDaysAgo(days) {
    const d = new Date();
    d.setDate(d.getDate() - days);
    return d.toISOString().slice(0, 10);
}

function _relSemanalFormatDate(value) {
    const raw = String(value || '').slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return value ? String(value) : 'Data não informada';
    const [y, m, d] = raw.split('-');
    return `${d}/${m}/${y}`;
}

// Avatar do contato: foto quando houver, senão a inicial (mesmo padrão da lista
// de clientes). É o "nome e foto do contato envolvido" pedido no relatório.
// A inicial fica sempre no fundo e a foto por cima: se a URL quebrar (foto
// remota que saiu do ar), o onerror só esconde o <img> e a inicial reaparece —
// sem HTML aninhado em atributo, que quebra com aspas no nome do contato.
function _relSemanalAvatar(contact, size = 34) {
    const name = escapeHtml(contact.name || 'Contato');
    const initial = escapeHtml(String(contact.name || '?').trim().charAt(0).toUpperCase() || '?');
    const photo = contact.photo_url
        ? `<img src="${escapeHtml(contact.photo_url)}" alt="${name}"
                style="position:absolute; inset:0; width:100%; height:100%; border-radius:50%; object-fit:cover;"
                onerror="this.style.display='none'">`
        : '';
    return `<div title="${name}"
                 style="position:relative; width:${size}px; height:${size}px; border-radius:50%; flex:0 0 auto;
                        background:#34d399; color:#fff; font-weight:700; font-size:${Math.round(size / 2.4)}px;
                        display:flex; align-items:center; justify-content:center; overflow:hidden;">
                ${initial}${photo}
            </div>`;
}

// ── Modal de seleção ────────────────────────────────────────────────────────

async function openRelatorioSemanalModal() {
    document.getElementById('relSemanalModal')?.remove();

    const modal = `
        <div class="modal active" id="relSemanalModal"
             onclick="if(event.target===this && document.getElementById('relSemanalFormArea')?.style.display!=='none') this.remove()">
            <div class="modal-content" style="max-width:720px;">
                <div class="modal-header">
                    <h2 class="modal-title"><i class="fas fa-calendar-week"></i> Relatório Semanal</h2>
                    <button class="modal-close" id="relSemanalCloseBtn"
                            onclick="document.getElementById('relSemanalModal').remove()">&#215;</button>
                </div>
                <div id="relSemanalFormArea">
                    <p style="margin:0 0 16px; color:#6b7280; font-size:13px;">
                        Escolha as contas e o período. O AutoToca compila as atividades, os compromissos
                        da Agenda e os cards do Kanban de cada conta e gera com IA um resumo da evolução
                        organizado por assunto tratado com os contatos.
                    </p>

                    <!-- Sem a classe .form-group de propósito: a regra global
                         '.form-group input { width:100%; padding:10px }' também
                         atinge checkbox, e o checkbox de cada conta passa a
                         ocupar a linha inteira, empurrando o nome para fora. -->
                    <div style="margin-bottom:16px;">
                        <label style="display:block; margin-bottom:6px; font-weight:600; color:#065f46;">Período</label>
                        <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px;">
                            <button type="button" class="btn btn-secondary btn-small" onclick="_relSemanalSetPeriod(6)">Últimos 7 dias</button>
                            <button type="button" class="btn btn-secondary btn-small" onclick="_relSemanalSetPeriod(13)">Últimas 2 semanas</button>
                            <button type="button" class="btn btn-secondary btn-small" onclick="_relSemanalSetPeriod(29)">Últimos 30 dias</button>
                        </div>
                        <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
                            <div>
                                <small style="color:#6b7280; font-size:11px;">Data inicial</small>
                                <input type="date" id="relSemanalStart" style="width:100%; padding:8px; border:1px solid #d1d5db; border-radius:6px;">
                            </div>
                            <div>
                                <small style="color:#6b7280; font-size:11px;">Data final</small>
                                <input type="date" id="relSemanalEnd" style="width:100%; padding:8px; border:1px solid #d1d5db; border-radius:6px;">
                            </div>
                        </div>
                    </div>

                    <div style="margin-bottom:8px;">
                        <label style="display:block; margin-bottom:6px; font-weight:600; color:#065f46;">Contas <span style="color:#dc2626;">*</span></label>
                        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:8px;">
                            <input type="search" id="relSemanalAccountFilter" placeholder="Filtrar contas..."
                                   oninput="_relSemanalRenderAccountList()"
                                   style="flex:1; min-width:180px; padding:8px; border:1px solid #d1d5db; border-radius:6px;">
                            <button type="button" class="btn btn-secondary btn-small" onclick="_relSemanalToggleAll(true)">Todas</button>
                            <button type="button" class="btn btn-secondary btn-small" onclick="_relSemanalToggleAll(false)">Nenhuma</button>
                        </div>
                        <div id="relSemanalAccountList"
                             style="max-height:240px; overflow-y:auto; border:1px solid #e5e7eb; border-radius:8px; padding:6px;">
                            <div style="padding:12px; color:#6b7280; font-size:13px;">Carregando contas...</div>
                        </div>
                        <div id="relSemanalSelectedCount" style="margin-top:6px; font-size:12px; color:#6b7280;"></div>
                    </div>
                </div>

                <div id="relSemanalProgressArea" style="display:none; padding:20px 4px 12px;">
                    <div style="font-size:13px; color:#6b7280; margin-bottom:12px; text-align:center;" id="relSemanalProgressStep">Iniciando...</div>
                    <div style="position:relative; background:#d1fae5; border-radius:99px; height:12px; overflow:visible; margin:0 16px 6px;">
                        <div id="relSemanalProgressBar" style="position:relative; height:100%; width:5%; background:linear-gradient(90deg,#059669,#10b981,#34d399); border-radius:99px; transition:width .6s ease;">
                            <img src="/images/coelho-correndo.webp" class="coelho-run" alt="">
                        </div>
                    </div>
                    <div style="display:flex; justify-content:flex-end; padding:0 16px;">
                        <div style="font-size:11px; color:#6b7280;" id="relSemanalProgressPct">5%</div>
                    </div>
                </div>

                <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:8px;">
                    <button id="relSemanalCancelBtn" class="btn btn-secondary"
                            onclick="document.getElementById('relSemanalModal').remove()">Cancelar</button>
                    <button id="relSemanalSubmitBtn" class="btn btn-auto-mapping btn-small" onclick="submitRelatorioSemanal()">
                        <span class="ai-star-icon">✦</span> Gerar Relatório
                    </button>
                </div>
            </div>
        </div>`;
    document.body.insertAdjacentHTML('beforeend', modal);

    _relSemanalSetPeriod(6);
    await _relSemanalLoadAccounts();
}

async function _relSemanalLoadAccounts() {
    try {
        const resp = await fetch(`${API_BASE}/autotoca/relatorio-semanal/contas`);
        if (!resp.ok) throw new Error('Não foi possível carregar as contas.');
        _relSemanalAccounts = await resp.json();
    } catch (error) {
        _relSemanalAccounts = [];
        showError(error.message || 'Erro ao carregar as contas.');
    }
    _relSemanalRenderAccountList();
}

function _relSemanalRenderAccountList() {
    const container = document.getElementById('relSemanalAccountList');
    if (!container) return;
    const term = (document.getElementById('relSemanalAccountFilter')?.value || '').trim().toLowerCase();
    // As marcações já feitas sobrevivem ao filtro: sem isto, digitar no campo de
    // busca apagaria silenciosamente contas que o usuário acabou de selecionar.
    const checked = _relSemanalSelectedIds();

    const visible = _relSemanalAccounts.filter(acc => !term || String(acc.name || '').toLowerCase().includes(term));
    if (!visible.length) {
        container.innerHTML = `<div style="padding:12px; color:#6b7280; font-size:13px;">${
            _relSemanalAccounts.length ? 'Nenhuma conta encontrada para esse filtro.' : 'Nenhuma conta cadastrada.'
        }</div>`;
        _relSemanalUpdateSelectedCount();
        return;
    }

    container.innerHTML = visible.map(acc => {
        const isChecked = checked.includes(Number(acc.id)) ? 'checked' : '';
        const logo = acc.logo_url
            ? `<img src="${escapeHtml(acc.logo_url)}" alt="" style="width:24px; height:24px; border-radius:6px; object-fit:contain; background:#f9fafb;">`
            : '<i class="fas fa-building" style="width:24px; text-align:center; color:#9ca3af;"></i>';
        const target = acc.is_target
            ? '<span style="background:#fef3c7; color:#92400e; border-radius:999px; padding:1px 7px; font-size:10px; font-weight:700;">TARGET</span>'
            : '';
        const contacts = Number(acc.contacts_count || 0);
        const contactsLabel = contacts === 1 ? '1 contato' : `${contacts} contatos`;
        return `<label style="display:flex; align-items:center; gap:10px; padding:7px 8px; border-radius:6px; cursor:pointer;">
                    <input type="checkbox" class="rel-semanal-acc" value="${acc.id}" ${isChecked}
                           onchange="_relSemanalUpdateSelectedCount()"
                           style="width:16px; height:16px; padding:0; flex:0 0 auto; accent-color:#059669; cursor:pointer;">
                    ${logo}
                    <span style="flex:1; min-width:0;">
                        <span style="font-size:13px; color:#111827;">${escapeHtml(acc.name || 'Conta sem nome')}</span>
                        <span style="display:block; font-size:11px; color:#9ca3af;">${contactsLabel}${
                            acc.sector ? ' · ' + escapeHtml(acc.sector) : ''}</span>
                    </span>
                    ${target}
                </label>`;
    }).join('');
    _relSemanalUpdateSelectedCount();
}

function _relSemanalSelectedIds() {
    return Array.from(document.querySelectorAll('.rel-semanal-acc:checked')).map(el => Number(el.value));
}

function _relSemanalUpdateSelectedCount() {
    const el = document.getElementById('relSemanalSelectedCount');
    if (!el) return;
    const total = _relSemanalSelectedIds().length;
    el.textContent = total ? `${total} conta(s) selecionada(s).` : 'Nenhuma conta selecionada.';
}

function _relSemanalToggleAll(value) {
    document.querySelectorAll('.rel-semanal-acc').forEach(el => { el.checked = value; });
    _relSemanalUpdateSelectedCount();
}

function _relSemanalSetPeriod(daysAgo) {
    const start = document.getElementById('relSemanalStart');
    const end = document.getElementById('relSemanalEnd');
    if (start) start.value = _relSemanalIsoDaysAgo(daysAgo);
    if (end) end.value = _relSemanalIsoDaysAgo(0);
}

function _relSemanalSetProgress(pct, step) {
    const bar = document.getElementById('relSemanalProgressBar');
    const stepEl = document.getElementById('relSemanalProgressStep');
    const pctEl = document.getElementById('relSemanalProgressPct');
    if (bar) bar.style.width = Math.max(5, pct) + '%';
    if (stepEl) stepEl.textContent = step || '';
    if (pctEl) pctEl.textContent = Math.round(pct) + '%';
}

// ── Execução ────────────────────────────────────────────────────────────────

async function submitRelatorioSemanal() {
    const accountIds = _relSemanalSelectedIds();
    const startDate = document.getElementById('relSemanalStart')?.value || '';
    const endDate = document.getElementById('relSemanalEnd')?.value || '';

    if (!accountIds.length) { showError('Selecione pelo menos uma conta.'); return; }
    if (!startDate || !endDate) { showError('Informe a data inicial e a data final.'); return; }
    if (startDate > endDate) { showError('A data inicial não pode ser posterior à data final.'); return; }

    const submitBtn = document.getElementById('relSemanalSubmitBtn');
    const cancelBtn = document.getElementById('relSemanalCancelBtn');
    const closeBtn = document.getElementById('relSemanalCloseBtn');
    const formArea = document.getElementById('relSemanalFormArea');
    const progressArea = document.getElementById('relSemanalProgressArea');

    const _restoreForm = () => {
        if (submitBtn) { submitBtn.disabled = false; submitBtn.style.display = ''; }
        if (cancelBtn) cancelBtn.style.display = '';
        if (closeBtn) closeBtn.style.display = '';
        if (formArea) formArea.style.display = '';
        if (progressArea) progressArea.style.display = 'none';
    };

    if (submitBtn) { submitBtn.disabled = true; submitBtn.style.display = 'none'; }
    if (cancelBtn) cancelBtn.style.display = 'none';
    if (closeBtn) closeBtn.style.display = 'none';
    if (formArea) formArea.style.display = 'none';
    if (progressArea) progressArea.style.display = 'block';
    _relSemanalSetProgress(5, 'Compilando registros das contas...');

    try {
        const resp = await fetch(`${API_BASE}/autotoca/relatorio-semanal`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_ids: accountIds, start_date: startDate, end_date: endDate })
        });
        const payload = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(payload.error || 'Erro ao iniciar o relatório.');
        const taskId = payload.task_id;
        if (!taskId) throw new Error('Resposta inesperada do servidor.');

        // Fechar o modal não cancela: a task continua e o resultado chega pelo
        // indicador de tarefas em background.
        if (closeBtn) {
            closeBtn.style.display = '';
            closeBtn.removeAttribute('onclick');
            closeBtn.addEventListener('click', () => {
                document.getElementById('relSemanalModal')?.remove();
            }, { once: true });
        }
        _attachBgTaskControls(
            progressArea, taskId,
            () => document.getElementById('relSemanalModal')?.remove(),
            () => { document.getElementById('relSemanalModal')?.remove(); showError('Tarefa cancelada.'); }
        );

        const sourceTab = typeof _currentTab !== 'undefined' ? _currentTab : 'autotoca';
        BgTaskManager.register(
            taskId,
            `${API_BASE}/autotoca/relatorio-semanal/tasks/${taskId}`,
            'Gerando Relatório Semanal',
            sourceTab,
            (result) => {
                document.getElementById('relSemanalModal')?.remove();
                renderRelatorioSemanal(result);
                showSuccess('Relatório Semanal gerado com sucesso!');
            },
            (errMsg) => {
                showError(errMsg || 'Erro ao gerar o Relatório Semanal.');
                _restoreForm();
            },
            (pct, step) => _relSemanalSetProgress(pct, step)
        );
    } catch (error) {
        showError(error.message || 'Erro ao gerar o Relatório Semanal.');
        _restoreForm();
    }
}

// ── Renderização do relatório ───────────────────────────────────────────────

function renderRelatorioSemanal(result) {
    const container = document.getElementById('relSemanalContent');
    if (!container) return;
    if (!result || !Array.isArray(result.accounts)) {
        container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📄</div>'
            + '<h3>Relatório indisponível</h3><p>Gere o relatório novamente.</p></div>';
        return;
    }
    _relSemanalLastResult = result;

    const period = result.period || {};
    const periodLabel = `${_relSemanalFormatDate(period.start_date)} a ${_relSemanalFormatDate(period.end_date)}`;
    const totals = result.totals || {};

    let html = `
        <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:16px; flex-wrap:wrap;
                    background:linear-gradient(135deg, rgba(4,120,87,0.96), rgba(6,95,70,0.96)); color:#fff;
                    padding:20px 22px; border-radius:14px; margin-bottom:18px;">
            <div style="min-width:240px;">
                <h3 style="margin:0 0 6px; font-size:20px; color:#fff;">Evolução por conta</h3>
                <div style="font-size:13px; color:rgba(255,255,255,0.92);">
                    Período: <strong>${escapeHtml(periodLabel)}</strong> ·
                    ${totals.accounts || 0} conta(s) · ${totals.events || 0} registro(s) ·
                    ${totals.assuntos || 0} assunto(s)
                </div>
            </div>
            <div style="display:flex; gap:8px; flex-wrap:wrap;">
                <button class="btn btn-secondary btn-small" onclick="openRelatorioSemanalModal()">
                    <i class="fas fa-sliders-h"></i> Alterar seleção
                </button>
                <button class="btn btn-secondary btn-small" onclick="printRelatorioSemanal()">
                    <i class="fas fa-print"></i> Imprimir / PDF
                </button>
            </div>
        </div>`;

    html += result.accounts.map(_relSemanalRenderAccount).join('');
    container.innerHTML = html;
    container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function _relSemanalRenderAccount(entry) {
    const account = entry.account || {};
    const counts = entry.counts || {};
    const logo = account.logo_url
        ? `<img src="${escapeHtml(account.logo_url)}" alt="" style="width:44px; height:44px; border-radius:10px; object-fit:contain; background:#f9fafb; border:1px solid #e5e7eb;">`
        : '<div style="width:44px; height:44px; border-radius:10px; background:#ecfdf5; color:#047857; display:flex; align-items:center; justify-content:center;"><i class="fas fa-building"></i></div>';

    const chip = (icon, label, value) => `
        <span style="display:inline-flex; align-items:center; gap:6px; background:#f9fafb; border:1px solid #e5e7eb;
                     border-radius:999px; padding:4px 10px; font-size:12px; color:#374151;">
            <i class="fas ${icon}" style="color:#059669;"></i> ${value} ${label}
        </span>`;

    const iaBadge = entry.llm_used
        ? '<span style="background:#ecfdf5; color:#065f46; border:1px solid #a7f3d0; border-radius:999px; padding:3px 10px; font-size:11px; font-weight:700;"><span class="ai-star-icon">✦</span> Resumo por IA</span>'
        : '<span style="background:#fff7ed; color:#9a3412; border:1px solid #fdba74; border-radius:999px; padding:3px 10px; font-size:11px; font-weight:700;" title="SAI e OpenRouter não responderam — os assuntos foram agrupados por palavra-chave.">Agrupamento automático</span>';

    let html = `
        <section style="background:#fff; border:1px solid #e5e7eb; border-radius:14px; padding:18px; margin-bottom:16px;">
            <div style="display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:12px;">
                ${logo}
                <div style="flex:1; min-width:200px;">
                    <div style="font-size:17px; font-weight:700; color:#065f46;">${escapeHtml(account.name || 'Conta sem nome')}</div>
                    <div style="font-size:12px; color:#9ca3af;">${escapeHtml(account.sector || 'Setor não informado')}</div>
                </div>
                ${iaBadge}
            </div>
            <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px;">
                ${chip('fa-comments', 'atividade(s)', counts.atividades || 0)}
                ${chip('fa-calendar-day', 'item(ns) de agenda', counts.agenda || 0)}
                ${chip('fa-columns', 'card(s) de Kanban', counts.kanban || 0)}
            </div>`;

    if (entry.resumo_periodo) {
        html += `<div style="background:#f0fdf4; border-left:4px solid #34d399; border-radius:0 8px 8px 0;
                             padding:12px 14px; margin-bottom:16px; font-size:13px; line-height:1.6; color:#374151;">
                    ${escapeHtml(entry.resumo_periodo)}
                 </div>`;
    }

    const contacts = entry.contacts || [];
    if (contacts.length) {
        html += `<div style="margin-bottom:16px;">
                    <div style="font-size:12px; font-weight:700; color:#065f46; margin-bottom:8px;">
                        Contatos envolvidos no período
                    </div>
                    <div style="display:flex; gap:14px; flex-wrap:wrap;">
                        ${contacts.map(contact => `
                            <div style="display:flex; align-items:center; gap:8px;">
                                ${_relSemanalAvatar(contact, 38)}
                                <div>
                                    <div style="font-size:13px; font-weight:600; color:#111827;">${escapeHtml(contact.name || '')}</div>
                                    <div style="font-size:11px; color:#9ca3af;">${escapeHtml(contact.position || 'Cargo não informado')}</div>
                                </div>
                            </div>`).join('')}
                    </div>
                 </div>`;
    }

    const assuntos = entry.assuntos || [];
    if (!assuntos.length) {
        html += `<div style="padding:14px; background:#f9fafb; border:1px dashed #d1d5db; border-radius:10px;
                             font-size:13px; color:#6b7280;">
                    Nenhum assunto identificado nesta conta no período selecionado.
                 </div>`;
    } else {
        html += '<div style="display:flex; flex-direction:column; gap:12px;">'
            + assuntos.map(_relSemanalRenderAssunto).join('')
            + '</div>';
    }

    const listBlock = (title, icon, items, color) => {
        if (!items || !items.length) return '';
        return `<div style="margin-top:14px;">
                    <div style="font-size:12px; font-weight:700; color:${color}; margin-bottom:6px;">
                        <i class="fas ${icon}"></i> ${title}
                    </div>
                    <ul style="margin:0; padding-left:20px; font-size:13px; color:#374151; line-height:1.7;">
                        ${items.map(item => `<li>${escapeHtml(item)}</li>`).join('')}
                    </ul>
                </div>`;
    };
    html += listBlock('Próximos passos', 'fa-forward', entry.proximos_passos, '#065f46');
    html += listBlock('Alertas', 'fa-triangle-exclamation', entry.alertas, '#9a3412');

    const events = entry.events || [];
    if (events.length) {
        html += `<details style="margin-top:16px;">
                    <summary style="cursor:pointer; font-size:12px; font-weight:700; color:#047857;">
                        Ver os ${events.length} registro(s) que originaram este resumo
                    </summary>
                    <div style="margin-top:10px; display:flex; flex-direction:column; gap:8px;">
                        ${events.map(_relSemanalRenderEvent).join('')}
                    </div>
                 </details>`;
    }

    html += '</section>';
    return html;
}

function _relSemanalRenderAssunto(assunto) {
    const status = REL_SEMANAL_STATUS_LABELS[assunto.status] || REL_SEMANAL_STATUS_LABELS.em_andamento;
    const origens = (assunto.origens || []).map(origin => `
        <span style="display:inline-flex; align-items:center; gap:5px; background:#f3f4f6; color:#4b5563;
                     border-radius:999px; padding:2px 9px; font-size:11px;">
            <i class="fas ${REL_SEMANAL_SOURCE_ICONS[origin] || 'fa-circle-dot'}"></i> ${escapeHtml(origin)}
        </span>`).join('');

    const contatos = (assunto.contatos || []).map(contact => `
        <div style="display:flex; align-items:center; gap:7px; background:#fff; border:1px solid #e5e7eb;
                    border-radius:999px; padding:3px 12px 3px 3px;">
            ${_relSemanalAvatar(contact, 28)}
            <div>
                <div style="font-size:12px; font-weight:600; color:#111827;">${escapeHtml(contact.name || '')}</div>
                <div style="font-size:10px; color:#9ca3af;">${escapeHtml(contact.position || 'Cargo não informado')}</div>
            </div>
        </div>`).join('');

    // Nome citado pela IA que não bate com nenhum contato cadastrado: aparece
    // como texto, sem foto, para o usuário conferir em vez de virar atribuição
    // silenciosa ao contato errado.
    const naoIdentificados = (assunto.contatos_nao_identificados || []).length
        ? `<span style="font-size:11px; color:#9a3412; background:#fff7ed; border:1px solid #fdba74;
                        border-radius:999px; padding:3px 10px;"
                 title="Citado no resumo, mas sem contato correspondente no cadastro.">
               ${escapeHtml((assunto.contatos_nao_identificados || []).join(', '))} (não cadastrado)
           </span>`
        : '';

    const semContato = (!contatos && !naoIdentificados)
        ? '<span style="font-size:11px; color:#9ca3af;">Sem contato vinculado</span>'
        : '';

    return `
        <article style="border:1px solid #e5e7eb; border-left:4px solid #10b981; border-radius:0 10px 10px 0; padding:12px 14px;">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:10px; flex-wrap:wrap; margin-bottom:8px;">
                <div style="font-size:14px; font-weight:700; color:#111827;">${escapeHtml(assunto.assunto || 'Assunto')}</div>
                <span style="background:${status.bg}; color:${status.color}; border:1px solid ${status.border};
                             border-radius:999px; padding:2px 10px; font-size:11px; font-weight:700;">${status.label}</span>
            </div>
            ${assunto.resumo ? `<div style="font-size:13px; color:#374151; line-height:1.6; margin-bottom:10px;">${escapeHtml(assunto.resumo)}</div>` : ''}
            <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:8px;">
                ${contatos}${naoIdentificados}${semContato}
            </div>
            ${origens ? `<div style="display:flex; gap:6px; flex-wrap:wrap;">${origens}</div>` : ''}
        </article>`;
}

function _relSemanalRenderEvent(event) {
    const icon = REL_SEMANAL_SOURCE_ICONS[event.source] || 'fa-circle-dot';
    return `
        <div style="display:flex; gap:10px; font-size:12px; color:#4b5563; padding:8px 10px; background:#f9fafb; border-radius:8px;">
            <i class="fas ${icon}" style="color:#059669; margin-top:2px;"></i>
            <div style="flex:1; min-width:0;">
                <div style="font-weight:600; color:#111827;">
                    ${escapeHtml(event.title || event.source || 'Registro')}
                    <span style="font-weight:400; color:#9ca3af;">
                        · ${escapeHtml(_relSemanalFormatDate(event.date))}
                        ${event.contact_name ? ' · ' + escapeHtml(event.contact_name) : ''}
                    </span>
                </div>
                <div style="line-height:1.5;">${escapeHtml(event.text || '')}</div>
            </div>
        </div>`;
}

function printRelatorioSemanal() {
    const container = document.getElementById('relSemanalContent');
    if (!container || !container.innerHTML.trim()) {
        showError('Gere o relatório antes de imprimir.');
        return;
    }
    const win = window.open('', '_blank');
    if (!win) { showError('O navegador bloqueou a janela de impressão.'); return; }
    // <details> fechado não imprime o conteúdo — o relatório impresso precisa
    // levar os registros de origem junto.
    const body = container.innerHTML.replace(/<details/g, '<details open');
    win.document.write(`<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
        <title>Relatório Semanal — Toca do Coelho</title>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
        <style>body{font-family:'Segoe UI',Arial,sans-serif; margin:24px; color:#111827;}
               button{display:none !important;} section{page-break-inside:avoid;}</style>
        </head><body>${body}</body></html>`);
    win.document.close();
    win.focus();
    setTimeout(() => win.print(), 400);
}

// Painel do AutoToca: na primeira abertura já pergunta contas e período; nas
// seguintes preserva o relatório já na tela.
function initRelatorioSemanalPanel() {
    const container = document.getElementById('relSemanalContent');
    if (container && !container.innerHTML.trim()) {
        openRelatorioSemanalModal();
    }
}
