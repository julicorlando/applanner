const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const code = fs.readFileSync(path.join(__dirname, '../static/js/app-install.js'), 'utf8');

function page({installed=false, ios=false, storageBlocked=false}={}) {
  const events = {};
  const click = {};
  const instructions = {textContent:''};
  const button = {disabled:false, addEventListener:(name,handler)=>{click.install=handler;}};
  const dismiss = {addEventListener:(name,handler)=>{click.dismiss=handler;}};
  const strip = {hidden:true,querySelector:(selector)=>selector==='[data-app-install]'?button:dismiss};
  const dialog = {opened:false,showModal(){this.opened=true;},querySelector:()=>instructions};
  const storage = {getItem(){if(storageBlocked) throw Error('Blocked');return null;},setItem(){if(storageBlocked) throw Error('Blocked');}};
  const navigator = {userAgent:ios?'iPhone':'Android',platform:ios?'iPhone':'Linux',maxTouchPoints:1};
  const window = {navigator,matchMedia:()=>({matches:installed,addEventListener(){}}),addEventListener:(name,handler)=>{events[name]=handler;}};
  vm.runInNewContext(code,{window,navigator,sessionStorage:storage,document:{querySelector:(selector)=>selector==='[data-app-install-strip]'?strip:dialog}});
  return {events,click,strip,dialog,instructions,button};
}

test('installation asks the browser only after user presses Add',async()=>{
  const ui=page();let prompted=0;
  ui.events.beforeinstallprompt({preventDefault(){},async prompt(){prompted++;},userChoice:Promise.resolve({outcome:'accepted'})});
  assert.equal(prompted,0);
  await ui.click.install();
  assert.equal(prompted,1);
  assert.equal(ui.strip.hidden,true);
  assert.equal(ui.button.disabled,false);
});
test('iPhone without a native prompt receives home screen instructions',async()=>{
  const ui=page({ios:true});
  await ui.click.install();
  assert.equal(ui.dialog.opened,true);
  assert.match(ui.instructions.textContent,/Safari/);
  assert.match(ui.instructions.textContent,/Adicionar à Tela de Início/);
});
test('dismissal works even when preference storage is blocked',()=>{
  const ui=page({storageBlocked:true});
  assert.equal(ui.strip.hidden,false);
  ui.click.dismiss();
  assert.equal(ui.strip.hidden,true);
});
test('installed display hides the installation suggestion',()=>{
  assert.equal(page({installed:true}).strip.hidden,true);
});
test('browser refusing a native prompt shows manual instructions',async()=>{
  const ui=page();
  ui.events.beforeinstallprompt({preventDefault(){},async prompt(){throw Error('Not available');}});
  await ui.click.install();
  assert.equal(ui.dialog.opened,true);
  assert.equal(ui.button.disabled,false);
});
