// =====================================================
// Indicadores de conexão na abertura do sistema
//
// Pilha de círculos fixa no canto inferior direito (acima do indicador de
// tarefas em background) com o andamento das 3 verificações de conexão:
// WhatsApp (WAHA), Outlook (Microsoft Graph) e chaves de integração
// (Tavily / OpenRouter / iToca SAI).
//
// - Em andamento: anel verde cresce por marcos reais; clique abre o modal
//   do serviço mostrando o status ao vivo.
// - Sucesso: checkmark verde e fade-out após 3s.
// - Não configurado: círculo cinza neutro (não é falha), some junto.
// - Falha: X vermelho piscando, persiste; clique abre o modal com o motivo
//   e as ações de correção; ao fechar o modal a verificação reexecuta.
// - O toggle "Verificar conexões na abertura" (waha_startup_check_enabled,
//   via /api/whatsapp/startup-check) desliga tudo.
// =====================================================

const CONN_RING_LEN = 154; // 2*PI*24.5 — casa com stroke-dasharray no CSS

const CONN_CHECKS = {
    wa:   { label: 'WhatsApp',                icon: '<i class="fab fa-whatsapp"></i>', color: '#25d366', modalId: 'waConnectModal' },
    ms:   { label: 'Outlook / Microsoft 365', icon: '<i class="fas fa-cloud"></i>',    color: '#2563eb', modalId: 'ms365ConnectModal' },
    keys: { label: 'Chaves de integração',    icon: '<i class="fas fa-plug"></i>',     color: '#059669', modalId: 'connKeysModal' },
};

const _connStatus = {};      // id -> { state, progress, reason, fadeTimer }
let _connKeysDetail = null;  // última resposta de /api/config/integrations

// ---------- Renderização da pilha ----------

function _connCircleHtml(id) {
    const c = CONN_CHECKS[id];
    return `
        <div class="conn-circle" id="connCircle-${id}" data-state="running" title="${c.label} — verificando..." onclick="_connCircleClick('${id}')">
            <svg class="conn-ring" viewBox="0 0 54 54">
                <defs>
                    <linearGradient id="connGrad-${id}" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stop-color="#6ee7b7"/>
                        <stop offset="100%" stop-color="#059669"/>
                    </linearGradient>
                </defs>
                <circle class="conn-ring-track" cx="27" cy="27" r="24.5"></circle>
                <circle class="conn-ring-bar" cx="27" cy="27" r="24.5" stroke="url(#connGrad-${id})"></circle>
            </svg>
            <span class="conn-icon" style="color:${c.color};">${c.icon}</span>
            <span class="conn-badge"></span>
        </div>`;
}

function _connRenderStack() {
    document.getElementById('connStatusStack')?.remove();
    const html = `<div id="connStatusStack">${Object.keys(CONN_CHECKS).map(_connCircleHtml).join('')}</div>`;
    document.body.insertAdjacentHTML('beforeend', html);
}

function _connSetProgress(id, pct) {
    const st = _connStatus[id] = _connStatus[id] || {};
    st.progress = pct;
    const bar = document.querySelector(`#connCircle-${id} .conn-ring-bar`);
    if (bar) bar.style.strokeDashoffset = String(CONN_RING_LEN * (1 - pct / 100));
}

function _connFinish(id, state, reason) {
    const st = _connStatus[id] = _connStatus[id] || {};
    st.state = state;
    st.reason = reason || '';
    const el = document.getElementById(`connCircle-${id}`);
    if (!el) return;
    el.dataset.state = state;
    const badge = el.querySelector('.conn-badge');
    if (badge) badge.textContent = state === 'success' ? '✓' : state === 'error' ? '✕' : '–';
    if (state === 'success') _connSetProgress(id, 100);
    const suffix = st.reason ? ` — ${st.reason}` : (state === 'success' ? ' — conectado' : '');
    el.title = `${CONN_CHECKS[id].label}${suffix}`;
    if (state === 'success' || state === 'neutral') {
        st.fadeTimer = setTimeout(() => _connRemove(id), 3000);
    }
}

function _connRemove(id) {
    const el = document.getElementById(`connCircle-${id}`);
    if (!el) return;
    el.classList.add('conn-fadeout');
    setTimeout(() => {
        el.remove();
        const stack = document.getElementById('connStatusStack');
        if (stack && !stack.querySelector('.conn-circle')) stack.remove();
    }, 550);
}

/** Volta um círculo ao estado "em andamento" e reexecuta a verificação. */
function _connRecheck(id) {
    const el = document.getElementById(`connCircle-${id}`);
    if (!el) return;
    const st = _connStatus[id] = _connStatus[id] || {};
    if (st.fadeTimer) { clearTimeout(st.fadeTimer); st.fadeTimer = null; }
    st.state = 'running';
    st.reason = '';
    el.dataset.state = 'running';
    el.title = `${CONN_CHECKS[id].label} — verificando...`;
    _connSetProgress(id, 5);
    if (id === 'wa') _connCheckWhatsapp(0);
    else if (id === 'ms') _connCheckOutlook();
    else _connCheckKeys();
}

// ---------- Clique nos círculos ----------

function _connCircleClick(id) {
    if (id === 'wa') {
        openWhatsappConnectModal();
        _connWatchModalThenRecheck('wa');
    } else if (id === 'ms') {
        openMicrosoft365Modal();
        _connWatchModalThenRecheck('ms');
    } else {
        openIntegrationsStatusModal();
    }
}

/** Quando o modal do serviço fechar, reexecuta a verificação do círculo. */
function _connWatchModalThenRecheck(id) {
    const modalId = CONN_CHECKS[id].modalId;
    let seen = false;
    const timer = setInterval(() => {
        if (!document.getElementById(`connCircle-${id}`)) { clearInterval(timer); return; }
        const open = !!document.getElementById(modalId);
        if (open) { seen = true; return; }
        if (!seen) return; // modal ainda nem abriu
        clearInterval(timer);
        _connRecheck(id);
    }, 1200);
}

// ---------- Verificações ----------

async function _connCheckWhatsapp(attempt) {
    attempt = attempt || 0;
    if (attempt === 0) _connSetProgress('wa', 15);
    let st;
    try {
        st = await (await fetch(`${API_BASE}/whatsapp/status`)).json();
    } catch (e) {
        _connFinish('wa', 'error', 'Não foi possível contatar o servidor do Toca do Coelho.');
        return;
    }
    if (!st.configured) {
        _connFinish('wa', 'neutral', 'O WhatsApp (WAHA) ainda não foi configurado.');
        return;
    }
    if (st.connected) {
        _connFinish('wa', 'success');
        return;
    }
    // Cold start do WAHA-lite/Chrome: mesma tolerância do fluxo antigo (6 x 10s),
    // com o anel avançando devagar enquanto espera.
    if (st.state === 'starting' && attempt < 6) {
        _connSetProgress('wa', Math.min(80, 15 + (attempt + 1) * 11));
        setTimeout(() => _connCheckWhatsapp(attempt + 1), 10000);
        return;
    }
    let reason;
    if (st.state === 'starting') reason = 'O serviço do WhatsApp não respondeu a tempo.';
    else if (st.state === 'scan_qr') reason = 'WhatsApp aguardando leitura do QR code.';
    else reason = st.error || 'WhatsApp desconectado.';
    _connFinish('wa', 'error', reason);
}

async function _connCheckOutlook() {
    _connSetProgress('ms', 30);
    let st;
    try {
        st = await (await fetch(`${API_BASE}/outlook/graph-status`)).json();
    } catch (e) {
        _connFinish('ms', 'error', 'Não foi possível verificar a conexão com o Microsoft 365.');
        return;
    }
    if (st.connected) {
        _connFinish('ms', 'success', st.email ? `conectado como ${st.email}` : '');
        return;
    }
    if (st.needs_reauth || st.needs_consent || st.error) {
        _connFinish('ms', 'error', st.error || 'A autorização da conta Microsoft precisa ser refeita.');
        return;
    }
    // connected:false sem needs_reauth/consent nem erro = nunca conectou.
    _connFinish('ms', 'neutral', 'A conta Microsoft 365 ainda não foi conectada.');
}

async function _connCheckKeys() {
    _connSetProgress('keys', 30);
    let cfg;
    try {
        cfg = await (await fetch(`${API_BASE}/config/integrations`)).json();
    } catch (e) {
        _connFinish('keys', 'error', 'Não foi possível verificar as chaves de integração.');
        return;
    }
    if (cfg.error) {
        _connFinish('keys', 'error', cfg.error);
        return;
    }
    _connKeysDetail = cfg;
    const missing = [];
    if (!cfg.tavily_configured) missing.push('Tavily');
    if (!cfg.openrouter_configured) missing.push('OpenRouter');
    if (!cfg.itoca_sai_configured) missing.push('iToca SAI');
    _connSetProgress('keys', 100);
    if (missing.length === 0) _connFinish('keys', 'success');
    else _connFinish('keys', 'neutral', `chaves não configuradas: ${missing.join(', ')}`);
}

// ---------- Modal das chaves de integração ----------

function closeIntegrationsStatusModal() {
    document.getElementById(CONN_CHECKS.keys.modalId)?.remove();
}

function openIntegrationsStatusModal() {
    closeIntegrationsStatusModal();
    const info = _connStatus.keys || {};
    let body;
    if (_connKeysDetail) {
        const row = (name, ok, preview) => `
            <div style="display:flex; align-items:center; gap:10px; padding:8px 12px; border:1px solid #e5e7eb; border-radius:10px; margin-bottom:8px;">
                <span style="width:9px; height:9px; border-radius:50%; background:${ok ? '#059669' : '#9ca3af'}; flex-shrink:0;"></span>
                <div style="flex:1; font-size:13px; font-weight:600; color:#111827;">${name}</div>
                <div style="font-size:12px; color:${ok ? '#059669' : '#6b7280'};">${ok ? 'configurada' + (preview ? ` (${escapeHtml(preview)})` : '') : 'não configurada'}</div>
            </div>`;
        body = row('Tavily (busca)', _connKeysDetail.tavily_configured, _connKeysDetail.tavily_key_preview)
             + row('OpenRouter (LLM)', _connKeysDetail.openrouter_configured, _connKeysDetail.openrouter_key_preview)
             + row('iToca SAI', _connKeysDetail.itoca_sai_configured, _connKeysDetail.itoca_sai_key_preview);
    } else {
        body = `<div style="background:#fef2f2; border:1px solid #fca5a5; border-radius:10px; padding:14px 16px; font-size:13px; color:#991b1b;">
                    ${escapeHtml(info.reason || 'Não foi possível verificar as chaves de integração.')}
                </div>`;
    }
    const retryBtn = info.state === 'error'
        ? `<button class="btn btn-secondary btn-small" onclick="closeIntegrationsStatusModal(); _connRecheck('keys');"><i class="fas fa-rotate-right"></i> Tentar novamente</button>`
        : '';
    const html = `
        <div class="modal active" id="${CONN_CHECKS.keys.modalId}" onclick="if(event.target===this) closeIntegrationsStatusModal()">
            <div class="modal-content" style="max-width:460px;">
                <div class="modal-header">
                    <h2 class="modal-title"><i class="fas fa-plug" style="color:#059669;"></i> Chaves de Integração</h2>
                    <button class="modal-close" onclick="closeIntegrationsStatusModal()">&#215;</button>
                </div>
                <p style="font-size:12.5px; color:#6b7280; margin-bottom:12px;">Chaves do usuário final usadas pelas automações (busca, LLM e assistente iToca).</p>
                ${body}
                <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap; justify-content:flex-end; margin-top:14px; padding-top:12px; border-top:1px solid #e5e7eb;">
                    ${retryBtn}
                    <button class="btn btn-auto-mapping btn-small" onclick="closeIntegrationsStatusModal(); switchTab(null, 'configuracoes');">
                        <span class="ai-star-icon">✦</span> Ir para Configurações
                    </button>
                    <button class="btn btn-secondary btn-small" onclick="closeIntegrationsStatusModal()">Fechar</button>
                </div>
            </div>
        </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
}

// ---------- Inicialização ----------

async function connStatusInit() {
    try {
        const pref = await (await fetch(`${API_BASE}/whatsapp/startup-check`)).json();
        if (!pref.enabled) return; // toggle desligado: nada roda, nada aparece
        _connRenderStack();
        _connCheckWhatsapp(0);
        _connCheckOutlook();
        _connCheckKeys();
    } catch (e) { /* verificação silenciosa — nunca atrapalha a abertura */ }
}

// Pequeno atraso para não competir com os avisos de inicialização
// (primeiro acesso, envios perdidos, atualização da extensão).
document.addEventListener('DOMContentLoaded', () => setTimeout(connStatusInit, 2000));
