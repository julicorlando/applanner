(() => {
  const form = document.getElementById('arena-booking');
  if (!form) return;
  const court = document.getElementById('arena-court');
  const date = document.getElementById('arena-date');
  const duration = document.getElementById('arena-duration');
  const slot = document.getElementById('arena-slot');
  const feedback = document.getElementById('arena-feedback');
  const button = form.querySelector('button[type="submit"]');
  const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;
  const slug = form.dataset.publicSlug;
  const today = new Date();
  date.min = [today.getFullYear(), String(today.getMonth() + 1).padStart(2, '0'), String(today.getDate()).padStart(2, '0')].join('-');
  const picker = createBookingSlotPicker({
    container: document.getElementById('arena-slots'), input: slot,
    status: document.getElementById('arena-slot-status'),
  });

  function updateDuration() {
    duration.replaceChildren();
    const selected = court.selectedOptions[0];
    if (selected?.dataset.min) {
      const min = Number(selected.dataset.min), max = Number(selected.dataset.max);
      for (let minutes = min; minutes <= max; minutes += 30) {
        const option = new Option(`${minutes} minutos`, String(minutes));
        duration.add(option);
      }
    }
    loadSlots();
  }
  function loadSlots() {
    if (!court.value || !date.value || !duration.value) {
      picker.reset('Escolha quadra e data para ver os horários.');
      return;
    }
    const params = new URLSearchParams({court_id: court.value, date: date.value, duration: duration.value});
    picker.load(`/api/public/${encodeURIComponent(slug)}/arena/slots/?${params}`);
  }
  court.addEventListener('change', updateDuration);
  date.addEventListener('change', loadSlots);
  duration.addEventListener('change', loadSlots);
  updateDuration();
  document.querySelectorAll('[data-select-court]').forEach(link => {
    link.addEventListener('click', () => {
      court.value = link.dataset.selectCourt;
      updateDuration();
    });
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!slot.value) { feedback.textContent = 'Escolha um horário disponível.'; return; }
    const payload = {
      court_id: court.value, starts_at: slot.value, duration: duration.value,
      name: document.getElementById('arena-name').value.trim(),
      phone: document.getElementById('arena-phone').value.trim(),
      email: document.getElementById('arena-email').value.trim(),
      notes: document.getElementById('arena-notes').value.trim(),
      payment: form.querySelector('[name="arena-payment"]:checked')?.value || 'onsite',
    };
    if (!payload.phone && !payload.email) { feedback.textContent = 'Informe telefone ou e-mail.'; return; }
    button.disabled = true;
    feedback.textContent = 'Confirmando reserva...';
    try {
      const response = await fetch(`/api/public/${encodeURIComponent(slug)}/arena/book/`, {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) {
        feedback.textContent = result.detail || 'Não foi possível reservar.';
        loadSlots();
        button.disabled = false;
        return;
      }
      feedback.replaceChildren(document.createTextNode(`${result.detail} `));
      const when = new Intl.DateTimeFormat('pt-BR', {timeZone: result.timezone, dateStyle: 'full', timeStyle: 'short'}).format(new Date(result.starts_at));
      const until = new Intl.DateTimeFormat('pt-BR', {timeZone: result.timezone, hour: '2-digit', minute: '2-digit'}).format(new Date(result.ends_at));
      const total = new Intl.NumberFormat('pt-BR', {style: 'currency', currency: 'BRL'}).format(Number(result.total));
      for (const text of [result.court, `${when} até ${until}`, `Valor da reserva: ${total}`]) {
        const line = document.createElement('p');
        line.textContent = text;
        feedback.appendChild(line);
      }
      const link = document.createElement('a');
      link.href = result.manage_url;
      link.textContent = 'Ver minha reserva';
      feedback.appendChild(link);
    } catch {
      feedback.textContent = 'Não foi possível confirmar a reserva. Consulte suas reservas antes de tentar novamente.';
      loadSlots();
      button.disabled = false;
    }
  });
})();
