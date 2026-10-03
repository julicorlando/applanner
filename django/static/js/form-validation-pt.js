// Keep browser constraint validation, with messages matching the interface language.
document.addEventListener('invalid', (event) => {
  const field = event.target;
  if (!field.validity || !field.setCustomValidity) return;
  const validity = field.validity;
  if (validity.customError) return;
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
}, true);
['input', 'change'].forEach((name) => document.addEventListener(name, (event) => {
  if (event.target.setCustomValidity) event.target.setCustomValidity('');
}));
