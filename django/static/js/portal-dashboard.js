(() => {
  const dashboard = document.querySelector('.operation-dashboard');
  const toggle = document.getElementById('portal-view-toggle');
  if (dashboard && toggle) {
    const key = 'applanner.portal.simplified-view';
    let saved = null;
    try { saved = window.localStorage.getItem(key); } catch (_) { /* Storage may be disabled. */ }
    const isMobile = window.matchMedia('(max-width: 700px)').matches;
    const setView = (simplified, persist = true) => {
      dashboard.classList.toggle('is-simplified', simplified);
      toggle.setAttribute('aria-pressed', String(simplified));
      toggle.innerHTML = simplified ? '<span aria-hidden="true">◑</span> Visão completa' : '<span aria-hidden="true">◐</span> Visão simplificada';
      if (persist) {
        try { window.localStorage.setItem(key, simplified ? '1' : '0'); } catch (_) { /* Keep the current view usable. */ }
      }
    };
    setView(saved === null ? isMobile : saved === '1', false);
    toggle.addEventListener('click', () => setView(!dashboard.classList.contains('is-simplified')));
  }
})();

document.addEventListener('click', async (event) => {
  const button = event.target.closest('.operation-copy');
  if (!button) return;
  const url = button.dataset.copyUrl;
  if (!url) return;
  try {
    await navigator.clipboard.writeText(url);
    const original = button.textContent;
    button.textContent = 'Copiado!';
    window.setTimeout(() => { button.textContent = original; }, 2200);
  } catch (_) {
    button.textContent = 'Abra o link para compartilhar';
  }
});
