(() => {
  const sidebar = document.getElementById('pa-sidebar');
  const toggle = document.getElementById('pa-menu-toggle');
  if (!sidebar || !toggle) return;
  const close = () => { sidebar.classList.remove('pa-open'); toggle.setAttribute('aria-expanded', 'false'); };
  toggle.addEventListener('click', () => { toggle.setAttribute('aria-expanded', String(sidebar.classList.toggle('pa-open'))); });
  document.getElementById('pa-menu-close')?.addEventListener('click', close);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
  document.addEventListener('click', event => { if (!sidebar.contains(event.target) && !toggle.contains(event.target)) close(); });
})();
