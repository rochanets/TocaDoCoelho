// Cache em memória — persiste enquanto o service worker estiver vivo
let _pendingProfile = null;

chrome.runtime.onInstalled.addListener(() => {
  console.log('[AutoToca Helper] instalada com sucesso');
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
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
