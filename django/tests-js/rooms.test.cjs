const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const {webcrypto} = require('node:crypto');
const settle = async () => { for (let i=0;i<5;i++) await new Promise(resolve=>setImmediate(resolve)); };
function setup({prompt=true,fail=false}={}) {
 const dom = new JSDOM(`<button data-room-open>Trocar sala</button><dialog id="clinic-room-dialog" data-auto-open="${prompt}"><button data-room-close>Agora não</button></dialog><form data-patient-call action="/app/clinica/tv/chamar/"><input name="request_id" value="original-retry-key"><input name="appointment" value="12"><button type="submit">Chamar paciente</button><span data-call-status role="status"></span></form><form id="assessment"><textarea name="complaint">Texto clínico ainda não salvo</textarea></form>`,{runScripts:'outside-only',url:'https://applanner.test/app/clinica/'});
 const w=dom.window,d=w.document,dialog=d.querySelector('dialog');let requests=[];
 dialog.showModal=()=>{dialog.open=true;};dialog.close=()=>{dialog.open=false;};
 Object.defineProperty(w,'crypto',{value:webcrypto});
 w.fetch=async(url,options)=>{requests.push({url,options});if(fail)throw Error('Sem conexão');return {ok:true,headers:{get:()=> 'application/json'},json:async()=>({called:true,room:'Sala 02'})};};
 w.eval(fs.readFileSync('static/healthcare/rooms.js','utf8'));
 return {dom,w,d,dialog,requests};
}
test('first access asks room, close and change room reopen the accessible dialog',()=>{
 const ui=setup();assert.equal(ui.dialog.open,true);ui.d.querySelector('[data-room-close]').click();assert.equal(ui.dialog.open,false);ui.d.querySelector('[data-room-open]').click();assert.equal(ui.dialog.open,true);ui.dom.window.close();
});
test('remembered daily room does not prompt again',()=>{
 const ui=setup({prompt:false});assert.equal(ui.dialog.open,false);ui.dom.window.close();
});
test('calling from the record preserves unsaved clinical input and renews successful request UUID',async()=>{
 const ui=setup({prompt:false}),form=ui.d.querySelector('[data-patient-call]');
 const event=new ui.w.Event('submit',{cancelable:true});assert.equal(form.dispatchEvent(event),false);await settle();
 assert.equal(ui.requests.length,1);assert.equal(ui.requests[0].options.method,'POST');assert.equal(ui.requests[0].options.body.get('appointment'),'12');assert.equal(ui.requests[0].options.credentials,'same-origin');assert.match(form.querySelector('[role=status]').textContent,/Paciente chamado na TV · Sala 02/);assert.notEqual(form.elements.request_id.value,'original-retry-key');assert.equal(ui.d.querySelector('textarea').value,'Texto clínico ainda não salvo');assert.equal(form.querySelector('button').disabled,false);ui.dom.window.close();
});
test('failed calls retain the UUID for safe retry without claiming success',async()=>{
 const ui=setup({fail:true}),form=ui.d.querySelector('[data-patient-call]');form.dispatchEvent(new ui.w.Event('submit',{cancelable:true}));await settle();assert.equal(form.elements.request_id.value,'original-retry-key');assert.match(form.querySelector('[role=status]').textContent,/Sem conexão/);assert.equal(form.querySelector('button').disabled,false);ui.dom.window.close();
});
