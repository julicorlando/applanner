(() => {
  'use strict';
  const box = document.querySelector('[data-push-preferences]');
  if (!box) return;
  const status = box.querySelector('[data-push-feedback]');
  const enable = box.querySelector('[data-push-enable]');
  const disable = box.querySelector('[data-push-disable]');
  const url = box.dataset.pushUrl;
  let config = null;
  const supported = () => window.isSecureContext && 'Notification' in window &&
    'PushManager' in window && 'serviceWorker' in navigator;
  async function responseJSON(response) {
    let data;
    try { data = await response.json(); } catch { throw Error('Não foi possível comunicar com o servidor. Entre novamente e tente outra vez.'); }
    if (!response.ok) throw Error(data.detail || 'Não foi possível salvar a preferência.');
    return data;
  }
  const load = async () => {
    config = await responseJSON(await fetch(url, {cache: 'no-store', credentials: 'same-origin'}));
    return config;
  };
  async function post(data) {
    return responseJSON(await fetch(url, {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json',
        'X-CSRFToken': document.querySelector('#push-csrf input').value},
      body: JSON.stringify(data)}));
  }
  function key(value) {
    const raw = atob(value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4));
    return Uint8Array.from(raw, character => character.charCodeAt(0));
  }
  async function registration() {
    await navigator.serviceWorker.register('/imagens/app-worker.js', {scope: '/'});
    return Promise.race([navigator.serviceWorker.ready,
      new Promise((_, reject) => setTimeout(() => reject(Error('O aplicativo ainda está atualizando. Reabra e tente novamente.')), 15000))]);
  }
  function busy(value) { enable.disabled = value; disable.disabled = value; }
  enable.addEventListener('click', async () => {
    try {
      if (!supported()) throw Error('Push não suportado neste navegador. No iPhone, adicione à Tela de Início e abra o aplicativo instalado.');
      if (config && !config.enabled) throw Error('O Master precisa ativar Web Push em Push e SMS antes de habilitar este dispositivo.');
      // Safari requires this call directly inside the click gesture, before any network await.
      const permission = Notification.requestPermission();
      busy(true);
      if (await permission !== 'granted') throw Error('Permissão não concedida. Habilite as notificações nas configurações do navegador ou do aplicativo.');
      const settings = config || await load();
      if (!settings.enabled) throw Error('O Master ainda precisa ativar Web Push na plataforma.');
      const worker = await registration();
      const subscription = await worker.pushManager.getSubscription() ||
        await worker.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: key(settings.publicKey)});
      status.textContent = (await post({subscription: subscription.toJSON()})).detail;
    } catch (error) {
      status.textContent = error.message || 'Não foi possível ativar neste dispositivo.';
    } finally { busy(false); }
  });
  disable.addEventListener('click', async () => {
    busy(true);
    try {
      if (!('serviceWorker' in navigator)) throw Error('Este navegador não oferece notificações do aplicativo.');
      const worker = await navigator.serviceWorker.getRegistration('/');
      const subscription = worker ? await worker.pushManager.getSubscription() : null;
      if (subscription) {
        await post({action: 'remove', endpoint: subscription.endpoint});
        await subscription.unsubscribe();
      }
      status.textContent = 'Notificações desativadas neste dispositivo.';
    } catch (error) {
      status.textContent = error.message || 'Não foi possível desativar. Tente novamente.';
    } finally { busy(false); }
  });
  if (!supported()) {
    status.textContent = 'No iPhone, instale na Tela de Início e abra o aplicativo instalado para habilitar notificações.';
  } else {
    load().then(settings => {
      status.textContent = !settings.enabled ? 'Web Push ainda não foi habilitado pela plataforma.' :
        Notification.permission === 'denied' ? 'As notificações estão bloqueadas nas configurações deste dispositivo.' :
        'Use Ativar notificações para cadastrar este dispositivo. Cada computador ou celular precisa de sua própria autorização.';
    }).catch(error => { status.textContent = error.message; });
  }
})();
