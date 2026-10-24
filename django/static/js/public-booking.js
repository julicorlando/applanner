/* Progressive enhancement: the complete form remains visible if enhancement cannot run. */
(() => {
  const form = document.getElementById('public-booking');
  if (!form) return;
  const byId = id => document.getElementById('booking-' + id);
  const service = byId('service'), professional = byId('professional'), date = byId('date'), slot = byId('slot');
  const labels = ['Serviço', 'Profissional', 'Data e horário', 'Seus dados', 'Revisão'];
  const panels = labels.map((label, index) => {
    const panel = document.createElement('section');
    panel.className = 'booking-step'; panel.dataset.step = index;
    const title = document.createElement('h3'); title.textContent = label; title.tabIndex = -1;
    panel.append(title); return panel;
  });
  const move = (index, element) => { if (element) panels[index].append(element); };
  move(0, byId('unit').closest('.form-field'));
  move(0, document.getElementById('servicos'));
  move(0, service.closest('.form-field'));
  move(1, professional.closest('.form-field'));
  move(2, date.closest('.form-field'));
  move(2, slot.closest('.booking-times'));
  ['name', 'phone', 'email', 'notes', 'plate', 'vehicle-model'].forEach(id => move(3, byId(id)?.closest('.form-field')));
  move(3, document.getElementById('customer-identity-hint'));
  move(3, byId('waitlist'));
  const review = document.createElement('p'); review.className = 'booking-review-contact';
  move(4, review);
  move(4, form.querySelector('fieldset'));
  move(4, byId('product-selection'));
  const submit = form.querySelector('button[type=submit]');
  move(4, submit.closest('.form-actions'));
  // Availability configuration errors remain visible above the wizard.
  form.querySelectorAll('.portal-module-grid').forEach(grid => { if (!grid.children.length) grid.remove(); });
  const steps = document.createElement('nav'); steps.className = 'booking-progress'; steps.setAttribute('aria-label', 'Etapas do agendamento');
  const buttons = labels.map((label, index) => {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = `${index + 1}. ${label}`;
    button.addEventListener('click', () => { if (index < current) show(index); }); steps.append(button); return button;
  });
  const layout = document.createElement('div'); layout.className = 'booking-layout';
  const content = document.createElement('div'); panels.forEach(panel => content.append(panel));
  const summary = document.createElement('aside'); summary.className = 'booking-summary'; summary.setAttribute('aria-label', 'Resumo da reserva');
  const heading = document.createElement('h3'); heading.textContent = 'Sua reserva'; summary.append(heading);
  const rows = {};
  for (const label of ['Unidade', 'Serviço', 'Profissional', 'Data e horário', 'Duração', 'Valor do serviço']) {
    const row = document.createElement('p'), title = document.createElement('small'), value = document.createElement('strong');
    title.textContent = label; row.append(title, value); summary.append(row); rows[label] = value;
  }
  const note = document.createElement('small'); note.textContent = 'Confira os dados antes de confirmar. Produtos reservados são pagos separadamente na unidade.'; summary.append(note);
  layout.append(content, summary);
  const actions = document.createElement('div'); actions.className = 'booking-navigation';
  const back = document.createElement('button'); back.type = 'button'; back.className = 'button'; back.textContent = 'Voltar';
  const next = document.createElement('button'); next.type = 'button'; next.className = 'button primary'; next.textContent = 'Continuar';
  const hint = document.createElement('span'); hint.setAttribute('role', 'status');
  actions.append(hint, back, next);
  const feedback = byId('feedback');
  form.insertBefore(steps, form.firstChild); form.insertBefore(layout, feedback); form.insertBefore(actions, feedback);
  form.classList.add('booking-enhanced');
  let current = 0, chosen = null, available = null, confirmed = false;
  function update() {
    const option = service.selectedOptions[0];
    review.textContent = `Contato: ${byId('name').value || '—'} · ${byId('phone').value || '—'}${byId('email').value ? ' · ' + byId('email').value : ''}`;
    rows.Unidade.textContent = byId('unit').selectedOptions[0]?.textContent || 'Não selecionada';
    rows.Serviço.textContent = option?.dataset.name || 'Escolha um serviço';
    rows.Profissional.textContent = chosen?.professional_name || professional.selectedOptions[0]?.textContent || 'Qualquer disponível';
    const dateText = date.value ? new Intl.DateTimeFormat('pt-BR', {dateStyle:'medium'}).format(new Date(date.value + 'T12:00:00')) : 'Escolha uma data';
    rows['Data e horário'].textContent = dateText + (chosen ? ' · ' + chosen.label : '');
    rows.Duração.textContent = option?.dataset.duration ? option.dataset.duration + ' min' : '—';
    rows['Valor do serviço'].textContent = option?.dataset.price ? new Intl.NumberFormat('pt-BR', {style:'currency', currency:'BRL'}).format(Number(option.dataset.price)) : '—';
    form.querySelectorAll('[data-select-service]').forEach(card => {
      const selected = card.dataset.selectService === service.value;
      card.classList.toggle('is-selected', selected); card.setAttribute('aria-pressed', String(selected));
    });
    next.hidden = current === 4 || confirmed;
    next.disabled = current === 3 && !slot.value;
    next.textContent = current === 2 && available === 0 && byId('waitlist') ? 'Informar contato para lista de espera' : current === 3 ? 'Revisar agendamento' : 'Continuar';
    hint.textContent = `Etapa ${current + 1} de 5`;
  }
  function show(index, focus = true) {
    current = index;
    panels.forEach((panel, i) => { panel.hidden = i !== index; });
    buttons.forEach((button, i) => { button.disabled = i > index; if (i === index) button.setAttribute('aria-current', 'step'); else button.removeAttribute('aria-current'); });
    back.hidden = index === 0 || confirmed;
    update();
    if (focus) { panels[index].querySelector('h3').focus({preventScroll:true}); document.getElementById('agendar').scrollIntoView({behavior:'smooth',block:'start'}); }
  }
  function validate(panel) {
    for (const field of panel.querySelectorAll('input,select,textarea')) {
      if (!field.checkValidity()) { field.reportValidity(); return false; }
    }
    return true;
  }
  next.addEventListener('click', () => {
    if (!validate(panels[current])) return;
    if (current === 2 && !slot.value && !(available === 0 && byId('waitlist'))) {
      hint.textContent = 'Selecione um horário disponível para continuar.'; return;
    }
    show(Math.min(4, current + 1));
  });
  back.addEventListener('click', () => show(Math.max(0, current - 1)));
  form.addEventListener('change', update);
  form.addEventListener('input', update);
  form.addEventListener('booking:service', () => { if (service.value) show(1); });
  document.querySelectorAll('a[href="#servicos"]').forEach(link => link.addEventListener('click', () => {
    if (confirmed) { window.location.reload(); return; }
    show(0, false);
  }));
  form.addEventListener('booking:slot', event => { chosen = event.detail.selected ? event.detail.chosen : null; update(); });
  form.addEventListener('booking:availability', event => { available = event.detail.count; update(); });
  form.addEventListener('invalid', event => {
    const panel = event.target.closest('.booking-step'); if (panel) show(Number(panel.dataset.step), false);
  }, true);
  // Handle implicit Enter before native validation can focus fields in later steps.
  form.addEventListener('keydown', event => {
    if (event.key === 'Enter' && current < 4 && !['BUTTON', 'TEXTAREA'].includes(event.target.tagName)) {
      event.preventDefault(); next.click();
    }
  }, true);
  // Only the final review may submit.
  form.addEventListener('submit', event => {
    if (current !== 4 || confirmed) { event.preventDefault(); event.stopImmediatePropagation(); if (!confirmed) next.click(); }
  }, true);
  form.addEventListener('booking:confirmed', () => {
    confirmed = true; layout.hidden = true; steps.hidden = true; actions.hidden = true;
  });
  show(0, false);
})();
