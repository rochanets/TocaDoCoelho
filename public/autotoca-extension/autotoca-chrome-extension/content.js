(() => {
  // Confirmação visível no DevTools (F12 → Console) para diagnóstico
  console.log('[AutoToca Helper] content.js v0.9.4 carregado em:', window.location.href);

  const WEB_PING_EVENT    = 'autotoca-extension-ping';
  const WEB_PONG_EVENT    = 'autotoca-extension-pong';
  const WEB_COMMAND_EVENT = 'autotoca-extension-command';
  const WEB_RESULT_EVENT  = 'autotoca-extension-result';
  const STORAGE_KEY       = 'autotoca-extension-envelope';
  const LINKEDIN_KEY      = 'autotoca-linkedin-pending';
  const LOG_KEY           = 'autotoca-extension-logs';
  const MAX_LOG_ENTRIES   = 200;
  const FORMS_URL_PREFIX  = 'https://forms.office.com/Pages/ResponsePage.aspx';

  // ---- Sistema de Logs -------------------------------------------------------

  const _logBuffer = [];
  let _logFlushTimer = null;

  function _log(level, msg, data = {}) {
    const entry = { ts: new Date().toISOString(), level, msg, url: window.location.href, ...data };
    console.log(`[AutoToca Helper] [${level.toUpperCase()}] ${msg}`, Object.keys(data).length ? data : '');
    _logBuffer.push(entry);
    if (!_logFlushTimer) {
      _logFlushTimer = setTimeout(_flushLogs, 400);
    }
  }

  function _flushLogs() {
    _logFlushTimer = null;
    if (_logBuffer.length === 0) return;
    const toWrite = _logBuffer.splice(0);
    try {
      chrome.storage.local.get(LOG_KEY).then(stored => {
        const existing = Array.isArray(stored[LOG_KEY]) ? stored[LOG_KEY] : [];
        const merged = [...existing, ...toWrite];
        while (merged.length > MAX_LOG_ENTRIES) merged.shift();
        chrome.storage.local.set({ [LOG_KEY]: merged }).catch(() => {});
      }).catch(() => {});
    } catch (_) {}
  }

  // ---- Helpers gerais -------------------------------------------------------

  const LABEL_MAP = {
    contaSelecionada:             ['conta', 'cliente', 'razao social', 'empresa'],
    tipoMinuta:                   ['tipo de minuta', 'minuta'],
    numeroContratoSalesforce:     ['numero contrato sf', 'numero do contrato sf', 'contrato sf', 'salesforce'],
    dataAssinaturaContratoOriginal: ['data assinatura', 'assinatura', 'data do contrato'],
    enderecoFinalConfirmado:      ['endereco'],
    clienteEncaminhouMinuta:      ['minuta do cliente', 'cliente encaminhou minuta'],
    contratoOriginalModo:         ['contrato original'],
    haveraReajusteValores:        ['havera reajuste', 'reajuste'],
    indiceReajuste:               ['indice utilizado', 'valor pos reajuste', 'indice e valor'],
    observacoesArquivos:          ['observacoes', 'anexos', 'arquivos'],
  };

  function normalize(value) {
    return String(value || '')
      .normalize('NFD').replace(/[̀-ͯ]/g, '')
      .toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  }

  function isFormsPage() {
    return window.location.href.startsWith(FORMS_URL_PREFIX);
  }

  function isLinkedInProfilePage() {
    return window.location.hostname.includes('linkedin.com') &&
           /\/in\/[^/?#]+/.test(window.location.pathname);
  }

  function emitPong() {
    window.dispatchEvent(new CustomEvent(WEB_PONG_EVENT, {
      detail: {
        ok: true,
        extension: 'AutoToca Helper',
        version: '0.9.4',
        href: window.location.href,
        isFormsPage: isFormsPage(),
        timestamp: Date.now(),
      }
    }));
  }

  function emitResult(detail) {
    window.dispatchEvent(new CustomEvent(WEB_RESULT_EVENT, { detail }));
  }

  function persistEnvelope(envelope) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(envelope)); }
    catch (e) { console.error('[AutoToca Helper] falha ao persistir envelope', e); }
  }

  function loadEnvelope() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'); }
    catch (_) { return null; }
  }

  // ---- Forms autofill -------------------------------------------------------

  function getQuestionText(el) {
    const texts = [];
    const container = el.closest('[role="listitem"], [data-automation-id], .office-form-question, .question-content, .question-body, div');
    if (container) texts.push(container.innerText || '');
    if (el.labels) texts.push(...Array.from(el.labels).map(l => l.innerText || ''));
    texts.push(el.getAttribute('aria-label') || '');
    texts.push(el.getAttribute('placeholder') || '');
    return normalize(texts.join(' | '));
  }

  function setNativeValue(el, value) {
    if (!el) return false;
    const sv = String(value ?? '');
    if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
      const d = Object.getOwnPropertyDescriptor(el.constructor.prototype, 'value');
      if (d?.set) d.set.call(el, sv); else el.value = sv;
      el.dispatchEvent(new Event('input',  { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      el.dispatchEvent(new Event('blur',   { bubbles: true }));
      return true;
    }
    if (el.getAttribute('contenteditable') === 'true') {
      el.innerText = sv;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('blur',  { bubbles: true }));
      return true;
    }
    return false;
  }

  function resolveValue(payload, key) {
    if (key === 'contratoOriginalModo')
      return payload.contratoOriginalModo === 'nao_se_aplica' ? 'Não se aplica' : 'Arquivo enviado pelo usuário';
    if (key === 'haveraReajusteValores')
      return payload.haveraReajusteValores || 'Não';
    if (key === 'observacoesArquivos') {
      return [
        payload.arquivosContratoOriginal?.length   ? `Contrato original: ${payload.arquivosContratoOriginal.length} arquivo(s)`   : 'Contrato original: sem arquivo',
        payload.arquivosAditivosAnteriores?.length  ? `Aditivos anteriores: ${payload.arquivosAditivosAnteriores.length} arquivo(s)` : 'Aditivos anteriores: sem arquivo',
        payload.arquivosMinutaCliente?.length       ? `Minuta do cliente: ${payload.arquivosMinutaCliente.length} arquivo(s)`       : 'Minuta do cliente: sem arquivo',
        payload.arquivosAprovacaoCEO?.length        ? `Aprovação CEO: ${payload.arquivosAprovacaoCEO.length} arquivo(s)`           : 'Aprovação CEO: sem arquivo',
      ].join(' | ');
    }
    return payload[key] || '';
  }

  function fillFormsFromEnvelope(envelope) {
    const payload = envelope?.payload || {};
    const candidates = Array.from(document.querySelectorAll(
      'input:not([type="hidden"]):not([type="file"]), textarea, [contenteditable="true"]'
    ));
    const results = [];
    Object.keys(LABEL_MAP).forEach(key => {
      const value = resolveValue(payload, key);
      if (!value) { results.push({ key, applied: false, reason: 'empty_value' }); return; }
      const target = candidates.find(el =>
        LABEL_MAP[key].some(term => getQuestionText(el).includes(normalize(term)))
      );
      const applied = setNativeValue(target, value);
      results.push({ key, applied, value, matchedText: target ? getQuestionText(target) : '' });
    });
    const fileInputs = Array.from(document.querySelectorAll('input[type="file"]')).map((el, i) => ({
      index: i, multiple: !!el.multiple, disabled: !!el.disabled, questionText: getQuestionText(el),
    }));
    return {
      ok: results.some(r => r.applied),
      message: results.some(r => r.applied)
        ? 'Preenchimento automático executado pela extensão.'
        : 'A extensão não encontrou campos compatíveis para preencher automaticamente.',
      results, fileInputs,
    };
  }

  // ---- LinkedIn extraction --------------------------------------------------

  function extractLinkedInText() {
    const parts = [];

    const name = document.querySelector('h1')?.innerText?.trim();
    if (name) parts.push(`Nome: ${name}`);

    const headline = document.querySelector(
      '.text-body-medium.break-words, [data-generated-suggestion-target], .ph5 .mt2 .t-16'
    )?.innerText?.trim();
    if (headline) parts.push(`Cargo/Headline: ${headline}`);

    const location = document.querySelector('.text-body-small.inline.t-black--light.break-words')?.innerText?.trim();
    if (location) parts.push(`Localização: ${location}`);

    const connections = document.querySelector('.t-bold ~ span, [data-field="connections_count"]')?.innerText?.trim();
    if (connections) parts.push(`Conexões: ${connections}`);

    document.querySelectorAll('section').forEach(section => {
      const heading = section.querySelector('h2, h3')?.innerText?.trim();
      const body    = section.innerText?.trim();
      if (!body || body.length < 20) return;
      if (section.closest('nav, header, footer, aside')) return;
      const label = heading ? `\n=== ${heading} ===\n` : '\n---\n';
      parts.push(label + body);
    });

    if (parts.length <= 2) {
      const main = document.querySelector('main, .scaffold-layout__main');
      if (main) {
        const fallback = main.innerText?.replace(/\s+/g, ' ').trim();
        if (fallback) parts.push(fallback);
      }
    }

    return parts.join('\n').replace(/\n{3,}/g, '\n\n').trim().slice(0, 20000);
  }

  // LinkedIn renderiza a seção "Experiência" de forma preguiçosa (lazy) —
  // parte do histórico só entra no DOM depois que a seção passa pelo viewport.
  // Rola a página até o fim antes de capturar para garantir a trajetória completa.
  async function _ensureFullProfileRendered() {
    const scrollRoot = document.scrollingElement || document.documentElement;
    const totalHeight = scrollRoot.scrollHeight;
    const step = Math.max(window.innerHeight, 400);
    for (let y = 0; y <= totalHeight; y += step) {
      window.scrollTo(0, y);
      await new Promise(r => setTimeout(r, 180));
    }
    window.scrollTo(0, 0);
    await new Promise(r => setTimeout(r, 150));
  }

  // Palavras que indicam foto de capa/banner (não é a foto de perfil).
  const _COVER_PHOTO_HINTS = ['background', 'banner', 'cover', 'capa', 'fundo', 'bg-image'];

  function _looksLikeCoverPhoto(img) {
    const haystack = [
      img.getAttribute('src') || '',
      img.getAttribute('alt') || '',
      img.className || '',
      img.closest('[class]')?.className || '',
    ].join(' ').toLowerCase();
    if (_COVER_PHOTO_HINTS.some(hint => haystack.includes(hint))) return true;
    // Banners de capa são bem mais largos que altos; foto de perfil é ~quadrada.
    const w = img.naturalWidth || img.width;
    const h = img.naturalHeight || img.height;
    if (w && h && w / h > 1.6) return true;
    return false;
  }

  function extractLinkedInPhotoUrl() {
    // Fonte mais confiável: o próprio LinkedIn define a meta og:image como a foto de
    // perfil oficial da página (usada para compartilhamento), o que evita ter que
    // adivinhar a classe CSS certa em meio a um DOM que muda com frequência.
    const ogImage = document.querySelector('meta[property="og:image"]')?.getAttribute('content')?.trim();
    if (ogImage && /^https?:\/\//i.test(ogImage) && !ogImage.includes('ghost') && !ogImage.includes('placeholder') && !ogImage.includes('data:')) {
      return ogImage;
    }

    const selectors = [
      '.pv-top-card-profile-picture__image--show',
      '.pv-top-card-profile-picture__image',
      'img.pv-top-card-profile-picture__image',
      '.profile-photo-edit__preview',
      '.ph5 img.pv-top-card-profile-picture__image',
      'button[aria-label*="foto de perfil"] img',
      'button[aria-label*="profile picture"] img',
      'button[aria-label*="Foto de perfil"] img',
      'img[class*="profile-picture"]',
    ];

    for (const selector of selectors) {
      const el = document.querySelector(selector);
      const src = el?.getAttribute('src')?.trim() || '';
      if (src && /^https?:\/\//i.test(src) && !src.includes('ghost') && !src.includes('data:') && !_looksLikeCoverPhoto(el)) {
        return src;
      }
    }

    const mainEl = document.querySelector('main, .scaffold-layout__main');
    if (mainEl) {
      const imgs = Array.from(mainEl.querySelectorAll('img'));
      for (const img of imgs) {
        const src = (img.getAttribute('src') || '').trim();
        if (!src.startsWith('http')) continue;
        if (src.includes('ghost') || src.includes('placeholder')) continue;
        if (_looksLikeCoverPhoto(img)) continue;
        const alt = (img.getAttribute('alt') || '').toLowerCase();
        if (alt.includes('profile') || alt.includes('perfil') || alt.includes('foto')) return src;
        const w = img.naturalWidth || img.width;
        const h = img.naturalHeight || img.height;
        if (w >= 80 && w <= 500 && Math.abs(w - h) <= 20) return src;
      }
    }

    return null;
  }

  async function fetchPhotoAsBase64(photoUrl) {
    if (!photoUrl) return null;
    try {
      const response = await fetch(photoUrl, { credentials: 'include', mode: 'cors' });
      if (!response.ok) return null;
      const blob = await response.blob();
      if (!blob || blob.size === 0) return null;
      return new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => {
          const result = reader.result;
          if (typeof result === 'string' && result.startsWith('data:image/')) {
            resolve(result);
          } else {
            resolve(null);
          }
        };
        reader.onerror = () => resolve(null);
        reader.readAsDataURL(blob);
      });
    } catch (e) {
      console.warn('[AutoToca Helper] Falha ao converter foto para base64:', e);
      return null;
    }
  }

  function injectLinkedInButton() {
    if (document.getElementById('autotoca-li-btn')) {
      _log('info', 'Botão já existe no DOM, pulando injeção');
      return;
    }

    _log('info', 'Injetando botão LinkedIn no DOM');

    const btn = document.createElement('button');
    btn.id = 'autotoca-li-btn';
    btn.innerHTML = `
      <span style="
        font-size:16px; font-weight:700;
        background:linear-gradient(135deg,#9333ea 0%,#60a5fa 55%,#22d3ee 100%);
        -webkit-background-clip:text; -webkit-text-fill-color:transparent;">✦</span>
      <span style="margin-left:6px;">Analisar com AutoToca</span>`;
    btn.style.cssText = `
      position:fixed; bottom:28px; right:28px; z-index:2147483647;
      background:linear-gradient(135deg,#ecfeff 0%,#dbeafe 55%,#e0f2fe 100%);
      color:#0f766e; border:1.5px solid #bae6fd; border-radius:24px;
      padding:11px 20px; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
      font-size:14px; font-weight:600; cursor:pointer;
      box-shadow:0 4px 20px rgba(147,197,253,0.55),inset 0 0 10px rgba(255,255,255,0.7);
      display:flex; align-items:center; transition:transform .15s,box-shadow .15s;`;

    btn.addEventListener('mouseenter', () => {
      btn.style.transform = 'translateY(-2px)';
      btn.style.boxShadow = '0 6px 28px rgba(147,197,253,0.7),inset 0 0 10px rgba(255,255,255,0.8)';
    });
    btn.addEventListener('mouseleave', () => {
      btn.style.transform = '';
      btn.style.boxShadow = '0 4px 20px rgba(147,197,253,0.55),inset 0 0 10px rgba(255,255,255,0.7)';
    });
    btn.addEventListener('click', captureLinkedInProfile);
    document.body.appendChild(btn);

    _log('info', 'Botão LinkedIn injetado com sucesso');
  }

  async function captureLinkedInProfile() {
    const btn = document.getElementById('autotoca-li-btn');
    if (btn) {
      btn.innerHTML = '<span style="margin-right:6px;">⏳</span> Capturando perfil...';
      btn.style.opacity = '0.8';
      btn.disabled = true;
    }

    _log('info', 'Iniciando captura de perfil LinkedIn');

    if (btn) btn.innerHTML = '<span style="margin-right:6px;">⏳</span> Carregando perfil completo...';
    await _ensureFullProfileRendered();

    const profileText  = extractLinkedInText();
    const profileUrl   = window.location.href;
    const photoUrl     = extractLinkedInPhotoUrl();

    _log('info', 'Dados extraídos', {
      textLen: profileText?.length || 0,
      hasPhoto: !!photoUrl,
    });

    let photoBase64 = null;
    let photoSource = 'none';
    if (photoUrl) {
      if (btn) btn.innerHTML = '<span style="margin-right:6px;">📷</span> Capturando foto...';
      photoBase64 = await fetchPhotoAsBase64(photoUrl);
      photoSource = photoBase64 ? 'linkedin_extension_base64' : 'linkedin_extension_url';
    }

    const data = {
      schemaVersion: 3,
      text: profileText,
      url: profileUrl,
      photoUrl: photoBase64 || photoUrl || null,
      photoSource,
      capturedAt: new Date().toISOString(),
    };

    // Salva via background service worker — único contexto compartilhado entre abas
    try {
      const resp = await chrome.runtime.sendMessage({ type: 'save_linkedin_profile', data });
      if (resp?.ok) {
        _log('info', 'Perfil salvo via background service worker (relay)');
      } else {
        throw new Error(resp?.error || 'background retornou erro');
      }
    } catch (e) {
      _log('warn', 'Falha no background relay, usando chrome.storage.local direto', { error: e.message });
      try {
        await chrome.storage.local.set({ [LINKEDIN_KEY]: data });
        _log('info', 'Perfil salvo diretamente no chrome.storage.local (fallback)');
      } catch (e2) {
        _log('error', 'Ambos os métodos de salvamento falharam', { error: e2.message });
      }
    }

    if (btn) {
      btn.innerHTML = `<span style="margin-right:6px;">✅</span> Perfil capturado! Volte ao AutoToca`;
      btn.style.background = 'linear-gradient(135deg,#d1fae5,#a7f3d0)';
      btn.style.opacity = '1';
      setTimeout(() => {
        btn.innerHTML = `<span style="
          font-size:16px; font-weight:700;
          background:linear-gradient(135deg,#9333ea 0%,#60a5fa 55%,#22d3ee 100%);
          -webkit-background-clip:text; -webkit-text-fill-color:transparent;">✦</span>
          <span style="margin-left:6px;">Analisar com AutoToca</span>`;
        btn.style.background = 'linear-gradient(135deg,#ecfeff 0%,#dbeafe 55%,#e0f2fe 100%)';
        btn.disabled = false;
      }, 5000);
    }
  }

  // ---- SPA URL Watcher -------------------------------------------------------

  let _lastUrl = '';

  function _onUrlChange(source) {
    const current = window.location.href;
    if (current === _lastUrl) return;
    const prev = _lastUrl;
    _lastUrl = current;

    _log('info', 'URL mudou', { source, de: prev || '(inicial)', para: current });

    // Remove botão de página anterior se ainda estiver no DOM
    const existingBtn = document.getElementById('autotoca-li-btn');
    if (existingBtn) {
      existingBtn.remove();
      _log('info', 'Botão removido após mudança de URL');
    }

    if (isLinkedInProfilePage()) {
      _log('info', 'Página de perfil LinkedIn detectada após navegação');
      _scheduleButtonInjection(0);
    } else {
      _log('info', 'Não é página de perfil LinkedIn', { pathname: window.location.pathname });
    }
  }

  // Verifica se a página de perfil LinkedIn tem conteúdo suficiente renderizado.
  // O LinkedIn mudou sua estrutura e o nome do perfil pode não estar mais em <h1>.
  function _isLinkedInProfileRendered() {
    // Sinal 1: h1 com texto (estrutura antiga do LinkedIn)
    const h1Text = document.querySelector('h1')?.innerText?.trim();
    if (h1Text) return { ready: true, signal: 'h1', value: h1Text.slice(0, 50) };

    // Sinal 2: qualquer heading (h2, h3) com texto — LinkedIn usa várias hierarquias
    for (const tag of ['h2', 'h3']) {
      const el = document.querySelector(`main ${tag}, .scaffold-layout__main ${tag}`);
      const txt = el?.innerText?.trim();
      if (txt) return { ready: true, signal: tag, value: txt.slice(0, 50) };
    }

    // Sinal 3: foto de perfil carregada (elemento comum em todas as versões)
    const photoSelectors = [
      '.pv-top-card-profile-picture__image',
      '.profile-photo-edit__preview',
      'button[aria-label*="foto"] img',
      'button[aria-label*="profile"] img',
      'button[aria-label*="Foto"] img',
      '.pv-top-card__photo img',
    ];
    for (const sel of photoSelectors) {
      if (document.querySelector(sel)) return { ready: true, signal: 'foto', value: sel };
    }

    // Sinal 4: card principal do perfil (artdeco-card é presente em todas as versões)
    if (document.querySelector('.artdeco-card .ph5, .pv-top-card')) {
      return { ready: true, signal: 'artdeco-card' };
    }

    // Sinal 5: na segunda tentativa em diante, a página deve ter main com conteúdo
    const mainEl = document.querySelector('main, .scaffold-layout__main');
    if (mainEl && mainEl.children.length > 2) {
      return { ready: true, signal: 'main-children', value: mainEl.children.length };
    }

    return { ready: false };
  }

  function _scheduleButtonInjection(attempt) {
    const delays = [900, 2000, 3500, 5500, 8000];
    if (attempt >= delays.length) {
      // Última chance: injeta de qualquer forma se ainda estiver no perfil
      if (isLinkedInProfilePage() && !document.getElementById('autotoca-li-btn')) {
        _log('warn', 'Tentativas esgotadas — injeção forçada');
        injectLinkedInButton();
      }
      return;
    }

    const urlAtSchedule = window.location.href;
    _log('info', `Tentativa ${attempt + 1} de ${delays.length + 1} agendada`, { delay: delays[attempt] + 'ms' });

    setTimeout(() => {
      if (window.location.href !== urlAtSchedule) {
        _log('info', `Tentativa ${attempt + 1} cancelada — URL mudou durante a espera`);
        return;
      }
      if (!isLinkedInProfilePage()) {
        _log('info', `Tentativa ${attempt + 1} cancelada — não é mais página de perfil`);
        return;
      }
      if (document.getElementById('autotoca-li-btn')) {
        _log('info', `Tentativa ${attempt + 1} desnecessária — botão já está no DOM`);
        return;
      }

      const { ready, signal, value } = _isLinkedInProfileRendered();

      if (ready) {
        _log('info', `Tentativa ${attempt + 1}: página pronta (${signal}), injetando botão`, value ? { value } : {});
        injectLinkedInButton();
      } else if (attempt >= 2) {
        // A partir da 3ª tentativa: injeta mesmo sem confirmação (evita não aparecer nunca)
        _log('warn', `Tentativa ${attempt + 1}: página não detectada, injetando mesmo assim (fallback)`);
        injectLinkedInButton();
      } else {
        _log('warn', `Tentativa ${attempt + 1}: página não pronta, reagendando`);
        _scheduleButtonInjection(attempt + 1);
      }
    }, delays[attempt]);
  }

  // Intercepta pushState/replaceState para detectar navegação SPA
  (function patchHistory() {
    try {
      const origPush = history.pushState.bind(history);
      history.pushState = function (...args) {
        origPush(...args);
        setTimeout(() => _onUrlChange('pushState'), 50);
      };
      const origReplace = history.replaceState.bind(history);
      history.replaceState = function (...args) {
        origReplace(...args);
        setTimeout(() => _onUrlChange('replaceState'), 50);
      };
    } catch (e) {
      _log('warn', 'Falha ao interceptar history API', { error: String(e) });
    }
    window.addEventListener('popstate', () => _onUrlChange('popstate'));
  })();

  // Polling como fallback para SPAs que não usam a history API padrão
  setInterval(() => _onUrlChange('interval'), 1500);

  // Guardian: re-injeta o botão se ele sumir do DOM enquanto estiver numa página de perfil.
  setInterval(() => {
    if (!isLinkedInProfilePage()) return;
    if (document.getElementById('autotoca-li-btn')) return;
    // Usa os mesmos múltiplos sinais — não depende mais apenas de h1
    const { ready, signal } = _isLinkedInProfileRendered();
    if (ready) {
      _log('warn', 'Guardian: botão ausente no DOM, re-injetando', { signal });
      injectLinkedInButton();
    }
  }, 2000);

  // MutationObserver no <title> do documento: o LinkedIn atualiza o título da aba
  // a cada navegação SPA — mais confiável que history.pushState num isolated world.
  (function watchTitleChanges() {
    const titleEl = document.querySelector('title');
    if (!titleEl) return;
    const observer = new MutationObserver(() => {
      // Pequena espera para o URL estar atualizado junto com o título
      setTimeout(() => _onUrlChange('titleMutation'), 100);
    });
    observer.observe(titleEl, { childList: true });
  })();

  // ---- Command handler ------------------------------------------------------

  async function handleCommand(detail) {
    const command = detail?.command;

    if (command === 'start_reembolso_task') {
      if (!['localhost', '127.0.0.1'].includes(window.location.hostname)) {
        emitResult({ ok: false, command, taskId: detail?.taskId, message: 'Este comando só pode ser iniciado pelo AutoToca local.' });
        return;
      }
      try {
        const response = await chrome.runtime.sendMessage({
          type: 'start_reembolso_task',
          task: {
            taskId: detail?.taskId,
            apiBase: detail?.apiBase,
            targetUrl: detail?.targetUrl,
          },
        });
        emitResult({
          ok: !!response?.ok,
          command,
          taskId: detail?.taskId,
          tabId: response?.tabId,
          message: response?.ok ? 'e-Reembolso aberto em uma nova aba.' : (response?.error || 'Falha ao abrir a aba.'),
        });
      } catch (error) {
        emitResult({ ok: false, command, taskId: detail?.taskId, message: error?.message || String(error) });
      }
      return;
    }

    if (command === 'store_payload') {
      persistEnvelope(detail.envelope || null);
      emitResult({ ok: true, command, message: 'Payload salvo na extensão.', href: window.location.href });
      return;
    }

    if (command === 'fill_current_forms') {
      const envelope = detail?.envelope || loadEnvelope();
      if (!isFormsPage()) {
        emitResult({ ok: false, command, reason: 'not_forms_page', message: 'A aba atual não é um Microsoft Forms suportado.', href: window.location.href });
        return;
      }
      if (!envelope?.payload) {
        emitResult({ ok: false, command, reason: 'missing_payload', message: 'Nenhum payload disponível.', href: window.location.href });
        return;
      }
      persistEnvelope(envelope);
      const fillResult = fillFormsFromEnvelope(envelope);
      emitResult({ ok: fillResult.ok, command, href: window.location.href, savedAt: envelope.savedAt || null, ...fillResult });
      return;
    }

    if (command === 'ping_forms_autofill') {
      const envelope = loadEnvelope();
      if (!isFormsPage() || !envelope?.payload) {
        emitResult({ ok: false, command, reason: 'unavailable', message: 'Sem contexto suficiente para autopreenchimento nesta aba.', href: window.location.href });
        return;
      }
      const fillResult = fillFormsFromEnvelope(envelope);
      emitResult({ ok: fillResult.ok, command, href: window.location.href, savedAt: envelope.savedAt || null, ...fillResult });
      return;
    }

    if (command === 'get_linkedin_profile') {
      let pending = null;

      // Busca via background service worker (relay confiável entre abas)
      try {
        const resp = await chrome.runtime.sendMessage({ type: 'get_linkedin_profile' });
        if (resp?.ok && resp?.data) {
          pending = resp.data;
          _log('info', 'Perfil recuperado via background service worker');
        }
      } catch (e) {
        _log('warn', 'Falha no background relay (leitura), tentando storage direto', { error: e.message });
      }

      // Fallback: leitura direta do chrome.storage.local
      if (!pending) {
        try {
          const stored = await chrome.storage.local.get(LINKEDIN_KEY);
          pending = stored[LINKEDIN_KEY] || null;
          if (pending) _log('info', 'Perfil recuperado via chrome.storage.local (fallback)');
        } catch (_) {}
      }

      if (!pending) {
        emitResult({ ok: false, command, reason: 'no_pending_profile', message: 'Nenhum perfil LinkedIn capturado ainda. Abra um perfil no LinkedIn e clique em "Analisar com AutoToca".' });
        return;
      }
      emitResult({
        ok: true,
        command,
        schemaVersion: pending.schemaVersion || 1,
        profileText: pending.text,
        profileUrl: pending.url,
        profilePhotoUrl: pending.photoUrl || null,
        profilePhotoSource: pending.photoSource || 'unknown',
        capturedAt: pending.capturedAt
      });
      return;
    }

    if (command === 'clear_linkedin_profile') {
      try { await chrome.runtime.sendMessage({ type: 'clear_linkedin_profile' }); } catch (_) {}
      try { await chrome.storage.local.remove(LINKEDIN_KEY); } catch (_) {}
      emitResult({ ok: true, command, message: 'Perfil capturado removido da extensão.' });
      return;
    }

    if (command === 'get_extension_logs') {
      let logs = [];
      try {
        const stored = await chrome.storage.local.get(LOG_KEY);
        logs = Array.isArray(stored[LOG_KEY]) ? stored[LOG_KEY] : [];
      } catch (_) {}
      emitResult({ ok: true, command, logs, count: logs.length });
      return;
    }

    if (command === 'clear_extension_logs') {
      try { await chrome.storage.local.remove(LOG_KEY); } catch (_) {}
      _log('info', 'Logs apagados via comando');
      emitResult({ ok: true, command, message: 'Logs da extensão apagados.' });
      return;
    }
  }

  // ---- Init -----------------------------------------------------------------

  _lastUrl = window.location.href;

  _log('info', 'Extensão AutoToca v0.9.4 carregada', {
    isLinkedInProfile: isLinkedInProfilePage(),
    isForms: isFormsPage(),
    pathname: window.location.pathname,
    hostname: window.location.hostname,
  });

  window.addEventListener(WEB_PING_EVENT, emitPong);
  window.addEventListener(WEB_COMMAND_EVENT, event => {
    handleCommand(event?.detail || {}).catch(err =>
      emitResult({ ok: false, command: event?.detail?.command || 'unknown', message: err?.message || 'Erro inesperado na extensão.' })
    );
  });

  emitPong();

  if (isFormsPage()) {
    setTimeout(() => handleCommand({ command: 'ping_forms_autofill' }).catch(() => {}), 1200);
  }

  if (isLinkedInProfilePage()) {
    _log('info', 'Página de perfil no carregamento inicial, iniciando injeção');
    _scheduleButtonInjection(0);
  }

  // ---- Captura automática "Siga o campeão" (Bloco 11) ------------------------
  // Ao visitar o perfil de um contato JÁ CADASTRADO no Toca do Coelho, captura
  // os dados visíveis (cargo/empresa) em background, sem exigir clique — modo
  // passivo: só acontece quando o usuário navega até o perfil por conta própria.

  const APP_BASE_URLS = ['http://localhost:3000', 'http://127.0.0.1:3000'];
  const WATCHLIST_KEY = 'autotoca-linkedin-watchlist';
  const AUTOCAP_KEY   = 'autotoca-autocapture-log';
  const WATCHLIST_TTL_MS = 30 * 60 * 1000;   // 30 min de cache da watchlist
  const AUTOCAP_COOLDOWN_MS = 6 * 60 * 60 * 1000;  // 6h por perfil

  async function _appFetch(path, options) {
    for (const base of APP_BASE_URLS) {
      try {
        const resp = await fetch(base + path, options);
        if (resp.ok) return resp;
      } catch (_) { /* app offline nessa base — tenta a próxima */ }
    }
    return null;
  }

  async function _getWatchlist() {
    try {
      const stored = await chrome.storage.local.get(WATCHLIST_KEY);
      const cached = stored[WATCHLIST_KEY];
      if (cached && (Date.now() - cached.at) < WATCHLIST_TTL_MS) return cached.items;
    } catch (_) {}
    const resp = await _appFetch('/api/linkedin/watchlist');
    if (!resp) return null;
    const items = await resp.json().catch(() => null);
    if (!Array.isArray(items)) return null;
    try { await chrome.storage.local.set({ [WATCHLIST_KEY]: { at: Date.now(), items } }); } catch (_) {}
    return items;
  }

  function _currentProfileSlug() {
    const m = window.location.pathname.match(/\/in\/([^/?#]+)/);
    return m ? decodeURIComponent(m[1]).toLowerCase() : null;
  }

  async function _autoCaptureIfKnownProfile() {
    if (!isLinkedInProfilePage()) return;
    const slug = _currentProfileSlug();
    if (!slug) return;
    try {
      const stored = await chrome.storage.local.get(AUTOCAP_KEY);
      const log = stored[AUTOCAP_KEY] || {};
      if (log[slug] && (Date.now() - log[slug]) < AUTOCAP_COOLDOWN_MS) return;
    } catch (_) {}
    const watchlist = await _getWatchlist();
    if (!watchlist || !watchlist.some(w => (w.slug || '').toLowerCase() === slug)) return;

    _log('info', 'Perfil de contato cadastrado detectado — captura automática', { slug });
    try {
      await _ensureFullProfileRendered();
      const text = extractLinkedInText();
      if (!text || text.length < 200) return;
      const resp = await _appFetch('/api/linkedin/auto-capture', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: window.location.href, text }),
      });
      const payload = resp ? await resp.json().catch(() => ({})) : {};
      _log('info', 'Captura automática enviada', { slug, changed: payload.changed || false });
      try {
        const stored = await chrome.storage.local.get(AUTOCAP_KEY);
        const log = stored[AUTOCAP_KEY] || {};
        log[slug] = Date.now();
        await chrome.storage.local.set({ [AUTOCAP_KEY]: log });
      } catch (_) {}
    } catch (e) {
      _log('warn', 'Falha na captura automática', { error: e?.message });
    }
  }

  if (isLinkedInProfilePage()) {
    setTimeout(() => _autoCaptureIfKnownProfile().catch(() => {}), 4000);
  }
  // Navegação SPA do LinkedIn: observa mudanças de URL
  let _autocapLastHref = window.location.href;
  setInterval(() => {
    if (window.location.href !== _autocapLastHref) {
      _autocapLastHref = window.location.href;
      if (isLinkedInProfilePage()) {
        setTimeout(() => _autoCaptureIfKnownProfile().catch(() => {}), 4000);
      }
    }
  }, 2000);
})();
