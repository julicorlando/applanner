const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const {JSDOM}=require('jsdom');const {webcrypto}=require('node:crypto');
const settle=async()=>{for(let i=0;i<5;i++)await new Promise(resolve=>setImmediate(resolve));};
function setup({failSave=false,online=false,foreign=false}={}){
 const html=fs.readFileSync('templates/healthcare/offline_shell.html','utf8').replace(/{%.*?%}/gs,'');
 const dom=new JSDOM(html,{runScripts:'outside-only',url:'https://applanner.test/offline/clinica/'}),w=dom.window,d=w.document;
 let saved,requests=[],interval;
 const snapshot={scope:'1:2',company:'Clínica Fictícia',user:'Pessoa Teste',downloaded_at:new Date().toISOString(),expires_at:new Date(Date.now()+86400000).toISOString(),permissions:{clinical:true,cash:true},truncated:{patients:false,appointments:false},patients:[{id:1,name:'Paciente Segredo',phone:'5581999999999'}],appointments:[],professionals:[{id:2,name:'Pessoa Teste'}],services:[{id:3,name:'Sessão'}],entries:[{id:4,customer:1,title:'Privado',content:'Dor confidencial',at:new Date().toISOString()}]};
 Object.defineProperty(w,'isSecureContext',{value:true});Object.defineProperty(w,'crypto',{value:webcrypto});Object.defineProperty(w.navigator,'onLine',{value:online,configurable:true});Object.defineProperty(w.navigator,'serviceWorker',{value:{}});Object.defineProperty(w.navigator,'locks',{value:{request:async(name,opts,cb)=>cb({})}});
 w.AbortSignal.timeout=()=>undefined;w.structuredClone=structuredClone;w.setInterval=fn=>{interval=fn;return 0;};w.confirm=()=>true;
 w.ClinicVault={load:async()=>({sealed:true}),open:async()=>({value:{snapshot:structuredClone(snapshot),queue:[]},key:{},salt:[]}),seal:async value=>structuredClone(value),save:async value=>{if(failSave)throw Error('Sem espaço no dispositivo');saved=structuredClone(value);},erase:async()=>{}};
 w.fetch=async(url,options={})=>{requests.push({url,options});return {ok:true,headers:{get:()=> 'application/json'},json:async()=>({...snapshot,scope:foreign?'9:9':snapshot.scope})};};
 w.eval(fs.readFileSync('static/healthcare/offline-ui.js','utf8'));
 async function unlock(){d.getElementById('co-password').value='SenhaLocalTeste!2026';d.getElementById('co-consent').checked=true;d.getElementById('co-unlock').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await settle();}
 return {w,d,dom,unlock,requests,get saved(){return saved;},get interval(){return interval;}};
}
test('offline patient form saves into the vault before confirming; no request is sent offline',async()=>{
 const ui=setup();await ui.unlock();const {d,w}=ui;assert.equal(d.getElementById('co-work').hidden,false);
 const form=d.getElementById('co-patient');form.elements.name.value='Novo Paciente';form.dispatchEvent(new w.Event('submit',{cancelable:true,bubbles:true}));await settle();
 assert.equal(ui.saved.queue.length,1);assert.equal(ui.saved.queue[0].kind,'customer');assert.equal(ui.saved.queue[0].data.name,'Novo Paciente');assert.equal(ui.requests.length,0);assert.match(d.getElementById('co-status').textContent,/Salvo no cofre local/);
 d.getElementById('co-lock-button').click();assert.equal(d.getElementById('co-work').hidden,true);assert.ok(!d.body.textContent.includes('Dor confidencial'));assert.ok(!d.body.textContent.includes('Paciente Segredo'));assert.equal(w.localStorage.length,0);ui.dom.window.close();
});
test('storage failure does not claim an offline save succeeded',async()=>{
 const ui=setup({failSave:true});await ui.unlock();const form=ui.d.getElementById('co-patient');form.elements.name.value='Falha de armazenamento';form.dispatchEvent(new ui.w.Event('submit',{cancelable:true,bubbles:true}));await settle();assert.equal(ui.saved,undefined);assert.match(ui.d.getElementById('co-status').textContent,/Sem espaço/);ui.dom.window.close();
});
test('a different signed-in account locks the vault without posting queued content',async()=>{
 const ui=setup({online:true,foreign:true});await ui.unlock();assert.equal(ui.d.getElementById('co-work').hidden,true);assert.ok(!ui.requests.some(x=>x.options.method==='POST'));assert.match(ui.d.getElementById('co-status').textContent,/Conta ou clínica diferente/);ui.dom.window.close();
});
