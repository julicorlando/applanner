/* Updates wait for a customer action; never interrupt an appointment form. */
(() => {
  if (!('serviceWorker' in navigator) || !window.isSecureContext) return;
  const script = document.querySelector('script[data-app-worker-url]');
  if (!script) return;
  let reloading = false, requestedUpdate = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (requestedUpdate && !reloading) { reloading = true; window.location.reload(); }
  });
  navigator.serviceWorker.register(script.dataset.appWorkerUrl, {scope:'/', updateViaCache:'none'}).then(registration => {
    function offerUpdate() {
      if (!registration.waiting || document.querySelector('[data-app-update]')) return;
      const panel = document.createElement('aside');
      panel.className = 'app-update-notice'; panel.dataset.appUpdate = ''; panel.setAttribute('aria-label','Atualização do ApPlanner');
      const text = document.createElement('p'); text.textContent = 'Nova versão disponível. Salve o que estiver fazendo antes de atualizar.';
      const update = document.createElement('button'); update.type = 'button'; update.className = 'button primary'; update.textContent = 'Atualizar agora';
      update.addEventListener('click', () => { if (registration.waiting) { requestedUpdate = true; registration.waiting.postMessage({type:'APPLANNER_ACTIVATE_UPDATE'}); } });
      const later = document.createElement('button'); later.type = 'button'; later.className = 'button'; later.textContent = 'Depois'; later.addEventListener('click', () => panel.remove());
      panel.append(text, update, later); document.body.append(panel);
    }
    offerUpdate();
    registration.addEventListener('updatefound', () => {
      const worker = registration.installing;
      worker?.addEventListener('statechange', () => { if (worker.state === 'installed' && navigator.serviceWorker.controller) offerUpdate(); });
    });
  }).catch(() => { /* The online system remains available when installation is unavailable. */ });
})();
