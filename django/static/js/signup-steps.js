/* Presentation only: the canonical Django form validates the complete submission. */
(() => {
  'use strict';
  const form = document.querySelector('[data-signup-form]');
  if (!form) return;
  const steps = [...form.querySelectorAll('[data-signup-step]')];
  const indicators = [...document.querySelectorAll('[data-signup-indicator]')];
  const previous = form.querySelector('[data-signup-back]');
  const next = form.querySelector('[data-signup-next]');
  const submit = form.querySelector('[data-signup-submit]');
  const status = document.querySelector('[data-signup-status]');
  let current = 0;
  function show(index, focus = true) {
    current = index;
    steps.forEach((step, i) => { step.hidden = i !== index; });
    indicators.forEach((item, i) => {
      if (i === index) item.setAttribute('aria-current', 'step');
      else item.removeAttribute('aria-current');
    });
    previous.hidden = index === 0;
    next.hidden = index === steps.length - 1;
    submit.hidden = index !== steps.length - 1;
    status.textContent = `Etapa ${index + 1} de ${steps.length}`;
    if (focus) steps[index].querySelector('legend').focus();
  }
  function invalid(step) {
    return [...step.querySelectorAll('input, select, textarea')].find(field => !field.checkValidity());
  }
  next.addEventListener('click', () => {
    const field = invalid(steps[current]);
    if (field) { field.reportValidity(); return; }
    show(current + 1);
  });
  previous.addEventListener('click', () => show(current - 1));
  form.addEventListener('submit', event => {
    if (current < steps.length - 1) {
      event.preventDefault();
      const field = invalid(steps[current]);
      if (field) field.reportValidity(); else show(current + 1);
      return;
    }
    for (const [index, step] of steps.entries()) {
      const field = invalid(step);
      if (field) { event.preventDefault(); show(index); field.reportValidity(); return; }
    }
  });
  document.querySelector('[data-signup-progress]').hidden = false;
  form.noValidate = true;
  const errorStep = steps.findIndex(step => step.querySelector('.field-error'));
  show(errorStep < 0 ? 0 : errorStep, false);
})();
