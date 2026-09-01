// ============================================================================
// iAta — Meu resumo
// Botão ao lado do "+ Nova Ata": modal de período (1 semana, 15 dias, 1 mês,
// todo o período) + contas com checkbox (todas marcadas ao abrir).
// Reaproveita o backend do Relatório Semanal (/api/autotoca/relatorio-semanal),
// que compila atividades, Agenda e Kanban por conta e resume com IA os temas
// em andamento — material pronto para reportar o status de cada conta ao chefe.
// Os helpers de renderização por conta (_relSemanalRenderAccount etc.) vêm de
// relatorio-semanal.js, carregado antes deste arquivo.
// ============================================================================

let _iataResumoAccounts = [];

const IATA_RESUMO_PERIODS = {
    semana: { label: '1 semana' },
    quinzena: { label: '15 dias' },
    mes: { label: '1 mês' },
    tudo: { label: 'Todo o período' }
};

function _iataResumoIsoToday() {
    return new Date().toISOString().slice(0, 10);
}

// Data inicial de cada período, sempre inclusiva (ex.: "1 semana" = hoje e os
// 6 dias anteriores). "Todo o período" usa uma data anterior a qualquer
// registro possível — o backend só filtra por intervalo, então isso traz tudo.
function _iataResumoStartDate(period) {
    const d = new Date();
    if (period === 'semana') d.setDate(d.getDate() - 6);
    else if (period === 'quinzena') d.setDate(d.getDate() - 14);
    else if (period === 'mes') d.setMonth(d.getMonth() - 1);
    else return '2000-01-01';
    return d.toISOString().slice(0, 10);
}

// ── Modal de seleção ────────────────────────────────────────────────────────

async function openIAtaMeuResumoModal() {
    document.getElementById('iataMeuResumoModal')?.remove();

    const periodOptions = Object.entries(IATA_RESUMO_PERIODS).map(([value, info], idx) => `
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer; margin:0;
                      border:1px solid #e5e7eb; border-radius:8px; padding:8px 12px; flex:1; min-width:120px;">
            <input type="radio" name="iataResumoPeriod" value="${value}"${idx === 0 ? ' checked' : ''}
                   style="width:auto; margin:0; flex-shrink:0; accent-color:#059669;">
            <span style="font-size:13px;">${info.label}</span>
        </label>`).join('');

    const modal = `
        <div class="modal active" id="iataMeuResumoModal"
             onclick="if(event.target===this && document.getElementById('iataResumoFormArea')?.style.display!=='none') this.remove()">
            <div class="modal-content" style="max-width:720px;">
                <div class="modal-header">
                    <h2 class="modal-title"><i class="fas fa-clipboard-list"></i> Meu resumo</h2>
                    <button class="modal-close" id="iataResumoCloseBtn"
                            onclick="document.getElementById('iataMeuResumoModal').remove()">&#215;</button>
                </div>
                <div id="iataResumoFormArea">
                    <p style="margin:0 0 16px; color:#6b7280; font-size:13px;">
                        Escolha o período e as contas. O AutoToca compila as atividades, os compromissos
                        da Agenda e os cards do Kanban de cada conta e gera com IA um resumo dos temas
                        em andamento — pronto para reportar o status de cada conta.
                    </p>

                    <!-- Sem a classe .form-group de propósito: a regra global
                         '.form-group input { width:100%; padding:10px }' também
                         atinge radio/checkbox e quebra o layout. -->
                    <div style="margin-bottom:16px;">
                        <label style="display:block; margin-bottom:6px; font-weight:600; color:#065f46;">Período</label>
                        <div style="display:flex; gap:8px; flex-wrap:wrap;">${periodOptions}</div>
                    </div>

                    <div style="margin-bottom:8px;">
                        <label style="display:block; margin-bottom:6px; font-weight:600; color:#065f46;">Contas <span style="color:#dc2626;">*</span></label>
                        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:8px;">
                            <input type="search" id="iataResumoAccountFilter" placeholder="Filtrar contas..."
                                   oninput="_iataResumoRenderAccountList()"
                                   style="flex:1; min-width:180px; padding:8px; border:1px solid #d1d5db; border-radius:6px;">
                            <button type="button" class="btn btn-secondary btn-small" onclick="_iataResumoToggleAll(true)">Todas</button>
                            <button type="button" class="btn btn-secondary btn-small" onclick="_iataResumoToggleAll(false)">Nenhuma</button>
                        </div>
                        <div id="iataResumoAccountList"
                             style="max-height:240px; overflow-y:auto; border:1px solid #e5e7eb; border-radius:8px; padding:6px;">
                            <div style="padding:12px; color:#6b7280; font-size:13px;">Carregando contas...</div>
                        </div>
                        <div id="iataResumoSelectedCount" style="margin-top:6px; font-size:12px; color:#6b7280;"></div>
                    </div>
                </div>

                <div id="iataResumoProgressArea" style="display:none; padding:20px 4px 12px;">
                    <div style="font-size:13px; color:#6b7280; margin-bottom:12px; text-align:center;" id="iataResumoProgressStep">Iniciando...</div>
                    <div style="position:relative; background:#d1fae5; border-radius:99px; height:12px; overflow:visible; margin:0 16px 6px;">
                        <div id="iataResumoProgressBar" style="position:relative; height:100%; width:5%; background:linear-gradient(90deg,#059669,#10b981,#34d399); border-radius:99px; transition:width .6s ease;">
                            <img src="/images/coelho-correndo.webp" class="coelho-run" alt="">
                        </div>
                    </div>
                    <div style="display:flex; justify-content:flex-end; padding:0 16px;">
                        <div style="font-size:11px; color:#6b7280;" id="iataResumoProgressPct">5%</div>
                    </div>
                </div>

                <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:8px;">
                    <button id="iataResumoCancelBtn" class="btn btn-secondary"
                            onclick="document.getElementById('iataMeuResumoModal').remove()">Cancelar</button>
                    <button id="iataResumoSubmitBtn" class="btn btn-auto-mapping btn-small" onclick="submitIAtaMeuResumo()">
                        <span class="ai-star-icon">✦</span> Gerar Resumo
                    </button>
                </div>
            </div>
        </div>`;
    document.body.insertAdjacentHTML('beforeend', modal);

    await _iataResumoLoadAccounts();
}

async function _iataResumoLoadAccounts() {
    try {
        const resp = await fetch(`${API_BASE}/autotoca/relatorio-semanal/contas`);
        if (!resp.ok) throw new Error('Não foi possível carregar as contas.');
        _iataResumoAccounts = await resp.json();
    } catch (error) {
        _iataResumoAccounts = [];
        showError(error.message || 'Erro ao carregar as contas.');
    }
    // Pedido do fluxo: abre com todas as contas marcadas — o usuário desmarca
    // as que não quer, em vez de marcar uma a uma.
    _iataResumoRenderAccountList(true);
}

function _iataResumoRenderAccountList(checkAll = false) {
    const container = document.getElementById('iataResumoAccountList');
    if (!container) return;
    const term = (document.getElementById('iataResumoAccountFilter')?.value || '').trim().toLowerCase();
    // As marcações sobrevivem ao filtro: sem isto, digitar na busca apagaria
    // silenciosamente contas que o usuário acabou de selecionar.
    const checked = checkAll ? _iataResumoAccounts.map(acc => Number(acc.id)) : _iataResumoSelectedIds();

    const visible = _iataResumoAccounts.filter(acc => !term || String(acc.name || '').toLowerCase().includes(term));
    if (!visible.length) {
        container.innerHTML = `<div style="padding:12px; color:#6b7280; font-size:13px;">${
            _iataResumoAccounts.length ? 'Nenhuma conta encontrada para esse filtro.' : 'Nenhuma conta cadastrada.'
        }</div>`;
        _iataResumoUpdateSelectedCount();
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
                    <input type="checkbox" class="iata-resumo-acc" value="${acc.id}" ${isChecked}
                           onchange="_iataResumoUpdateSelectedCount()"
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
    _iataResumoUpdateSelectedCount();
}

function _iataResumoSelectedIds() {
    return Array.from(document.querySelectorAll('.iata-resumo-acc:checked')).map(el => Number(el.value));
}

function _iataResumoUpdateSelectedCount() {
    const el = document.getElementById('iataResumoSelectedCount');
    if (!el) return;
    const total = _iataResumoSelectedIds().length;
    el.textContent = total ? `${total} conta(s) selecionada(s).` : 'Nenhuma conta selecionada.';
}

function _iataResumoToggleAll(value) {
    document.querySelectorAll('.iata-resumo-acc').forEach(el => { el.checked = value; });
    _iataResumoUpdateSelectedCount();
}

function _iataResumoSetProgress(pct, step) {
    const bar = document.getElementById('iataResumoProgressBar');
    const stepEl = document.getElementById('iataResumoProgressStep');
    const pctEl = document.getElementById('iataResumoProgressPct');
    if (bar) bar.style.width = Math.max(5, pct) + '%';
    if (stepEl) stepEl.textContent = step || '';
    if (pctEl) pctEl.textContent = Math.round(pct) + '%';
}

// ── Execução ────────────────────────────────────────────────────────────────

async function submitIAtaMeuResumo() {
    const accountIds = _iataResumoSelectedIds();
    const period = document.querySelector('input[name="iataResumoPeriod"]:checked')?.value || 'semana';

    if (!accountIds.length) { showError('Selecione pelo menos uma conta.'); return; }

    const startDate = _iataResumoStartDate(period);
    const endDate = _iataResumoIsoToday();

    const submitBtn = document.getElementById('iataResumoSubmitBtn');
    const cancelBtn = document.getElementById('iataResumoCancelBtn');
    const closeBtn = document.getElementById('iataResumoCloseBtn');
    const formArea = document.getElementById('iataResumoFormArea');
    const progressArea = document.getElementById('iataResumoProgressArea');

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
    _iataResumoSetProgress(5, 'Compilando registros das contas...');

    try {
        const resp = await fetch(`${API_BASE}/autotoca/relatorio-semanal`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_ids: accountIds, start_date: startDate, end_date: endDate })
        });
        const payload = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(payload.error || 'Erro ao iniciar o resumo.');
        const taskId = payload.task_id;
        if (!taskId) throw new Error('Resposta inesperada do servidor.');

        // Fechar o modal não cancela: a task continua e o resultado chega pelo
        // indicador de tarefas em background.
        if (closeBtn) {
            closeBtn.style.display = '';
            closeBtn.removeAttribute('onclick');
            closeBtn.addEventListener('click', () => {
                document.getElementById('iataMeuResumoModal')?.remove();
            }, { once: true });
        }
        _attachBgTaskControls(
            progressArea, taskId,
            () => document.getElementById('iataMeuResumoModal')?.remove(),
            () => { document.getElementById('iataMeuResumoModal')?.remove(); showError('Tarefa cancelada.'); }
        );

        const sourceTab = typeof _currentTab !== 'undefined' ? _currentTab : 'autotoca';
        BgTaskManager.register(
            taskId,
            `${API_BASE}/autotoca/relatorio-semanal/tasks/${taskId}`,
            'Gerando Meu Resumo (iAta)',
            sourceTab,
            (result) => {
                document.getElementById('iataMeuResumoModal')?.remove();
                renderIAtaMeuResumo(result, period);
                showSuccess('Resumo gerado com sucesso!');
            },
            (errMsg) => {
                showError(errMsg || 'Erro ao gerar o resumo.');
                _restoreForm();
            },
            (pct, step) => _iataResumoSetProgress(pct, step)
        );
    } catch (error) {
        showError(error.message || 'Erro ao gerar o resumo.');
        _restoreForm();
    }
}

// ── Renderização do resumo ──────────────────────────────────────────────────

function renderIAtaMeuResumo(result, period) {
    const container = document.getElementById('iataMeuResumoContent');
    if (!container) return;
    if (!result || !Array.isArray(result.accounts)) {
        container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📄</div>'
            + '<h3>Resumo indisponível</h3><p>Gere o resumo novamente.</p></div>';
        container.style.display = '';
        return;
    }

    const periodInfo = IATA_RESUMO_PERIODS[period];
    const periodLabel = period === 'tudo'
        ? 'Todo o período'
        : `${periodInfo ? periodInfo.label : period} — ${_relSemanalFormatDate((result.period || {}).start_date)} a ${_relSemanalFormatDate((result.period || {}).end_date)}`;
    const totals = result.totals || {};

    let html = `
        <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:16px; flex-wrap:wrap;
                    background:linear-gradient(135deg, rgba(4,120,87,0.96), rgba(6,95,70,0.96)); color:#fff;
                    padding:20px 22px; border-radius:14px; margin-bottom:18px;">
            <div style="min-width:240px;">
                <h3 style="margin:0 0 6px; font-size:20px; color:#fff;">Meu resumo — status por conta</h3>
                <div style="font-size:13px; color:rgba(255,255,255,0.92);">
                    Período: <strong>${escapeHtml(periodLabel)}</strong> ·
                    ${totals.accounts || 0} conta(s) · ${totals.events || 0} registro(s) ·
                    ${totals.assuntos || 0} assunto(s)
                </div>
            </div>
            <div style="display:flex; gap:8px; flex-wrap:wrap;">
                <button class="btn btn-secondary btn-small" onclick="openIAtaMeuResumoModal()">
                    <i class="fas fa-sliders-h"></i> Alterar seleção
                </button>
                <button class="btn btn-secondary btn-small" onclick="printIAtaMeuResumo()">
                    <i class="fas fa-print"></i> Imprimir / PDF
                </button>
                <button class="btn btn-secondary btn-small" onclick="_iataResumoClear()" title="Fechar o resumo">
                    <i class="fas fa-times"></i> Fechar
                </button>
            </div>
        </div>`;

    html += result.accounts.map(_relSemanalRenderAccount).join('');
    container.innerHTML = html;
    container.style.display = '';
    container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function _iataResumoClear() {
    const container = document.getElementById('iataMeuResumoContent');
    if (!container) return;
    container.innerHTML = '';
    container.style.display = 'none';
}

function printIAtaMeuResumo() {
    const container = document.getElementById('iataMeuResumoContent');
    if (!container || !container.innerHTML.trim()) {
        showError('Gere o resumo antes de imprimir.');
        return;
    }
    const win = window.open('', '_blank');
    if (!win) { showError('O navegador bloqueou a janela de impressão.'); return; }
    // <details> fechado não imprime o conteúdo — o resumo impresso precisa
    // levar os registros de origem junto.
    const body = container.innerHTML.replace(/<details/g, '<details open');
    win.document.write(`<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
        <title>Meu resumo — iAta — Toca do Coelho</title>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
        <style>body{font-family:'Segoe UI',Arial,sans-serif; margin:24px; color:#111827;}
               button{display:none !important;} section{page-break-inside:avoid;}</style>
        </head><body>${body}</body></html>`);
    win.document.close();
    win.focus();
    setTimeout(() => win.print(), 400);
}
