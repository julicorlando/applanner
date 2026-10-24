(() => {
  const dialog = document.getElementById('trial-subscription-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  const previousFocus = document.activeElement;
  document.getElementById('trial-subscription-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    if (previousFocus && previousFocus.isConnected) previousFocus.focus();
  });
  dialog.showModal();
})();
