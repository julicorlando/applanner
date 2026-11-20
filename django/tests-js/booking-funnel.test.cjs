const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function fixture() {
  const handlers = {}, calls = [];
  const form = {addEventListener:(name,fn)=>handlers[name]=fn,querySelector:()=>({value:'csrf-test'})};
  const config = {dataset:{url:'/api/public/test/funil/',token:'signed-token'}};
  const document = {getElementById:id=>id==='booking-funnel-tracking'?config:id==='public-booking'?form:null,querySelectorAll:()=>[]};
  vm.runInNewContext(fs.readFileSync('static/js/booking-funnel.js','utf8'),{document,Set,JSON,fetch:(url,options)=>{calls.push({url,options});return Promise.resolve({ok:true});}});
  return {handlers,calls};
}
test('resource and selected slot are counted once with the signed token and CSRF',()=>{
  const {handlers,calls}=fixture();
  handlers.change({target:{id:'booking-service',value:'1'}});
  handlers['booking:slot']({detail:{selected:true}});
  handlers['booking:slot']({detail:{selected:true}});
  assert.deepEqual(calls.map(c=>JSON.parse(c.options.body).stage),['resource','slot']);
  assert.equal(calls[0].options.headers['X-CSRFToken'],'csrf-test');
  assert.equal(JSON.parse(calls[0].options.body).token,'signed-token');
});
test('clearing a selection does not record a step or confirmation',()=>{
  const {handlers,calls}=fixture();
  handlers.change({target:{id:'booking-service',value:''}});
  handlers['booking:slot']({detail:{selected:false}});
  assert.equal(calls.length,0);
  assert.equal(handlers['booking:confirmed'],undefined);
});
test('arena slot buttons record the resource and time steps',()=>{
  const {handlers,calls}=fixture();
  handlers.click({target:{closest:()=>({})}});
  assert.deepEqual(calls.map(c=>JSON.parse(c.options.body).stage),['resource','slot']);
});
