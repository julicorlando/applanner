const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const code = fs.readFileSync(path.join(__dirname,'../static/js/app-worker.js'),'utf8');
function setup({type='text/css', policy='public, max-age=31536000', cacheError=false}={}) {
  const events={}, writes=[], fetched=[], deleted=[];
  const response={ok:true,type:'basic',redirected:false,headers:{get:key=>key==='Content-Type'?type:policy},clone(){return this;}};
  const cache={async match(){return undefined;},async put(request){writes.push(request.url);}};
  const caches={async open(){if(cacheError) throw Error('quota');return cache;},async keys(){return ['applanner-static-old','other-app'];},async delete(name){deleted.push(name);}};
  const self={location:{origin:'https://applanner.com.br'},clients:{async claim(){}},addEventListener:(name,fn)=>{events[name]=fn;},async skipWaiting(){self.activated=true;}};
  vm.runInNewContext(code,{self,caches,URL,Request,fetch:async request=>{fetched.push(request);return response;}});
  async function request(url,opts={}) {
    let intercepted=false,promise;
    events.fetch({request:{url,method:opts.method||'GET',mode:opts.mode||'same-origin'},respondWith(value){intercepted=true;promise=value;}});
    if(promise) await promise;
    return intercepted;
  }
  return {request,events,writes,fetched,deleted,self};
}
test('private pages, APIs, payments, uploads, external and non-fingerprinted assets are never intercepted',async()=>{
  const ui=setup();
  for(const url of ['/','/admin/','/app/','/api/appointments/','/billing/','/media/avatar.png','/static/js/theme.js','/static/js/theme.123456abcdef.js?token=secret','https://example.com/static/x.123456abcdef.js']) {
    assert.equal(await ui.request(url.startsWith('https:')?url:'https://applanner.com.br'+url),false,url);
  }
  assert.equal(await ui.request('https://applanner.com.br/static/app.123456abcdef.css',{method:'POST'}),false);
  assert.equal(await ui.request('https://applanner.com.br/static/app.123456abcdef.css',{mode:'navigate'}),false);
  assert.equal(ui.writes.length,0);
});
test('fingerprinted static assets are fetched without credentials and cached',async()=>{
  const ui=setup();
  assert.equal(await ui.request('https://applanner.com.br/static/app.123456abcdef.css'),true);
  assert.equal(ui.fetched[0].credentials,'omit');assert.equal(ui.writes.length,1);
});
test('HTML, JSON and private/no-store responses cannot enter cache',async()=>{
  for(const opts of [{type:'text/html'},{type:'application/json'},{policy:'private'},{policy:'no-store'}]) {
    const ui=setup(opts);await ui.request('https://applanner.com.br/static/app.123456abcdef.css');assert.equal(ui.writes.length,0);
  }
});
test('activation removes only this applications previous cache versions',async()=>{
  const ui=setup();let done;ui.events.activate({waitUntil(promise){done=promise;}});await done;
  assert.deepEqual(ui.deleted,['applanner-static-old']);
});
test('worker update requires explicit activation message',async()=>{
  const ui=setup();ui.events.message({data:{type:'other'},waitUntil(){}});assert.equal(ui.self.activated,undefined);
  let done;ui.events.message({data:{type:'APPLANNER_ACTIVATE_UPDATE'},waitUntil(promise){done=promise;}});await done;assert.equal(ui.self.activated,true);
});

test('unavailable cache storage falls back to the network',async()=>{
  const ui=setup({cacheError:true});await ui.request('https://applanner.com.br/static/app.123456abcdef.css');assert.equal(ui.fetched.length,1);
});

test('clinical shell preparation caches only a fixed public allowlist and reports success',async()=>{
 const events={},written=[],fetched=[],ports=[];
 const assets=['/offline/clinica/','/static/healthcare/offline-ui.aabbccddeeff.js'];
 const cache={async put(path){written.push(path);},async match(){return {cached:true};}};
 const self={location:{origin:'https://applanner.test'},addEventListener:(name,fn)=>events[name]=fn};
 vm.runInNewContext('const CLINICAL_OFFLINE_ASSETS='+JSON.stringify(assets)+';'+code,{self,caches:{async open(){return cache;}},URL,Request,fetch:async req=>{fetched.push(req);return {ok:true,redirected:false};}});
 let pending;events.message({data:{type:'CLINICAL_PREPARE'},ports:[{postMessage:value=>ports.push(value)}],waitUntil:p=>pending=p});await pending;
 assert.deepEqual(written,assets);assert.equal(ports[0].ok,true);assert.ok(fetched.every(req=>req.credentials==='omit'));
 for(const path of ['/app/clinica/operacao/snapshot/','/app/clinica/registro/1/','/api/anything/','/tv/foo/token/dados/']){
   let intercepted=false;events.fetch({request:{url:'https://applanner.test'+path,method:'GET',mode:'navigate'},respondWith:()=>intercepted=true});assert.equal(intercepted,false,path);
 }
});
