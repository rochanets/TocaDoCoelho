(() => {
  if (window.location.hostname !== 'ereembolso.stefanini.com.br') return;

  const normalize = value => String(value || '')
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9]+/g, ' ').trim().toLowerCase();
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  const isVisible = el => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  };
  const optionCode = value => {
    const match = String(value || '').match(/^\s*0*(\d+)(?:\s|[-–—]|$)/);
    return match ? Number(match[1]) : null;
  };
  const optionMatches = (actual, requested) => {
    const actualCode = optionCode(actual);
    const requestedCode = optionCode(requested);
    if (requestedCode !== null && actualCode === requestedCode) return true;
    const a = normalize(actual);
    const b = normalize(requested);
    return Boolean(a && b && (a === b || a.includes(b) || b.includes(a)));
  };

  function showStatus(text, error = false) {
    let badge = document.getElementById('autotoca-reembolso-status');
    if (!badge) {
      badge = document.createElement('div');
      badge.id = 'autotoca-reembolso-status';
      badge.style.cssText = [
        'position:fixed', 'right:20px', 'bottom:20px', 'z-index:2147483647',
        'max-width:420px', 'padding:12px 16px', 'border-radius:6px',
        'font:600 13px/1.4 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif',
        'box-shadow:0 6px 22px rgba(15,23,42,.25)'
      ].join(';');
      document.documentElement.appendChild(badge);
    }
    badge.style.background = error ? '#fee2e2' : '#ecfdf5';
    badge.style.color = error ? '#991b1b' : '#065f46';
    badge.style.border = `1px solid ${error ? '#fecaca' : '#a7f3d0'}`;
    badge.textContent = text;
  }

  async function getPendingTask() {
    try {
      const response = await chrome.runtime.sendMessage({ type: 'get_reembolso_task' });
      return response?.ok ? response.task : null;
    } catch (_) {
      return null;
    }
  }

  async function updateTask(task, update) {
    const response = await chrome.runtime.sendMessage({ type: 'update_reembolso_task', task, update });
    if (!response?.ok) throw new Error(response?.error || 'Falha ao atualizar a tarefa no AutoToca.');
  }

  async function setCheckpoint(task, checkpoint) {
    const response = await chrome.runtime.sendMessage({
      type: 'set_reembolso_checkpoint', taskId: task.taskId, checkpoint,
    });
    if (!response?.ok) throw new Error(response?.error || 'Falha ao salvar o progresso da automação.');
    task.checkpoint = checkpoint;
  }

  function findLabel(labelText) {
    const wanted = normalize(labelText);
    const candidates = Array.from(document.querySelectorAll(
      'label, .control-label, [class*="label" i], th, dt, span, strong'
    ));
    return candidates.find(el => {
      const text = normalize(el.textContent);
      return text === wanted || text.startsWith(`${wanted} `);
    }) || candidates.find(el => normalize(el.textContent).includes(wanted)) || null;
  }

  function controlCandidates(kind = 'combo') {
    const selector = kind === 'file'
      ? 'input[type="file"]'
      : kind === 'text'
        ? 'input:not([type]), input[type="text"], input[type="date"], textarea'
        : 'select, .select2-choice, .select2-selection, .chosen-single, [role="combobox"]';
    return Array.from(document.querySelectorAll(selector));
  }

  function findFieldControl(labelText, kind = 'combo', occurrence = 0) {
    const label = findLabel(labelText);
    if (!label) return null;
    if (label.htmlFor) {
      const linked = document.getElementById(label.htmlFor);
      if (linked) return linked;
    }

    const preferred = controlCandidates(kind);
    const ancestry = [label, label.parentElement, label.parentElement?.parentElement, label.parentElement?.parentElement?.parentElement];
    for (const root of ancestry) {
      if (!root) continue;
      const matches = preferred.filter(el => root !== el && root.contains(el));
      const visible = matches.filter(isVisible);
      if (visible.length === 1 && occurrence === 0) return visible[0];
      if (matches.length === 1 && occurrence === 0 && kind === 'file') return matches[0];
    }

    const labelRect = label.getBoundingClientRect();
    const ranked = preferred
      .filter(el => kind === 'file' || isVisible(el))
      .map(el => {
        const rect = el.getBoundingClientRect();
        const vertical = Math.max(0, rect.top - labelRect.bottom);
        const horizontal = Math.abs(rect.left - labelRect.left);
        const sameColumnPenalty = rect.right < labelRect.left || rect.left > labelRect.right + Math.max(180, labelRect.width)
          ? 1200 : 0;
        const abovePenalty = rect.bottom < labelRect.top ? 2000 : 0;
        return { el, score: vertical * 4 + horizontal + sameColumnPenalty + abovePenalty };
      })
      .sort((a, b) => a.score - b.score);
    return ranked[occurrence]?.el || null;
  }

  async function waitForField(labelText, kind = 'combo', timeoutMs = 20000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const control = findFieldControl(labelText, kind);
      if (control && !control.disabled && control.getAttribute('aria-disabled') !== 'true') return control;
      await delay(250);
    }
    throw new Error(`Não encontrei o controle habilitado do campo "${labelText}".`);
  }

  function setNativeValue(input, value) {
    const proto = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if (setter) setter.call(input, String(value));
    else input.value = String(value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }

  async function fillText(labelText, value, occurrence = 0) {
    const initial = await waitForField(labelText, 'text');
    const controls = controlCandidates('text').filter(el => {
      if (!isVisible(el)) return false;
      if (occurrence === 0) return el === initial;
      const label = findLabel(labelText);
      return label?.parentElement?.parentElement?.contains(el);
    });
    const control = occurrence === 0 ? initial : (controls[occurrence] || initial);
    if (String(control.value || '').trim() === String(value).trim()) return;
    control.focus();
    setNativeValue(control, value);
    if (String(control.value || '').trim() !== String(value).trim()) {
      throw new Error(`O campo "${labelText}" não reteve o valor informado.`);
    }
  }

  async function chooseOption(labelText, requested) {
    let control = await waitForField(labelText, 'combo');
    const selectedText = control.tagName === 'SELECT'
      ? control.options?.[control.selectedIndex]?.textContent
      : control.textContent;
    if (optionMatches(selectedText, requested)) return;
    if (control.tagName === 'SELECT' && isVisible(control)) {
      const option = Array.from(control.options).find(item => optionMatches(item.textContent, requested));
      if (!option) throw new Error(`Não encontrei a opção "${requested}" no campo "${labelText}".`);
      control.value = option.value;
      control.dispatchEvent(new Event('input', { bubbles: true }));
      control.dispatchEvent(new Event('change', { bubbles: true }));
      return;
    }

    if (control.tagName === 'SELECT') {
      const parent = control.parentElement;
      control = parent?.querySelector('.select2-choice, .select2-selection, .chosen-single, [role="combobox"]') || control;
    }
    control.click();

    const deadline = Date.now() + 10000;
    let options = [];
    while (Date.now() < deadline) {
      const search = Array.from(document.querySelectorAll(
        '.select2-input, .select2-search__field, .chosen-search input, input[type="search"]'
      )).find(isVisible);
      if (search) {
        const normalized = normalize(requested);
        const firstUsefulToken = normalized.split(' ').find(token => token.length >= 3) || normalized;
        const searchValue = optionCode(requested) !== null ? String(optionCode(requested)) : firstUsefulToken;
        setNativeValue(search, searchValue);
        search.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: 'a' }));
      }
      options = Array.from(document.querySelectorAll(
        '[role="option"], .select2-results__option, .select2-result-selectable, .select2-result-label, .chosen-results li'
      )).filter(isVisible);
      const match = options.find(item => optionMatches(item.textContent, requested));
      if (match) {
        match.click();
        return;
      }
      await delay(250);
    }
    throw new Error(
      `Não encontrei a opção "${requested}" no campo "${labelText}". ` +
      `Opções visíveis: ${options.map(item => item.textContent.trim()).slice(0, 10).join(' | ') || 'nenhuma'}.`
    );
  }

  async function chooseNative(labelText, requested) {
    const label = findLabel(labelText);
    const select = label?.htmlFor ? document.getElementById(label.htmlFor) : null;
    const ancestry = [label?.parentElement, label?.parentElement?.parentElement].filter(Boolean);
    const nearby = ancestry
      .map(root => Array.from(root.querySelectorAll('select')))
      .find(items => items.length === 1)?.[0];
    const control = select?.tagName === 'SELECT' ? select : (nearby || findFieldControl(labelText, 'combo'));
    if (!control || control.tagName !== 'SELECT') return chooseOption(labelText, requested);
    const selectedText = control.options?.[control.selectedIndex]?.textContent;
    if (optionMatches(selectedText, requested)) return;
    const option = Array.from(control.options).find(item => optionMatches(item.textContent, requested));
    if (!option) throw new Error(`Não encontrei a opção "${requested}" no campo "${labelText}".`);
    control.value = option.value;
    control.dispatchEvent(new Event('input', { bubbles: true }));
    control.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function findControlByIdSuffix(idSuffix) {
    return document.getElementById(`_ctl0_MainContent_${idSuffix}`) ||
      document.querySelector(`[id$="_${idSuffix}"]`);
  }

  async function waitForControlById(idSuffix, timeoutMs = 20000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const control = findControlByIdSuffix(idSuffix);
      if (control && !control.disabled && control.getAttribute('aria-disabled') !== 'true') return control;
      await delay(250);
    }
    throw new Error(`Não encontrei o controle externo "${idSuffix}".`);
  }

  async function chooseNativeById(idSuffix, requested) {
    const control = await waitForControlById(idSuffix);
    if (control.tagName !== 'SELECT') throw new Error(`O controle "${idSuffix}" não é uma lista de opções.`);
    const selectedText = control.options?.[control.selectedIndex]?.textContent;
    if (optionMatches(selectedText, requested)) return;
    const option = Array.from(control.options).find(item => optionMatches(item.textContent, requested));
    if (!option) throw new Error(`Não encontrei a opção "${requested}" no controle "${idSuffix}".`);
    control.value = option.value;
    control.dispatchEvent(new Event('input', { bubbles: true }));
    control.dispatchEvent(new Event('change', { bubbles: true }));
  }

  async function fillTextById(idSuffix, value) {
    const control = await waitForControlById(idSuffix);
    if (String(control.value || '').trim() === String(value).trim()) return;
    control.focus();
    setNativeValue(control, value);
    if (String(control.value || '').trim() !== String(value).trim()) {
      throw new Error(`O controle "${idSuffix}" não reteve o valor informado.`);
    }
  }

  function filesFromPayload(items) {
    return (items || []).map(item => {
      const binary = atob(item.base64);
      const bytes = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
      return new File([bytes], item.name, { type: item.mime || 'application/octet-stream' });
    });
  }

  async function uploadFiles(labelText, encodedItems) {
    const input = await waitForField(labelText, 'file');
    const transfer = new DataTransfer();
    filesFromPayload(encodedItems).forEach(file => transfer.items.add(file));
    input.files = transfer.files;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }

  async function uploadFilesById(idSuffix, encodedItems) {
    const input = await waitForControlById(idSuffix);
    if (input.type !== 'file') throw new Error(`O controle "${idSuffix}" não aceita arquivos.`);
    const transfer = new DataTransfer();
    filesFromPayload(encodedItems).forEach(file => transfer.items.add(file));
    input.files = transfer.files;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function formatDate(iso) {
    const [year, month, day] = String(iso || '').split('-');
    return year && month && day ? `${day}/${month}/${year}` : '';
  }

  async function fillPeriod(start, end) {
    const label = findLabel('PERIODO');
    if (!label) throw new Error('Não encontrei o rótulo de PERÍODO.');
    const labelRect = label.getBoundingClientRect();
    const ranked = controlCandidates('text')
      .filter(el => isVisible(el) && !el.classList.contains('select2-input'))
      .map(el => {
        const rect = el.getBoundingClientRect();
        const vertical = Math.max(0, rect.top - labelRect.bottom);
        const horizontal = Math.abs(rect.left - labelRect.left);
        const abovePenalty = rect.bottom < labelRect.top ? 2000 : 0;
        return { el, rect, score: vertical * 4 + horizontal + abovePenalty };
      })
      .sort((a, b) => a.score - b.score);
    const first = ranked[0];
    const second = ranked.slice(1).find(item => Math.abs(item.rect.top - first?.rect.top) < 40) || ranked[1];
    const inputs = [first?.el, second?.el].filter(Boolean);
    if (inputs.length < 2) throw new Error('Não encontrei os dois campos de PERÍODO.');
    if (String(inputs[0].value || '').trim() !== formatDate(start)) setNativeValue(inputs[0], formatDate(start));
    if (String(inputs[1].value || '').trim() !== formatDate(end)) setNativeValue(inputs[1], formatDate(end));
  }

  function clickByText(text, nearLabelText = '') {
    const wanted = normalize(text);
    const candidates = Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"], a'))
      .filter(el => isVisible(el) && normalize(el.textContent || el.value) === wanted);
    let candidate = candidates[0];
    const nearLabel = nearLabelText ? findLabel(nearLabelText) : null;
    if (nearLabel && candidates.length > 1) {
      const labelRect = nearLabel.getBoundingClientRect();
      candidate = candidates.map(el => {
        const rect = el.getBoundingClientRect();
        const belowPenalty = rect.bottom < labelRect.top ? 2000 : 0;
        return { el, score: Math.abs(rect.top - labelRect.bottom) + Math.abs(rect.left - labelRect.left) + belowPenalty };
      }).sort((a, b) => a.score - b.score)[0]?.el;
    }
    if (!candidate) throw new Error(`Não encontrei o botão "${text}".`);
    candidate.click();
  }

  function clickById(idSuffix) {
    const control = findControlByIdSuffix(idSuffix);
    if (!control || !isVisible(control)) throw new Error(`Não encontrei o botão externo "${idSuffix}".`);
    control.click();
  }

  async function fillCommon(task, data) {
    const payload = data.payload;
    await updateTask(task, { status: 'processing', progress: 30, step: 'Preenchendo Célula Custo...' });
    showStatus('AutoToca: preenchendo Célula Custo...');
    await chooseOption('CÉLULA CUSTO', payload.celula_custo);
    await delay(800);
    await waitForField('CLIENTE', 'combo');

    await updateTask(task, { status: 'processing', progress: 38, step: 'Preenchendo Cliente e Serviço...' });
    showStatus('AutoToca: preenchendo Cliente e Serviço...');
    await chooseOption('CLIENTE', 'Stefanini - Sao Paulo');
    await delay(800);
    await waitForField('SERVIÇO', 'combo');
    await chooseOption('SERVIÇO', 'Prospecção');
    await fillText('DESCRIÇÃO DA DESPESA', payload.descricao_despesa);
  }

  async function completeTask(task) {
    showStatus('AutoToca: preenchimento concluído. Revise os dados e envie.');
    await updateTask(task, {
      status: 'done', progress: 100,
      step: 'Preenchimento concluído. Revise os dados e clique em Enviar.',
    });
  }

  async function fillExpenseFields(payload, description) {
    await chooseNative('QUANTIDADE', String(payload.quantidade).padStart(2, '0'));
    await fillPeriod(payload.periodo_inicio, payload.periodo_fim);
    await fillText('VALOR TOTAL EM R$', Number(payload.valor_total).toFixed(2).replace('.', ','));
    if (description !== null) await fillText('DESCRIÇÃO', description);
  }

  async function fillOtherTravelFields(payload, description, travelType) {
    await chooseNativeById('ddlOutrosTipoDeslocamento', travelType);
    await chooseNativeById('ddlOutrosQuantidade', String(payload.quantidade).padStart(2, '0'));
    await fillTextById('txtOutrosPeriodoDe', formatDate(payload.periodo_inicio));
    await fillTextById('txtOutrosPeriodoA', formatDate(payload.periodo_fim));
    await fillTextById('txtOutrosValor', Number(payload.valor_total).toFixed(2).replace('.', ','));
    if (description !== null) await fillTextById('txtOutrosDescricao', description);
  }

  async function attachFiles(task, files, checkpoint, ids = null) {
    if (task.checkpoint === checkpoint) return false;
    await updateTask(task, { status: 'processing', progress: 72, step: 'Anexando comprovantes no e-Reembolso...' });
    if (ids) await uploadFilesById(ids.file, files);
    else await uploadFiles('COMPROVANTE', files);
    await setCheckpoint(task, checkpoint);
    if (ids) clickById(ids.attach);
    else clickByText('Anexar', 'COMPROVANTE');
    return true;
  }

  async function runTask(task, data) {
    const payload = data.payload;
    if (task.checkpoint === 'final-added') {
      await completeTask(task);
      return;
    }

    if (data.flow === 'almoco') {
      await fillCommon(task, data);
      await updateTask(task, { status: 'processing', progress: 58, step: 'Preenchendo Almoço com Cliente...' });
      await chooseNative('TIPO DE DESPESA', 'Gasto com cliente');
      await fillExpenseFields(payload, null);
      if (await attachFiles(task, data.files.comprovantes, 'expense-files-attached')) return;
      await fillText('DESCRIÇÃO', payload.descricao);
      await setCheckpoint(task, 'final-added');
      clickByText('adicionar', 'DESCRIÇÃO');
    } else if (data.flow === 'deslocamento:estacionamento') {
      await fillCommon(task, data);
      await updateTask(task, { status: 'processing', progress: 58, step: 'Preenchendo Estacionamento...' });
      await fillOtherTravelFields(payload, null, 'Estacionamento');
      if (await attachFiles(task, data.files.estacionamento_comprovantes, 'outros-files-attached', {
        file: 'fuOutrosFile', attach: 'lkAnexarOutrosFile',
      })) return;
      await fillOtherTravelFields(payload, payload.descricao_estacionamento, 'Estacionamento');
      await setCheckpoint(task, 'final-added');
      clickById('Button1');
    } else {
      if (!['deslocamento-added', 'outros-files-attached'].includes(task.checkpoint)) {
        await fillCommon(task, data);
        await updateTask(task, { status: 'processing', progress: 52, step: 'Preenchendo Origem e Destino...' });
        await fillText('ORIGEM', payload.origem);
        await fillText('DESTINO', payload.destino);
        await fillText('DATA DO DESLOCAMENTO', formatDate(payload.data_deslocamento));
        await chooseOption('TIPO DO TRANSPORTE', payload.tipo_transporte);
        if (payload.ida_e_volta) {
          const checkboxLabel = findLabel('DESLOCAMENTO IDA E VOLTA');
          const checkbox = checkboxLabel?.querySelector('input[type="checkbox"]') ||
            checkboxLabel?.parentElement?.querySelector('input[type="checkbox"]');
          if (checkbox && !checkbox.checked) checkboxLabel.click();
        }
        await fillText('DESCRIÇÃO DO DESLOCAMENTO', `Visita ao cliente ${payload.conta}, de ${payload.origem} à ${payload.destino}`);
        await setCheckpoint(task, 'deslocamento-added');
        clickByText('adicionar', 'DESCRIÇÃO DO DESLOCAMENTO');
        await delay(900);
      }
      if (payload.pedagio_valor_total) {
        const tollPayload = {
          quantidade: Math.max(1, data.files.pedagio_comprovantes?.length || 0),
          periodo_inicio: payload.data_deslocamento,
          periodo_fim: payload.data_deslocamento,
          valor_total: payload.pedagio_valor_total,
        };
        await fillOtherTravelFields(tollPayload, null, 'Pedágio');
        if (await attachFiles(task, data.files.pedagio_comprovantes, 'outros-files-attached', {
          file: 'fuOutrosFile', attach: 'lkAnexarOutrosFile',
        })) return;
        await fillOtherTravelFields(
          tollPayload, `Deslocamento para visitar cliente ${payload.conta}`, 'Pedágio'
        );
        await setCheckpoint(task, 'final-added');
        clickById('Button1');
      } else {
        await setCheckpoint(task, 'final-added');
      }
    }

    await delay(900);
    await completeTask(task);
  }

  async function init() {
    const task = await getPendingTask();
    if (!task) return;

    const loginVisible = Boolean(document.querySelector('input[type="password"]')) ||
      /login|signin|sign-in|logon/i.test(window.location.href);
    if (loginVisible) {
      showStatus('AutoToca: faça login no e-Reembolso. O preenchimento continuará automaticamente.');
      await updateTask(task, {
        status: 'processing', progress: 18,
        step: 'Faça login nesta aba. O robô continuará automaticamente após a autenticação.',
      }).catch(() => {});
      return;
    }

    if (window.location.href.split('#')[0] !== task.targetUrl) {
      window.location.replace(task.targetUrl);
      return;
    }

    showStatus('AutoToca: carregando os dados do reembolso...');
    try {
      const response = await chrome.runtime.sendMessage({ type: 'load_reembolso_task', task });
      if (!response?.ok) throw new Error(response?.error || 'Não foi possível carregar os dados do AutoToca.');
      await runTask(task, response.data);
    } catch (error) {
      const message = error?.message || String(error);
      showStatus(`AutoToca: ${message}`, true);
      await updateTask(task, { status: 'error', progress: 0, step: '', error: message }).catch(() => {});
    }
  }

  setTimeout(() => init().catch(() => {}), 700);
})();
