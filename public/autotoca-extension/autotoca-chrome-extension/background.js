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
});

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
