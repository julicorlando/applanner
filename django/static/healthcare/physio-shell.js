(() => {
  const sidebar = document.getElementById('pa-sidebar');
  const toggle = document.getElementById('pa-menu-toggle');
  if (!sidebar || !toggle) return;
  const mobile = () => window.matchMedia ? window.matchMedia('(max-width:760px)').matches : true;
  const setOpen = (open, persist = false) => {
    sidebar.classList.toggle('pa-open', open);
    document.body.classList.toggle('pa-menu-collapsed', !open && !mobile());
    sidebar.inert = !open;
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Ocultar menu' : 'Mostrar menu');
    if (persist && !mobile()) { try { localStorage.setItem('applanner.clinical.menu.collapsed', String(!open)); } catch {} }
  };
  const initial = () => { let collapsed = false; try { collapsed = localStorage.getItem('applanner.clinical.menu.collapsed') === 'true'; } catch {} setOpen(!mobile() && !collapsed); };
  const close = () => { setOpen(false, true); toggle.focus(); };
  initial();
  window.addEventListener('resize', initial);
  toggle.addEventListener('click', () => {
    const open = toggle.getAttribute('aria-expanded') !== 'true';
    setOpen(open, true);
    if (open && mobile()) sidebar.querySelector('a[href],button')?.focus();
  });
  document.getElementById('pa-menu-close')?.addEventListener('click', close);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
  document.addEventListener('click', event => { if (mobile() && !sidebar.contains(event.target) && !toggle.contains(event.target)) close(); });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Tab' || !mobile() || !sidebar.classList.contains('pa-open')) return;
    const items = [...sidebar.querySelectorAll('a[href],button')];
    if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1).focus(); }
    else if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); toggle.focus(); }
  });
})();
