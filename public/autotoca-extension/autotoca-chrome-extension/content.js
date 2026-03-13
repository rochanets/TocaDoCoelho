(() => {
  const WEB_PING_EVENT = 'autotoca-extension-ping';
  const WEB_PONG_EVENT = 'autotoca-extension-pong';
  const WEB_COMMAND_EVENT = 'autotoca-extension-command';
  const WEB_RESULT_EVENT = 'autotoca-extension-result';
  const STORAGE_KEY = 'autotoca-extension-envelope';
  const FORMS_URL_PREFIX = 'https://forms.office.com/Pages/ResponsePage.aspx';

  const LABEL_MAP = {
    contaSelecionada: ['conta', 'cliente', 'razao social', 'empresa'],
    tipoMinuta: ['tipo de minuta', 'minuta'],
    numeroContratoSalesforce: ['numero contrato sf', 'numero do contrato sf', 'contrato sf', 'salesforce'],
    dataAssinaturaContratoOriginal: ['data assinatura', 'assinatura', 'data do contrato'],
    enderecoFinalConfirmado: ['endereco'],
    clienteEncaminhouMinuta: ['minuta do cliente', 'cliente encaminhou minuta'],
    contratoOriginalModo: ['contrato original'],
    haveraReajusteValores: ['havera reajuste', 'reajuste'],
    indiceReajuste: ['indice utilizado', 'valor pos reajuste', 'indice e valor'],
    observacoesArquivos: ['observacoes', 'anexos', 'arquivos'],
  };

  function normalize(value) {
    return String(value || '')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, ' ')
      .trim();
  }

  function isFormsPage() {
    return window.location.href.startsWith(FORMS_URL_PREFIX);
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
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(envelope));
    } catch (error) {
      console.error('[AutoToca Helper] falha ao persistir envelope', error);
    }
  }

  function loadEnvelope() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
    } catch (_) {
      return null;
    }
  }

  function getQuestionText(el) {
    const texts = [];
    const container = el.closest('[role="listitem"], [data-automation-id], .office-form-question, .question-content, .question-body, div');
    if (container) texts.push(container.innerText || '');
    if (el.labels) texts.push(...Array.from(el.labels).map(label => label.innerText || ''));
    texts.push(el.getAttribute('aria-label') || '');
    texts.push(el.getAttribute('placeholder') || '');
    return normalize(texts.join(' | '));
  }

  function setNativeValue(el, value) {
    if (!el) return false;
    const stringValue = String(value ?? '');
    if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
      const descriptor = Object.getOwnPropertyDescriptor(el.constructor.prototype, 'value');
      if (descriptor && descriptor.set) descriptor.set.call(el, stringValue);
      else el.value = stringValue;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      el.dispatchEvent(new Event('blur', { bubbles: true }));
      return true;
    }
    if (el.getAttribute('contenteditable') === 'true') {
      el.innerText = stringValue;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('blur', { bubbles: true }));
      return true;
    }
    return false;
  }

  function getAllCandidates() {
    return Array.from(document.querySelectorAll('input:not([type="hidden"]):not([type="file"]), textarea, [contenteditable="true"]'));
  }

  function resolveValue(payload, key) {
    if (key === 'contratoOriginalModo') {
      return payload.contratoOriginalModo === 'nao_se_aplica' ? 'Não se aplica' : 'Arquivo enviado pelo usuário';
    }
    if (key === 'haveraReajusteValores') {
      return payload.haveraReajusteValores || 'Não';
    }
    if (key === 'observacoesArquivos') {
      return [
        payload.arquivosContratoOriginal?.length ? `Contrato original: ${payload.arquivosContratoOriginal.length} arquivo(s)` : 'Contrato original: sem arquivo',
        payload.arquivosAditivosAnteriores?.length ? `Aditivos anteriores: ${payload.arquivosAditivosAnteriores.length} arquivo(s)` : 'Aditivos anteriores: sem arquivo',
        payload.arquivosMinutaCliente?.length ? `Minuta do cliente: ${payload.arquivosMinutaCliente.length} arquivo(s)` : 'Minuta do cliente: sem arquivo',
        payload.arquivosAprovacaoCEO?.length ? `Aprovação CEO: ${payload.arquivosAprovacaoCEO.length} arquivo(s)` : 'Aprovação CEO: sem arquivo'
      ].join(' | ');
    }
    return payload[key] || '';
  }

  function fillFormsFromEnvelope(envelope) {
    const payload = envelope?.payload || {};
    const candidates = getAllCandidates();
    const results = [];

    Object.keys(LABEL_MAP).forEach((key) => {
      const value = resolveValue(payload, key);
      if (!value) {
        results.push({ key, applied: false, reason: 'empty_value' });
        return;
      }
      const target = candidates.find((el) => {
        const questionText = getQuestionText(el);
        return LABEL_MAP[key].some(term => questionText.includes(normalize(term)));
      });
      const applied = setNativeValue(target, value);
      results.push({
        key,
        applied,
        value,
        matchedText: target ? getQuestionText(target) : '',
      });
    });

    const fileInputs = Array.from(document.querySelectorAll('input[type="file"]')).map((el, index) => ({
      index,
      multiple: !!el.multiple,
      disabled: !!el.disabled,
      questionText: getQuestionText(el),
    }));

    return {
      ok: results.some(item => item.applied),
      message: results.some(item => item.applied)
        ? 'Preenchimento automático executado pela extensão.'
        : 'A extensão não encontrou campos compatíveis para preencher automaticamente.',
      results,
      fileInputs,
    };
  }

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
      if (!envelope || !envelope.payload) {
        emitResult({ ok: false, command, reason: 'missing_payload', message: 'Nenhum payload disponível na extensão para preencher o Forms.', href: window.location.href });
        return;
      }
      persistEnvelope(envelope);
      const fillResult = fillFormsFromEnvelope(envelope);
      emitResult({
        ok: fillResult.ok,
        command,
        href: window.location.href,
        savedAt: envelope.savedAt || null,
        ...fillResult,
      });
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
    }
  }

  window.addEventListener(WEB_PING_EVENT, emitPong);
  window.addEventListener(WEB_COMMAND_EVENT, (event) => {
    handleCommand(event?.detail || {}).catch(error => {
      emitResult({ ok: false, command: event?.detail?.command || 'unknown', message: error?.message || 'Erro inesperado na extensão.' });
    });
  });

  emitPong();
  if (isFormsPage()) {
    setTimeout(() => handleCommand({ command: 'ping_forms_autofill' }).catch(() => {}), 1200);
  }
})();
