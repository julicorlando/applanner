/* Reception desktop app: keeps the offline mode ready and asks for uploads when the internet is back.
   Reads only the non-PHI pending counter of the encrypted vault; never the vault content. */
(() => {
  'use strict';
  const box = document.getElementById('rp-offline');
  if (!box || !window.isSecureContext || !('serviceWorker' in navigator) || !globalThis.ClinicVault) return;
  const shell = box.dataset.shell, title = box.querySelector('[data-offline-title]'), text = box.querySelector('[data-offline-text]'),
    action = box.querySelector('[data-offline-action]');
  let sealed = null;
  async function prepare() {
    // Caches only the public offline page and its scripts, so the app opens without internet.
    try {
      const registration = await navigator.serviceWorker.ready;
      if (!registration.active) return;
      await new Promise(resolve => {
        const channel = new MessageChannel(), timer = setTimeout(resolve, 20000);
        channel.port1.onmessage = () => { clearTimeout(timer); resolve(); };
        registration.active.postMessage({type:'CLINICAL_PREPARE'}, [channel.port2]);
      });
    } catch { /* The online panel keeps working. */ }
  }
  async function refresh() {
    try { sealed = await ClinicVault.load(); } catch { sealed = null; }
    box.classList.toggle('is-pending', Boolean(sealed?.pending));
    box.classList.toggle('is-offline', !navigator.onLine);
    if (!sealed) {
      title.textContent = 'Modo offline não ativado neste computador';
      text.textContent = 'Ative enquanto estiver conectado: a recepção continua consultando pacientes e a agenda e registrando chegadas, cadastros e recebimentos em dinheiro sem internet. Tudo é enviado quando a conexão voltar.';
      action.textContent = 'Ativar modo offline';
    } else if (sealed.pending) {
      title.textContent = `${sealed.pending} lançamento(s) feito(s) sem internet aguardando envio`;
      text.textContent = navigator.onLine ? 'A internet está disponível. Abra o modo offline e desbloqueie o cofre para enviar agora.' : 'Sem internet. Os lançamentos estão guardados com segurança neste computador.';
      action.textContent = navigator.onLine ? 'Enviar agora' : 'Abrir modo offline';
    } else {
      const when = sealed.saved_at ? new Date(sealed.saved_at).toLocaleString('pt-BR') : '';
      title.textContent = 'Modo offline pronto neste computador';
      text.textContent = `Cópia local criptografada${when ? ' atualizada em ' + when : ''}. Se a internet cair, o app abre o modo offline sozinho.`;
      action.textContent = 'Abrir e atualizar cópia';
    }
    box.hidden = false;
  }
  addEventListener('online', refresh);
  addEventListener('offline', () => { refresh(); if (sealed) setTimeout(() => { if (!navigator.onLine) location.assign(shell); }, 3000); });
  refresh().then(prepare);
})();
