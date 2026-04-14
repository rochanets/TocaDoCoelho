(() => {
  const WEB_PING_EVENT    = 'autotoca-extension-ping';
  const WEB_PONG_EVENT    = 'autotoca-extension-pong';
  const WEB_COMMAND_EVENT = 'autotoca-extension-command';
  const WEB_RESULT_EVENT  = 'autotoca-extension-result';
  const STORAGE_KEY       = 'autotoca-extension-envelope';
  const LINKEDIN_KEY      = 'autotoca-linkedin-pending';
  const FORMS_URL_PREFIX  = 'https://forms.office.com/Pages/ResponsePage.aspx';

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
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
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
        version: '0.2.0',
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

    // Nome (h1 principal do perfil)
    const name = document.querySelector('h1')?.innerText?.trim();
    if (name) parts.push(`Nome: ${name}`);

    // Cargo/headline
    const headline = document.querySelector(
      '.text-body-medium.break-words, [data-generated-suggestion-target], .ph5 .mt2 .t-16'
    )?.innerText?.trim();
    if (headline) parts.push(`Cargo/Headline: ${headline}`);

    // Localização
    const location = document.querySelector('.text-body-small.inline.t-black--light.break-words')?.innerText?.trim();
    if (location) parts.push(`Localização: ${location}`);

    // Seguidores/conexões
    const connections = document.querySelector('.t-bold ~ span, [data-field="connections_count"]')?.innerText?.trim();
    if (connections) parts.push(`Conexões: ${connections}`);

    // Seções principais: Sobre, Experiência, Formação, Habilidades, etc.
    document.querySelectorAll('section').forEach(section => {
      const heading = section.querySelector('h2, h3')?.innerText?.trim();
      const body    = section.innerText?.trim();
      if (!body || body.length < 20) return;
      // Ignora seções de navegação, recomendações de pessoas, etc.
      if (section.closest('nav, header, footer, aside')) return;
      const label = heading ? `\n=== ${heading} ===\n` : '\n---\n';
      parts.push(label + body);
    });

    // Fallback: texto do main se não capturou seções suficientes
    if (parts.length <= 2) {
      const main = document.querySelector('main, .scaffold-layout__main');
      if (main) {
        const fallback = main.innerText?.replace(/\s+/g, ' ').trim();
        if (fallback) parts.push(fallback);
      }
    }

    return parts.join('\n').replace(/\n{3,}/g, '\n\n').trim().slice(0, 10000);
  }

  function extractLinkedInPhoto() {
    const selectors = [
      '.pv-top-card-profile-picture__image--show',
      '.pv-top-card-profile-picture__image',
      '.profile-photo-edit__preview',
      '.ph5 img.pv-top-card-profile-picture__image',
      'main img[alt*="foto de perfil"]',
      'main img[alt*="profile photo"]',
    ];
    for (const selector of selectors) {
      const el = document.querySelector(selector);
      const src = el?.getAttribute('src')?.trim() || '';
      if (src && /^https?:\/\//i.test(src)) return src;
    }
    const topImg = Array.from(document.querySelectorAll('main img')).find(img => {
      const src = img?.getAttribute('src') || '';
      const alt = (img?.getAttribute('alt') || '').toLowerCase();
      return /^https?:\/\//i.test(src) && (alt.includes('profile') || alt.includes('perfil'));
    });
    return topImg?.getAttribute('src')?.trim() || null;
  }

  function injectLinkedInButton() {
    if (document.getElementById('autotoca-li-btn')) return;

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
  }

  async function captureLinkedInProfile() {
    const btn = document.getElementById('autotoca-li-btn');
    if (btn) {
      btn.innerHTML = '<span style="margin-right:6px;">⏳</span> Capturando perfil...';
      btn.style.opacity = '0.8';
      btn.disabled = true;
    }

    const profileText = extractLinkedInText();
    const profileUrl  = window.location.href;
    const profilePhotoUrl = extractLinkedInPhoto();
    const data = {
      schemaVersion: 2,
      text: profileText,
      url: profileUrl,
      photoUrl: profilePhotoUrl || null,
      photoSource: profilePhotoUrl ? 'linkedin_extension' : 'none',
      capturedAt: new Date().toISOString(),
    };

    // Salva em chrome.storage.local (persistente entre tabs)
    try {
      await chrome.storage.local.set({ [LINKEDIN_KEY]: data });
    } catch (e) {
      // Firefox fallback: localStorage com prefixo
      try { localStorage.setItem(LINKEDIN_KEY, JSON.stringify(data)); } catch (_) {}
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

  // ---- Command handler ------------------------------------------------------

  async function handleCommand(detail) {
    const command = detail?.command;

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
      try {
        const stored = await chrome.storage.local.get(LINKEDIN_KEY);
        pending = stored[LINKEDIN_KEY] || null;
      } catch (_) {
        try { pending = JSON.parse(localStorage.getItem(LINKEDIN_KEY) || 'null'); } catch (__) {}
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
      try { await chrome.storage.local.remove(LINKEDIN_KEY); } catch (_) {
        try { localStorage.removeItem(LINKEDIN_KEY); } catch (__) {}
      }
      emitResult({ ok: true, command, message: 'Perfil capturado removido da extensão.' });
      return;
    }
  }

  // ---- Init -----------------------------------------------------------------

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
    // Injeta botão após a página carregar completamente (LinkedIn é SPA)
    const tryInject = () => {
      if (document.querySelector('h1')) injectLinkedInButton();
    };
    setTimeout(tryInject, 1500);
    setTimeout(tryInject, 3000); // segunda tentativa para SPAs lentas
  }
})();
