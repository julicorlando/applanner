const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.events = {}; this.textContent = ''; }
  appendChild(child) { this.children.push(child); }
  replaceChildren() { this.children = []; }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener(key, callback) { this.events[key] = callback; }
  querySelectorAll(tag) { return this.children.flatMap(child => [...(child.tag === tag ? [child] : []), ...child.querySelectorAll(tag)]); }
}
function picker(fetch, extra = {}) {
  const window = {}, container = new Element('div'), input = {value:''}, status = {};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/booking-slots.js'), 'utf8'), {window, fetch, document:{createElement: tag => new Element(tag)}});
  return {container, input, status, api:window.createBookingSlotPicker({container,input,status,...extra})};
}
const response = data => ({ok:true,json:async()=>data});
test('groups slots, marks only one selected, and returns professional metadata', async () => {
  let selected;
  const page = picker(async()=>response({slots:[
    {value:'morning-a',label:'09:30',professional_name:'Ana'},
    {value:'afternoon-b',label:'14:00',professional_name:'Bia'},
    {value:'night-a',label:'18:00',professional_name:'Ana'},
  ]}), {onChange:(active,slot)=>{selected=active ? slot : null;}});
  await page.api.load('/slots');
  assert.deepEqual(page.container.children.map(group=>group.children[0].textContent), ['Manhã','Tarde','Noite']);
  const buttons=page.container.querySelectorAll('button');
  assert.equal(buttons[0].children[0].textContent, 'Próximo horário');
  buttons[0].events.click(); buttons[1].events.click();
  assert.equal(page.input.value, 'afternoon-b'); assert.equal(selected.professional_name, 'Bia');
  assert.equal(buttons[0].attrs['aria-pressed'], 'false'); assert.equal(buttons[1].attrs['aria-pressed'], 'true');
});
test('an outdated availability request cannot replace the current date', async () => {
  let resolveOld;
  const page=picker(url=>url==='old' ? new Promise(resolve=>{resolveOld=resolve;}) : Promise.resolve(response({slots:[{value:'new',label:'15:00'}]})));
  const old=page.api.load('old'); await page.api.load('new');
  resolveOld(response({slots:[{value:'old',label:'08:00'}]})); await old;
  const buttons=page.container.querySelectorAll('button'); assert.equal(buttons.length,1);
  buttons[0].events.click(); assert.equal(page.input.value,'new');
});
test('empty dates preserve next available date and reset a previous selection', async () => {
  let nextDate, availability;
  const page=picker(async()=>response({slots:[],next_available:{date:'2026-10-08',date_label:'08/10',label:'10:00'}}),{onNextDate:date=>{nextDate=date;},onAvailability:count=>{availability=count;}});
  page.input.value='previous'; await page.api.load('/empty');
  assert.equal(page.input.value,''); assert.equal(availability,0);
  page.container.querySelectorAll('button')[0].events.click(); assert.equal(nextDate,'2026-10-08');
});
