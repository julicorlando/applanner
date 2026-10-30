const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');const {webcrypto}=require('node:crypto');const {JSDOM}=require('jsdom');
function vault(){const ctx={TextEncoder,TextDecoder,crypto:webcrypto,btoa,atob,Uint8Array};vm.createContext(ctx);vm.runInContext(fs.readFileSync('static/healthcare/offline-vault.js','utf8'),ctx);return ctx.ClinicVault;}
test('offline vault encrypts PHI using a nonextractable key and rejects wrong passwords and tampering',async()=>{
 const v=vault(),salt=webcrypto.getRandomValues(new Uint8Array(16)),key=await v.derive('SenhaLocalForte!123',salt);assert.equal(key.extractable,false);
 const state={snapshot:{scope:'3:4',patients:[{name:'Paciente Segredo'}]},queue:[{kind:'evolution',data:{content:'Dor 7/10'}}]};
 const envelope=await v.seal(state,key,salt);assert.ok(!JSON.stringify(envelope).includes('Paciente'));assert.ok(!JSON.stringify(envelope).includes('Dor'));
 assert.equal((await v.open(envelope,'SenhaLocalForte!123')).value.queue[0].data.content,'Dor 7/10');
 await assert.rejects(v.open(envelope,'SenhaErrada!12345'),/Senha incorreta/);
 const tampered={...envelope,ciphertext:(envelope.ciphertext[0]==='A'?'B':'A')+envelope.ciphertext.slice(1)};
 await assert.rejects(v.open(tampered,'SenhaLocalForte!123'),/danificado/);await assert.rejects(v.derive('curta',salt),/12 caracteres/);
});
test('large clinical snapshot encrypts without overflowing the stack',async()=>{
 const v=vault(),salt=webcrypto.getRandomValues(new Uint8Array(16)),key=await v.derive('SenhaLocalForte!123',salt),content='á'.repeat(300000);
 assert.equal((await v.open(await v.seal({snapshot:{scope:'1:2',content},queue:[]},key,salt),'SenhaLocalForte!123')).value.snapshot.content,content);
});
test('desktop menu hides, restores and maintains accessibility; mobile Escape closes',()=>{
 const dom=new JSDOM('<button id="pa-menu-toggle"></button><aside id="pa-sidebar"><a href="/app/">Painel</a><button id="pa-menu-close">Fechar</button></aside>',{runScripts:'outside-only',url:'https://applanner.test'});const w=dom.window,d=w.document;let mobile=false;
 w.matchMedia=()=>({matches:mobile});w.eval(fs.readFileSync('static/healthcare/physio-shell.js','utf8'));
 const toggle=d.getElementById('pa-menu-toggle');assert.equal(toggle.getAttribute('aria-expanded'),'true');toggle.click();assert.ok(d.body.classList.contains('pa-menu-collapsed'));assert.equal(d.getElementById('pa-sidebar').inert,true);assert.equal(w.localStorage.getItem('applanner.clinical.menu.collapsed'),'true');
 toggle.click();assert.equal(toggle.getAttribute('aria-expanded'),'true');mobile=true;w.dispatchEvent(new w.Event('resize'));assert.equal(toggle.getAttribute('aria-expanded'),'false');toggle.click();assert.equal(toggle.getAttribute('aria-expanded'),'true');d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape'}));assert.equal(toggle.getAttribute('aria-expanded'),'false');
});
test('TV treats labels as text and clears calls/media when access is revoked',async()=>{
 const dom=new JSDOM('<div id="tv-panel" data-feed="/feed/"></div><span id="tv-link"></span><button id="tv-start"></button><div id="tv-current"></div><div id="tv-history"></div><div id="tv-media"></div><span id="tv-connection"></span><h1 id="tv-title"></h1><time id="tv-clock"></time>',{runScripts:'outside-only',url:'https://applanner.test/tv/test/token/'});
 const w=dom.window,d=w.document;let revoked=false,interval;w.setTimeout=()=>0;w.AbortSignal.timeout=()=>undefined;w.setInterval=(fn,ms)=>{if(ms===5000)interval=fn;return 0;};
 w.fetch=async()=>({ok:!revoked,status:revoked?404:200,json:async()=>({title:'Teste',voice:false,calls:[{id:1,name:'<img src=x onerror=alert(1)>',room:'Sala 01'},{id:2,name:'João S.',room:'Sala 02'}],media:[]})});w.eval(fs.readFileSync('static/healthcare/tv.js','utf8'));await new Promise(resolve=>setImmediate(resolve));
 assert.equal(d.querySelector('#tv-current img'),null);assert.ok(d.getElementById('tv-current').textContent.includes('<img'));assert.equal(d.querySelectorAll('.tv-row').length,1);revoked=true;await interval();assert.equal(d.getElementById('tv-current').textContent,'Aguarde a chamada');assert.equal(d.getElementById('tv-history').children.length,0);assert.equal(d.getElementById('tv-media').children.length,0);
});
