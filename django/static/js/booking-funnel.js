(() => {
  const config = document.getElementById('booking-funnel-tracking');
  const form = document.getElementById('public-booking') || document.getElementById('arena-booking');
  if (!config || !form) return;
  const sent = new Set();
  const send = stage => {
    if (sent.has(stage)) return;
    sent.add(stage);
    fetch(config.dataset.url, {method:'POST', credentials:'same-origin', keepalive:true,
      headers:{'Content-Type':'application/json','X-CSRFToken':form.querySelector('[name=csrfmiddlewaretoken]')?.value || ''},
      body:JSON.stringify({token:config.dataset.token,stage})}).catch(() => {});
  };
  form.addEventListener('booking:slot', event => { if (event.detail.selected) { send('resource'); send('slot'); } });
  form.addEventListener('click', event => { if (event.target.closest('.booking-slot[aria-pressed="true"]')) { send('resource'); send('slot'); } });
  document.querySelectorAll('[data-select-court]').forEach(link => link.addEventListener('click', () => send('resource')));
  form.addEventListener('change', event => {
    if (['booking-service','arena-court'].includes(event.target.id) && event.target.value) send('resource');
    if (['booking-slot','arena-slot'].includes(event.target.id) && event.target.value) { send('resource'); send('slot'); }
  });
})();
