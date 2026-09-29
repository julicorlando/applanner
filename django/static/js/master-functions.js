const search = document.getElementById('master-function-search');

if (search) {
  const groups = [...document.querySelectorAll('[data-master-group]')];
  const categories = document.getElementById('master-category-grid');
  const clear = document.getElementById('master-search-clear');
  const status = document.getElementById('master-search-status');
  const empty = document.getElementById('master-search-empty');
  const normalize = (value) => value.toLocaleLowerCase('pt-BR').normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim();

  function filterFunctions() {
    const query = normalize(search.value);
    let found = 0;
    for (const group of groups) {
      const groupName = normalize(group.querySelector('h3').textContent);
      let inGroup = 0;
      for (const card of group.querySelectorAll('[data-master-function]')) {
        const match = !query || groupName.includes(query) || normalize(card.textContent).includes(query);
        card.hidden = !match;
        if (match) inGroup += 1;
      }
      group.hidden = inGroup === 0;
      found += inGroup;
    }
    categories.hidden = Boolean(query);
    clear.hidden = !query;
    empty.hidden = !query || found > 0;
    status.textContent = query ? `${found} ${found === 1 ? 'função encontrada' : 'funções encontradas'}` : '';
  }

  search.addEventListener('input', filterFunctions);
  search.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      search.value = '';
      filterFunctions();
    }
  });
  clear.addEventListener('click', () => {
    search.value = '';
    filterFunctions();
    search.focus();
  });
}
