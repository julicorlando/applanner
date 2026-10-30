const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/push-preferences.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

async function harness({permission = 'granted', enabled = true, removeFails = false} = {}) {
  const events = [], listeners = {}, feedback = {textContent: ''};
  const buttons = {enable: {addEventListener: (name, fn) => { listeners.enable = fn; }},
                   disable: {addEventListener: (name, fn) => { listeners.disable = fn; }}};
  const subscription = {endpoint: 'https://fcm.googleapis.com/synthetic', toJSON: () => ({}),
    unsubscribe: async () => { events.push('unsubscribe'); }};
  const registration = {pushManager: {getSubscription: async () => subscription}};
  const box = {dataset: {pushUrl: '/account/notificacoes/push/'}, querySelector: selector =>
    selector === '[data-push-feedback]' ? feedback :
      selector === '[data-push-enable]' ? buttons.enable : buttons.disable};
  const Notification = {permission: 'default', requestPermission: () => {
    events.push('permission'); return Promise.resolve(permission);
  }};
  const context = {window: {isSecureContext: true, Notification, PushManager: {}}, Notification,
    navigator: {serviceWorker: {register: async () => registration, ready: Promise.resolve(registration),
      getRegistration: async () => registration}},
    document: {querySelector: selector => selector === '[data-push-preferences]' ? box : {value: 'synthetic-csrf'}},
    fetch: async (url, options = {}) => {
      if (options.method === 'POST') {
        const data = JSON.parse(options.body);
        events.push(data.action === 'remove' ? 'remove' : 'enroll');
        return {ok: !(removeFails && data.action === 'remove'),
          json: async () => ({detail: removeFails ? 'Servidor indisponível' : 'Preferência salva'})};
      }
      events.push('config');
      return {ok: true, json: async () => ({enabled, publicKey: 'AQ'})};
    },
    atob: value => Buffer.from(value, 'base64').toString('binary'),
    setTimeout: () => 0, Uint8Array, Promise, Error, JSON,
  };
  vm.runInNewContext(source, context);
  await tick();
  events.length = 0;
  return {events, listeners, feedback};
}

test('Push requests permission inside click before any enrollment request', async () => {
  const h = await harness();
  const action = h.listeners.enable();
  assert.equal(h.events[0], 'permission');
  await action;
  assert.deepEqual(h.events, ['permission', 'enroll']);
  assert.equal(h.feedback.textContent, 'Preferência salva');
});

test('Denied permission never enrolls the device', async () => {
  const h = await harness({permission: 'denied'});
  await h.listeners.enable();
  assert.deepEqual(h.events, ['permission']);
  assert.match(h.feedback.textContent, /Permissão não concedida/);
});

test('Disabled platform Push does not prompt for browser permission', async () => {
  const h = await harness({enabled: false});
  await h.listeners.enable();
  assert.deepEqual(h.events, []);
  assert.match(h.feedback.textContent, /Master precisa ativar/);
});

test('Unsubscribe waits for server success and reports failures', async () => {
  const h = await harness({removeFails: true});
  await h.listeners.disable();
  assert.deepEqual(h.events, ['remove']);
  assert.equal(h.feedback.textContent, 'Servidor indisponível');
});
