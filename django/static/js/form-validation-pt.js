// Localize constraints before the browser opens its validation bubble.
(() => {
  const messages = new WeakMap();
  function localize(field) {
    if (!field.validity || !field.setCustomValidity || !field.willValidate) return;
    if (messages.has(field)) {
      if (field.validationMessage === messages.get(field)) field.setCustomValidity('');
      messages.delete(field);
    }
    const validity = field.validity;
    if (validity.valid || validity.customError) return;
    let message = 'Confira o valor informado neste campo.';
    if (validity.valueMissing) message = field.tagName === 'SELECT' ? 'Selecione uma opção.' : 'Preencha este campo.';
    else if (validity.typeMismatch) message = field.type === 'email' ? 'Informe um e-mail válido.' : 'Informe um endereço válido.';
    else if (validity.tooShort) message = `Use pelo menos ${field.minLength} caracteres.`;
    else if (validity.tooLong) message = `Use no máximo ${field.maxLength} caracteres.`;
    else if (validity.rangeUnderflow) message = `Informe um valor igual ou maior que ${field.min}.`;
    else if (validity.rangeOverflow) message = `Informe um valor igual ou menor que ${field.max}.`;
    else if (validity.badInput || validity.stepMismatch) message = 'Informe um número válido dentro do intervalo permitido.';
    else if (validity.patternMismatch) message = field.title || 'Confira o formato solicitado neste campo.';
    field.setCustomValidity(message);
    messages.set(field, message);
  }
  function localizeForm(form) {
    if (form && !form.noValidate) Array.from(form.elements).forEach(localize);
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('button, input[type="submit"], input[type="image"]');
    if (button && ['submit', 'image'].includes(button.type) && !button.formNoValidate) localizeForm(button.form);
  }, true);
  document.addEventListener('keydown', event => {
    if (event.key === 'Enter' && event.target.tagName !== 'TEXTAREA') localizeForm(event.target.form);
  }, true);
  document.addEventListener('invalid', event => {
    const field = event.target;
    localize(field);
    const feedback = field.form && field.form.querySelector('#booking-feedback');
    if (feedback) {
      const label = field.labels && field.labels[0];
      feedback.textContent = `${label ? label.textContent.trim() + ': ' : ''}${field.validationMessage}`;
    }
  }, true);
  ['input', 'change'].forEach(name => document.addEventListener(name, event => {
    const field = event.target;
    if (!messages.has(field)) return;
    if (field.validationMessage === messages.get(field)) field.setCustomValidity('');
    messages.delete(field);
  }));
})();
