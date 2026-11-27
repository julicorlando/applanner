(() => {
  const sections = [...document.querySelectorAll('[data-live-agenda]')];
  if (!sections.length) return;
  const status = document.getElementById('agenda-live-status');
  let fetching = false;
  async function refresh() {
    if (fetching || document.hidden) return;
    fetching = true;
    try {
      const response = await fetch(window.location.href, {
        credentials: 'same-origin', cache: 'no-store', headers: {'X-Requested-With': 'XMLHttpRequest'},
      });
      if (!response.ok || response.redirected) throw new Error('Consulta indisponível');
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      const updates = sections.map(current => page.querySelector(`[data-live-agenda="${current.dataset.liveAgenda}"]`));
      if (updates.some(next => !next)) throw new Error('Agenda indisponível');
      sections.forEach((current, index) => {
        if (current.innerHTML !== updates[index].innerHTML) current.replaceChildren(...updates[index].childNodes);
      });
      if (status) status.textContent = 'Agenda sincronizada automaticamente.';
    } catch {
      if (status) status.textContent = 'Não foi possível sincronizar agora. Tentaremos novamente em instantes.';
    } finally {
      fetching = false;
    }
  }
  setInterval(refresh, 15000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
})();
