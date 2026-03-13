(function () {
  const PING_EVENT = 'autotoca-extension-ping';
  const PONG_EVENT = 'autotoca-extension-pong';

  function sendPong() {
    window.dispatchEvent(new CustomEvent(PONG_EVENT, {
      detail: {
        ok: true,
        extension: 'AutoToca Helper',
        version: '0.1.0',
        href: window.location.href,
        timestamp: Date.now(),
      }
    }));
  }

  window.addEventListener(PING_EVENT, sendPong);
  sendPong();
})();
