/* Filter only server-authorized navigation. No account or customer data is cached. */
(function () {
  'use strict';
  const sidebar = document.getElementById('workspace-sidebar');
  const input = document.getElementById('workspace-search');
  if (!sidebar || !input) return;
  const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  const groups = [...sidebar.querySelectorAll('.workspace-group')];
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
