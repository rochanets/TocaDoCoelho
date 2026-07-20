// Cache em memória — persiste enquanto o service worker estiver vivo
let _pendingProfile = null;
const REEMBOLSO_TASK_KEY = 'autotoca-reembolso-task';

function _validLocalApiBase(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(url.hostname);
  } catch (_) {
    return false;
  }
}

function _validReembolsoUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === 'ereembolso.stefanini.com.br';
  } catch (_) {
    return false;
  }
}

chrome.runtime.onInstalled.addListener(() => {
  console.log('[AutoToca Helper] instalada com sucesso');
  _checkForUpdate();
});

// ---------------------------------------------------------------------------
// Auto-atualização: a extensão é carregada "sem compactação" de uma pasta estável
// que o app mantém sempre na versão mais nova. Aqui verificamos periodicamente a
// versão publicada pelo app e, se estivermos defasados, chamamos
// chrome.runtime.reload() — o Chrome recarrega a extensão do disco (já atualizado
// pelo app), sem download, descompactação ou re-adição manual.
// ---------------------------------------------------------------------------
const _UPDATE_CHECK_URLS = [
  'http://localhost:3000/api/extension/current-version',
  'http://127.0.0.1:3000/api/extension/current-version',
];
const _UPDATE_ALARM = 'autotoca-update-check';

function _cmpVersion(a, b) {
  const pa = String(a).split('.').map(n => Number(n) || 0);
  const pb = String(b).split('.').map(n => Number(n) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const diff = (pa[i] || 0) - (pb[i] || 0);
    if (diff !== 0) return diff < 0 ? -1 : 1;
  }
  return 0;
}

async function _checkForUpdate() {
  const current = chrome.runtime.getManifest().version;
  for (const url of _UPDATE_CHECK_URLS) {
    try {
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok) continue;
      const data = await res.json();
      const latest = String(data.version || '');
      if (latest && _cmpVersion(current, latest) < 0) {
        console.log(`[AutoToca Helper] atualizando ${current} -> ${latest} (reload)`);
        chrome.runtime.reload();
      }
      return; // app respondeu — não tenta o próximo host
    } catch (_) {
      // app provavelmente fechado; tenta o próximo host e desiste em silêncio
    }
  }
}

chrome.runtime.onStartup.addListener(_checkForUpdate);
try {
  chrome.alarms.create(_UPDATE_ALARM, { periodInMinutes: 30 });
  chrome.alarms.onAlarm.addListener(alarm => {
    if (alarm.name === _UPDATE_ALARM) _checkForUpdate();
  });
} catch (_) {
  // Ambiente sem chrome.alarms — o check em onStartup/onInstalled ainda cobre o caso comum.
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'start_reembolso_task') {
    const task = message.task || {};
    if (!_validLocalApiBase(task.apiBase) || !_validReembolsoUrl(task.targetUrl) || !task.taskId) {
      sendResponse({ ok: false, error: 'Dados inválidos para iniciar o e-Reembolso.' });
      return false;
    }
    chrome.storage.local.set({ [REEMBOLSO_TASK_KEY]: task })
      .then(() => chrome.tabs.create({ url: task.targetUrl }))
      .then(tab => sendResponse({ ok: true, taskId: task.taskId, tabId: tab.id }))
      .catch(async e => {
        await chrome.storage.local.remove(REEMBOLSO_TASK_KEY).catch(() => {});
        sendResponse({ ok: false, error: String(e) });
      });
    return true;
  }

  if (message.type === 'get_reembolso_task') {
    chrome.storage.local.get(REEMBOLSO_TASK_KEY)
      .then(stored => sendResponse({ ok: true, task: stored[REEMBOLSO_TASK_KEY] || null }))
      .catch(e => sendResponse({ ok: false, error: String(e) }));
    return true;
  }

  if (message.type === 'set_reembolso_checkpoint') {
    const taskId = message.taskId;
    chrome.storage.local.get(REEMBOLSO_TASK_KEY)
      .then(async stored => {
        const task = stored[REEMBOLSO_TASK_KEY] || null;
        if (!task || task.taskId !== taskId) {
          sendResponse({ ok: false, error: 'Tarefa ativa não encontrada.' });
          return;
        }
        const updated = { ...task, checkpoint: String(message.checkpoint || '') };
        await chrome.storage.local.set({ [REEMBOLSO_TASK_KEY]: updated });
        sendResponse({ ok: true, task: updated });
      })
      .catch(e => sendResponse({ ok: false, error: String(e) }));
    return true;
  }

  if (message.type === 'click_reembolso_control') {
    const tabId = sender.tab?.id;
    const controlId = String(message.controlId || '');
    if (!tabId || !/^_ctl0_MainContent_[A-Za-z0-9_]+$/.test(controlId)) {
      sendResponse({ ok: false, error: 'Controle externo inválido.' });
      return false;
    }
    chrome.scripting.executeScript({
      target: { tabId },
      world: 'MAIN',
      func: id => {
        const control = document.getElementById(id);
        if (!control) return { ok: false, error: `Controle ${id} não encontrado.` };
        const href = control.getAttribute('href') || '';
        const postback = href.match(/^javascript:__doPostBack\('([^']*)','([^']*)'\)$/i);
        if (postback && typeof window.__doPostBack === 'function') {
          window.__doPostBack(postback[1], postback[2]);
          return { ok: true, mode: 'postback' };
        }
        control.click();
        return { ok: true, mode: 'click' };
      },
      args: [controlId],
    })
      .then(results => sendResponse(results?.[0]?.result || { ok: false, error: 'Clique não confirmado.' }))
      .catch(e => sendResponse({ ok: false, error: String(e) }));
    return true;
  }

  if (message.type === 'load_reembolso_task') {
    const task = message.task || {};
    if (!_validLocalApiBase(task.apiBase) || !task.taskId) {
      sendResponse({ ok: false, error: 'Tarefa local inválida.' });
      return false;
    }
    fetch(`${task.apiBase}/api/autotoca/reembolsos/extension/tasks/${encodeURIComponent(task.taskId)}`, {
      cache: 'no-store',
    })
      .then(async response => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          if (response.status === 404) await chrome.storage.local.remove(REEMBOLSO_TASK_KEY);
          throw new Error(data.error || `HTTP ${response.status}`);
        }
        sendResponse({ ok: true, data });
      })
      .catch(e => sendResponse({ ok: false, error: String(e) }));
    return true;
  }

  if (message.type === 'update_reembolso_task') {
    const task = message.task || {};
    if (!_validLocalApiBase(task.apiBase) || !task.taskId) {
      sendResponse({ ok: false, error: 'Tarefa local inválida.' });
      return false;
    }
    fetch(`${task.apiBase}/api/autotoca/reembolsos/extension/tasks/${encodeURIComponent(task.taskId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(message.update || {}),
    })
      .then(async response => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        if (message.update?.status === 'done' || message.update?.status === 'error') {
          await chrome.storage.local.remove(REEMBOLSO_TASK_KEY);
        }
        sendResponse({ ok: true, data });
      })
      .catch(e => sendResponse({ ok: false, error: String(e) }));
    return true;
  }

  if (message.type === 'save_linkedin_profile') {
    _pendingProfile = message.data;
    chrome.storage.local.set({ 'autotoca-linkedin-pending': message.data })
      .then(() => sendResponse({ ok: true }))
      .catch(e => sendResponse({ ok: false, error: String(e) }));
    return true; // async
  }

  if (message.type === 'get_linkedin_profile') {
    if (_pendingProfile) {
      sendResponse({ ok: true, data: _pendingProfile });
      return false;
    }
    // Service worker foi reiniciado — recupera do storage
    chrome.storage.local.get('autotoca-linkedin-pending')
      .then(stored => {
        const data = stored['autotoca-linkedin-pending'] || null;
        if (data) _pendingProfile = data;
        sendResponse({ ok: !!data, data });
      })
      .catch(() => sendResponse({ ok: false, data: null }));
    return true; // async
  }

  if (message.type === 'clear_linkedin_profile') {
    _pendingProfile = null;
    chrome.storage.local.remove('autotoca-linkedin-pending')
      .then(() => sendResponse({ ok: true }))
      .catch(() => sendResponse({ ok: false }));
    return true; // async
  }
});
