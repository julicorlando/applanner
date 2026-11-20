(() => {
  const dialog = document.getElementById('clinic-room-dialog');
  if (!dialog) return;
  document.querySelectorAll('[data-room-open]').forEach(button => button.addEventListener('click', () => dialog.showModal()));
  dialog.querySelector('[data-room-close]').addEventListener('click', () => dialog.close());
  document.querySelectorAll('[data-patient-call]').forEach(form => form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    const status = form.querySelector('[data-call-status]');
    button.disabled = true;
    status.textContent = 'Chamando…';
    try {
      const response = await fetch(form.action, {method: 'POST', body: new FormData(form), credentials: 'same-origin', headers: {'Accept': 'application/json'}});
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Não foi possível confirmar a chamada. Confira a sala, conexão e permissões.');
      const data = await response.json();
      status.textContent = `Paciente chamado na TV · ${data.room}`;
      form.elements.request_id.value = crypto.randomUUID();
    } catch (error) {
      status.textContent = error.message || 'Falha na chamada. Tente novamente.';
    } finally { button.disabled = false; }
  }));
  if (dialog.dataset.autoOpen === 'true') dialog.showModal();
})();
