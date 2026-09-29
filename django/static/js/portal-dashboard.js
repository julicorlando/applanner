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
