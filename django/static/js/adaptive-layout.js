(() => {
  'use strict';
  // Keep every value and action. Complex report tables retain their own scroll.
  for (const table of document.querySelectorAll('.portal-table')) {
    const headings = Array.from(table.querySelectorAll('thead tr'));
    const rows = Array.from(table.querySelectorAll('tbody tr'));
    if (headings.length !== 1 || !rows.length) continue;
    const headers = Array.from(headings[0].cells);
    if (!headers.length || headers.some(cell => cell.colSpan !== 1 || cell.rowSpan !== 1)) continue;
    if (rows.some(row => row.cells.length !== headers.length || Array.from(row.cells).some(cell => cell.colSpan !== 1 || cell.rowSpan !== 1))) continue;
    table.classList.add('mobile-cards');
    table.setAttribute('role', 'table');
    table.querySelector('thead').setAttribute('role', 'rowgroup');
    table.querySelector('tbody').setAttribute('role', 'rowgroup');
    headings[0].setAttribute('role', 'row');
    headers.forEach(cell => cell.setAttribute('role', 'columnheader'));
    for (const row of rows) {
      row.setAttribute('role', 'row');
      Array.from(row.cells).forEach((cell, index) => {
        cell.dataset.mobileLabel = headers[index].textContent.trim() || 'Ações';
        cell.setAttribute('role', 'cell');
      });
    }
  }
})();
