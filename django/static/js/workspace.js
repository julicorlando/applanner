/* Filter only server-authorized navigation. No account or customer data is cached. */
(function () {
  'use strict';
  const sidebar = document.getElementById('workspace-sidebar');
  const input = document.getElementById('workspace-search');
  if (!sidebar || !input) return;
  const triggers = [...document.querySelectorAll('[data-sidebar-toggle], [data-mobile-menu]')];
  const backdrop = document.querySelector('.workspace-backdrop');
  let opener;
  const setOpen = open => {
    document.body.classList.toggle('workspace-open', open);
    backdrop.hidden = !open;
    triggers.forEach(button => { button.setAttribute('aria-expanded', String(open)); button.setAttribute('aria-controls', sidebar.id); });
    if (open) input.focus(); else if (opener) opener.focus();
  };
  triggers.forEach(button => button.addEventListener('click', () => { opener = button; setOpen(!document.body.classList.contains('workspace-open')); }));
  document.querySelectorAll('[data-sidebar-close]').forEach(button => button.addEventListener('click', () => setOpen(false)));
  document.addEventListener('keydown', event => {
    if (!document.body.classList.contains('workspace-open')) return;
    if (event.key === 'Escape') setOpen(false);
    if (event.key === 'Tab') {
      const elements = [...sidebar.querySelectorAll('a,button,input,summary')].filter(item => item.getClientRects().length);
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  const groups = [...sidebar.querySelectorAll('.workspace-group')];
  groups.forEach(group => { if (group.querySelectorAll('a').length > 10 && !group.querySelector('[aria-current]')) group.open = false; });
  const initial = groups.map(group => group.open);
  input.addEventListener('input', () => {
    const term = normalize(input.value);
    let total = 0;
    groups.forEach((group, index) => {
      let visible = 0;
      const title = normalize(group.querySelector('summary').textContent);
      group.querySelectorAll('[data-workspace-link]').forEach(link => {
        link.hidden = Boolean(term) && !normalize(link.textContent).includes(term) && !title.includes(term);
        if (!link.hidden) visible++;
      });
      group.hidden = !visible;
      group.open = term ? Boolean(visible) : initial[index];
      total += visible;
    });
    sidebar.querySelector('.workspace-no-results').hidden = Boolean(total);
  });
  input.addEventListener('keydown', event => {
    if (event.key === 'Escape') { input.value = ''; input.dispatchEvent(new Event('input')); }
  });
})();
