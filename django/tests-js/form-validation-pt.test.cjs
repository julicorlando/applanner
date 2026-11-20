const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function page() {
  const listeners = {};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/form-validation-pt.js'), 'utf8'), {
    document: {addEventListener(name, handler) { listeners[name] = handler; }},
  });
  return listeners;
}
function input(constraints = {}) {
  let custom = '';
  return {
    tagName: 'INPUT', type: 'text', willValidate: true, labels: [{textContent: 'Seu nome'}],
    get validationMessage() { return custom || 'Please fill out this field.'; },
    setCustomValidity(message) { custom = message; },
    get validity() { return {...constraints, customError: !!custom, valid: !custom && !Object.values(constraints).some(Boolean)}; },
    correct() { Object.keys(constraints).forEach(key => { constraints[key] = false; }); },
  };
}
test('Portuguese message is set before submit validation and clears after correction', () => {
  const handlers = page();
  const field = input({valueMissing: true});
  const form = {elements: [field]};
  handlers.click({target: {closest: () => ({type: 'submit', form})}});
  assert.equal(field.validationMessage, 'Preencha este campo.');
  field.correct();
  handlers.input({target: field});
  assert.equal(field.validity.valid, true);
});
test('Enter submission and invalid event provide Portuguese feedback', () => {
  const handlers = page();
  const field = input({typeMismatch: true});
  field.type = 'email';
  const feedback = {};
  field.form = {elements: [field], querySelector: () => feedback};
  handlers.keydown({key: 'Enter', target: field});
  handlers.invalid({target: field});
  assert.equal(field.validationMessage, 'Informe um e-mail válido.');
  assert.equal(feedback.textContent, 'Seu nome: Informe um e-mail válido.');
});
test('Business custom errors survive localization and input changes', () => {
  const handlers = page();
  const field = input();
  field.setCustomValidity('Este telefone não pode ser usado.');
  handlers.invalid({target: field});
  handlers.input({target: field});
  assert.equal(field.validationMessage, 'Este telefone não pode ser usado.');
});
