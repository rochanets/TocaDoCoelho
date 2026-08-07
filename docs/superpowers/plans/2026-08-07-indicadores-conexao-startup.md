# Indicadores de Conexão na Abertura (Pilha de Círculos) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir o popup automático de conexão do WhatsApp na abertura por uma pilha de 3 círculos de status (WhatsApp, Outlook, chaves de integração) no canto inferior direito, com anel de progresso, checkmark/fade-out no sucesso e X piscante persistente na falha.

**Architecture:** Feature 100% frontend. Novo módulo `public/js/connection-status.js` orquestra as 3 verificações em paralelo chamando endpoints existentes (`/api/whatsapp/status`, `/api/outlook/graph-status`, `/api/config/integrations`), renderiza a pilha fixa e reaproveita os modais existentes (`openWhatsappConnectModal`, `openMicrosoft365Modal`). O auto-open do modal de WhatsApp em `connection-check.js` é removido; o toggle `waha_startup_check_enabled` passa a controlar a pilha inteira.

**Tech Stack:** Vanilla JS + CSS (SVG ring com gradiente), Flask (sem mudanças), Font Awesome (ícones já usados no app).

**Spec:** `docs/superpowers/specs/2026-08-07-indicadores-conexao-startup-design.md`

**Nota sobre testes:** o projeto não tem runner de testes JS; a validação segue o padrão do projeto (CLAUDE.md): verificação manual contra instância local isolada (`PORT=3210` + `TOCA_DB_PATH` temporário), simulando estados via console.

---

## Contexto essencial do código (para quem chega sem contexto)

- `public/index.html` é o markup da SPA; o JS mora em `public/js/*.js`. `connection-check.js` é o último script (linha 2472). O indicador de tarefas em background `#bgTaskIndicator` (CSS em `app.css:2134`, `position:fixed; bottom:24px; right:24px; z-index:9999`) ocupa o canto inferior direito — a pilha nova fica ACIMA dele (`bottom:88px`).
- Z-index no app: modais `.modal` = 1000 (`app.css:787`); popup global de erros `#errorPopupStack` = 10700 (`app.css:1020`). A pilha usa **10650** (acima dos modais, abaixo dos erros).
- Respostas dos endpoints:
  - `GET /api/whatsapp/status` → `{configured, connected, state, error?}` com `state` ∈ `not_configured | no_session | unauthorized | connected | scan_qr | starting | offline | stopped | error` (`routes/whatsapp.py:42-91`).
  - `GET /api/outlook/graph-status` → conectado: `{connected:true, email, expires_at}`; senão `{connected:false, needs_reauth, needs_consent, error}`. **Nunca conectado** = `connected:false` com `needs_reauth:false, needs_consent:false, error:''` (`integrations/outlook_graph.py:623-650`).
  - `GET /api/config/integrations` → `{tavily_configured, tavily_key_preview, openrouter_configured, openrouter_key_preview, itoca_sai_configured, itoca_sai_key_preview, ...}` (`routes/config.py:349-387`).
  - `GET/PUT /api/whatsapp/startup-check` → `{enabled}` (setting `waha_startup_check_enabled`).
- Globals disponíveis para o módulo novo: `API_BASE`, `escapeHtml()`, `switchTab(null, 'configuracoes')`, `openWhatsappConnectModal()`, `openMicrosoft365Modal()`, `showSuccess/showError`.
- IDs dos modais existentes: `waConnectModal` e `ms365ConnectModal` (`connection-check.js:11`).

---

### Task 1: CSS da pilha de círculos

**Files:**
- Modify: `public/css/app.css` (inserir após o bloco `.coelho-run`, ~linha 2176)

- [ ] **Step 1: Adicionar os estilos**

Localizar o fim do bloco `.coelho-run { ... }` (termina em `pointer-events: none;` + `}`, ~linha 2176) e inserir logo depois:

```css
        /* ---- Indicadores de conexão na abertura (pilha de círculos) ---- */
        #connStatusStack {
            position: fixed;
            right: 24px;
            bottom: 88px; /* acima do #bgTaskIndicator (bottom:24 + 52 de altura + folga) */
            z-index: 10650; /* acima dos modais (1000); abaixo do #errorPopupStack (10700) */
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 10px;
            pointer-events: none;
        }
        .conn-circle {
            position: relative;
            width: 54px;
            height: 54px;
            border-radius: 50%;
            background: rgba(255,255,255,0.97);
            box-shadow: 0 4px 18px rgba(0,0,0,0.14);
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            pointer-events: auto;
            user-select: none;
            transition: opacity 0.5s ease, transform 0.5s ease;
        }
        .conn-circle .conn-icon { font-size: 21px; line-height: 1; }
        .conn-ring {
            position: absolute;
            inset: 0;
            transform: rotate(-90deg); /* progresso começa no topo */
            pointer-events: none;
        }
        .conn-ring-track { fill: none; stroke: #e5e7eb; stroke-width: 3; }
        .conn-ring-bar {
            fill: none;
            stroke-width: 3;
            stroke-linecap: round;
            stroke-dasharray: 154; /* 2*PI*24.5 — casa com CONN_RING_LEN no JS */
            stroke-dashoffset: 154;
            transition: stroke-dashoffset 0.7s ease;
            filter: drop-shadow(0 0 4px rgba(52,211,153,0.85)); /* brilho "luz moderna" */
        }
        .conn-circle[data-state="neutral"] .conn-ring-bar { display: none; }
        .conn-badge {
            position: absolute;
            top: -4px;
            right: -4px;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            display: none;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: 700;
            color: #fff;
            box-shadow: 0 2px 8px rgba(0,0,0,0.22);
        }
        .conn-circle[data-state="success"] .conn-badge { display: flex; background: #10b981; }
        .conn-circle[data-state="neutral"] .conn-badge { display: flex; background: #9ca3af; }
        .conn-circle[data-state="error"] .conn-badge {
            display: flex;
            background: #dc2626;
            animation: connBadgeBlink 1s ease-in-out infinite;
        }
        @keyframes connBadgeBlink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.25; }
        }
        .conn-circle.conn-fadeout { opacity: 0; transform: translateY(8px) scale(0.85); }
```

- [ ] **Step 2: Commit**

```bash
git add public/css/app.css
git commit -m "feat(ui): estilos da pilha de indicadores de conexao na abertura"
```

---

### Task 2: Módulo `connection-status.js`

**Files:**
- Create: `public/js/connection-status.js`

- [ ] **Step 1: Criar o arquivo com o módulo completo**

```javascript
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
```

- [ ] **Step 2: Commit**

```bash
git add public/js/connection-status.js
git commit -m "feat(ui): pilha de indicadores de conexao na abertura (WhatsApp, Outlook, chaves)"
```

---

### Task 3: Incluir o script e atualizar o rótulo do toggle em `index.html`

**Files:**
- Modify: `public/index.html:1561-1564` (rótulo do toggle) e `public/index.html:2472` (script include)

- [ ] **Step 1: Atualizar o rótulo do toggle**

Trocar (linhas 1561-1564):

```html
                    <label style="display:flex; align-items:center; gap:8px; cursor:pointer; user-select:none; font-size:13px; color:#4b5563;">
                        <input type="checkbox" id="waStartupCheckToggle" onchange="onWaStartupCheckToggle(this.checked)" style="width:17px; height:17px; cursor:pointer; accent-color:#10b981;">
                        Avisar na abertura do sistema quando o WhatsApp estiver desconectado
                    </label>
```

por:

```html
                    <label style="display:flex; align-items:center; gap:8px; cursor:pointer; user-select:none; font-size:13px; color:#4b5563;">
                        <input type="checkbox" id="waStartupCheckToggle" onchange="onWaStartupCheckToggle(this.checked)" style="width:17px; height:17px; cursor:pointer; accent-color:#10b981;">
                        Verificar conexões na abertura do sistema (WhatsApp, Outlook e chaves de integração)
                    </label>
```

- [ ] **Step 2: Incluir o novo script**

Trocar (linha 2472):

```html
    <script src="/js/connection-check.js"></script>
```

por:

```html
    <script src="/js/connection-check.js"></script>
    <script src="/js/connection-status.js"></script>
```

- [ ] **Step 3: Commit**

```bash
git add public/index.html
git commit -m "feat(ui): inclui connection-status.js e atualiza rotulo do toggle de abertura"
```

---

### Task 4: Remover o auto-open do modal de WhatsApp em `connection-check.js`

**Files:**
- Modify: `public/js/connection-check.js`

- [ ] **Step 1: Atualizar o comentário de cabeçalho (linhas 1-9)**

Trocar:

```javascript
        // =====================================================
        // Verificação de conexões (WhatsApp/WAHA e Microsoft 365)
        //
        // 1) Na abertura do sistema, checa em background se a sessão do
        //    WhatsApp está ativa. Se não estiver, abre um pop-up com o QR code
        //    do WAHA (com opções "fechar" e "não perguntar mais").
        // 2) Os mesmos modais ficam disponíveis sob demanda em
        //    Configurações → Integrações de API.
        // =====================================================
```

por:

```javascript
        // =====================================================
        // Modais de conexão (WhatsApp/WAHA e Microsoft 365)
        //
        // Disponíveis sob demanda em Configurações → Integrações de API e ao
        // clicar nos círculos de status da abertura (connection-status.js).
        // A verificação automática na abertura mora em connection-status.js.
        // =====================================================
```

- [ ] **Step 2: Remover o estado do fluxo de startup**

Trocar:

```javascript
        const _connModalIds = { wa: 'waConnectModal', ms: 'ms365ConnectModal' };
        let _waConnPollTimer = null;
        let _waConnOpenedFromStartup = false;
        let _ms365PollTimer = null;
```

por:

```javascript
        const _connModalIds = { wa: 'waConnectModal', ms: 'ms365ConnectModal' };
        let _waConnPollTimer = null;
        let _ms365PollTimer = null;
```

- [ ] **Step 3: Simplificar `openWhatsappConnectModal` (sem checkbox de startup)**

Trocar o bloco (docstring + função, linhas ~27-64):

```javascript
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
```

por:

```javascript
        /** Abre o modal de sincronização do WhatsApp. */
        function openWhatsappConnectModal() {
            closeWhatsappConnectModal();
```

E dentro do template HTML da mesma função, trocar a linha do rodapé:

```javascript
                        <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-top:14px; padding-top:12px; border-top:1px solid #e5e7eb;">
                            ${dontAskRow}
                            <button class="btn btn-secondary btn-small" style="margin-left:auto;" onclick="_waConnClose()">Fechar</button>
                        </div>
```

por:

```javascript
                        <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-top:14px; padding-top:12px; border-top:1px solid #e5e7eb;">
                            <button class="btn btn-secondary btn-small" style="margin-left:auto;" onclick="_waConnClose()">Fechar</button>
                        </div>
```

- [ ] **Step 4: Simplificar `_waConnClose`**

Trocar:

```javascript
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
```

por:

```javascript
        function _waConnClose() {
            closeWhatsappConnectModal();
            if (typeof loadConnectionsCard === 'function') loadConnectionsCard();
        }
```

- [ ] **Step 5: Remover `checkWhatsappConnectionOnStartup` e o listener**

Apagar o bloco inteiro (docstring + função, linhas ~147-169):

```javascript
        /**
         * Verificação em background na abertura do sistema.
         * Usa /status (que não acorda o Chrome) e só abre o modal — que aí sim
         * inicia a sessão para gerar o QR — quando a sessão está mesmo caída.
         */
        async function checkWhatsappConnectionOnStartup(attempt) {
            ...função inteira...
        }
```

E apagar no fim do arquivo (linhas ~331-333):

```javascript
        // Atrasa 3s para não competir com os avisos de inicialização
        // (envios perdidos, primeiro acesso, atualização da extensão).
        document.addEventListener('DOMContentLoaded', () => setTimeout(checkWhatsappConnectionOnStartup, 3000));
```

- [ ] **Step 6: Atualizar as mensagens do toggle**

Trocar em `onWaStartupCheckToggle`:

```javascript
                showSuccess(enabled ? 'Aviso de WhatsApp desconectado reativado.' : 'Aviso de WhatsApp desconectado desligado.');
```

por:

```javascript
                showSuccess(enabled ? 'Verificação de conexões na abertura ativada.' : 'Verificação de conexões na abertura desativada.');
```

- [ ] **Step 7: Conferir que nada mais referencia o que foi removido**

```bash
grep -rn "checkWhatsappConnectionOnStartup\|waConnDontAsk\|_waConnOpenedFromStartup\|openWhatsappConnectModal({" public/
```

Expected: nenhuma ocorrência.

- [ ] **Step 8: Commit**

```bash
git add public/js/connection-check.js
git commit -m "refactor(ui): remove auto-open do modal de WhatsApp na abertura (substituido pelos circulos)"
```

---

### Task 5: Verificação manual no preview

**Files:** nenhum novo (correções pontuais se surgirem defeitos).

- [ ] **Step 1: Subir instância isolada**

Criar banco temporário e subir na porta 3210 (não conflita com a instância do usuário na 3000; `PORT` e `TOCA_DB_PATH` são suportados — ver memória do projeto):

```bash
TOCA_DB_PATH="$TMP/toca-teste-conn.db" PORT=3210 python -c "import app; app.app.run(host='localhost', port=3210, use_reloader=False)"
```

(rodar via `python -c` evita o `webbrowser.open` do bloco `__main__`.)

- [ ] **Step 2: Abrir preview em `http://localhost:3210` e observar a pilha**

Esperado com banco zerado: após ~2s aparecem 3 círculos; WhatsApp → cinza neutro ("não configurado"), Outlook → cinza neutro, Chaves → cinza neutro; todos somem com fade após 3s.

Atenção: banco zerado pode acionar o fluxo de primeiro acesso (`/api/config/first-run`) — os círculos devem conviver com ele sem sobreposição de clique.

- [ ] **Step 3: Simular os demais estados via console (javascript_tool)**

```javascript
// re-renderiza a pilha e testa cada estado visual
_connRenderStack();
_connSetProgress('wa', 55);                        // anel parcial com glow
_connFinish('ms', 'error', 'Token expirado (teste)'); // X vermelho piscando, persiste
_connFinish('keys', 'success');                    // check verde, some em 3s
```

Verificar: anel com gradiente cresce suave; X pisca e círculo NÃO some; check some com fade; clique no X do Outlook abre `ms365ConnectModal`; fechar o modal faz o círculo voltar a "verificando" e reexecutar; clique no círculo de chaves abre o modal novo com as 3 linhas e botão "Ir para Configurações" funciona (`switchTab`).

- [ ] **Step 4: Testar o toggle**

Nas Configurações, desligar "Verificar conexões na abertura do sistema", recarregar a página: nenhum círculo deve aparecer. Religar e recarregar: círculos voltam.

- [ ] **Step 5: Screenshot de prova + commit final (se houve correções)**

```bash
git add -A
git commit -m "fix(ui): ajustes da verificacao manual dos indicadores de conexao"
```

(pular o commit se nada mudou.)

---

## Self-Review

- **Spec coverage:** popup removido (Task 4); 3 círculos com ícones (Task 2 `_connCircleHtml`); clique abre modal de status (Task 2 `_connCircleClick`); borda gradiente com glow crescendo por marcos (Task 1 CSS + `_connSetProgress`); checkmark + fade 3s (`_connFinish`/`_connRemove`); X piscando persistente com motivo + ações (CSS `connBadgeBlink` + modais existentes + `_connWatchModalThenRecheck`); neutro cinza (decisão 3); toggle reaproveitado (Tasks 3/4 + `connStatusInit`); posição acima do coelho (CSS `bottom:88px`). ✓
- **Placeholders:** nenhum TBD; todo step de código traz o código. ✓
- **Consistência de nomes:** `CONN_RING_LEN`=154 casa com `stroke-dasharray:154`; `modalId`s casam com `_connModalIds` de connection-check.js; `_connRecheck`/`_connFinish`/`_connSetProgress` usados consistentemente. ✓
