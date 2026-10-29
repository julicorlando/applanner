const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');

function dental(initial={}){
  const dom=new JSDOM(`<section data-odontogram><input data-chart-input><div data-arches></div><div data-legend></div><p data-selection></p><div data-chart-summary></div><button data-dentition="permanent"></button><button data-dentition="primary"></button><select data-condition><option value="carie">Cárie</option></select><input data-surface type="checkbox" value="mesial"><textarea data-note></textarea><button data-add></button><button data-clear></button></section>`,{runScripts:'outside-only'});
  dom.window.document.querySelector('[data-chart-input]').value=JSON.stringify(initial);
  dom.window.eval(fs.readFileSync('static/healthcare/odontogram.js','utf8'));
  return dom;
}
test('FDI draws 32 permanent and 20 deciduous schematic teeth',()=>{
  const {window}=dental(),d=window.document;
  assert.equal(d.querySelectorAll('[data-tooth]').length,32);
  assert.ok(d.querySelector('[data-tooth="18"] path'));
  d.querySelector('[data-dentition="primary"]').click();
  assert.equal(d.querySelectorAll('[data-tooth]').length,20);
  assert.ok(d.querySelector('[data-tooth="55"]'));
  assert.equal(d.querySelector('[data-tooth="18"]'),null);
});
test('multi-tooth conditions and faces are serialized without executing notes',()=>{
  const {window}=dental(),d=window.document;
  d.querySelector('[data-tooth="11"]').dispatchEvent(new window.MouseEvent('click',{bubbles:true}));
  d.querySelector('[data-tooth="21"]').dispatchEvent(new window.MouseEvent('click',{bubbles:true}));
  d.querySelector('[data-surface]').click();
  d.querySelector('[data-note]').value='<img src=x onerror=alert(1)>';
  d.querySelector('[data-add]').click();
  const chart=JSON.parse(d.querySelector('[data-chart-input]').value);
  assert.deepEqual(Object.keys(chart),['11','21']);
  assert.deepEqual(chart['11'][0].surfaces,['mesial']);
  assert.equal(d.querySelector('[data-chart-summary] img'),null);
  assert.match(d.querySelector('[data-chart-summary]').textContent,/<img/);
});
test('dentition switch preserves draft and keyboard selects teeth',()=>{
  const {window}=dental({'55':[{condition:'carie',surfaces:['mesial'],note:'Histórico'}]}),d=window.document;
  d.querySelector('[data-tooth="11"]').dispatchEvent(new window.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
  assert.match(d.querySelector('[data-selection]').textContent,/11/);
  d.querySelector('[data-dentition="primary"]').click();
  assert.equal(JSON.parse(d.querySelector('[data-chart-input]').value)['55'][0].note,'Histórico');
});
test('surface targets use palatal/incisal for upper incisors',()=>{
  const d=dental().window.document;
  assert.ok(d.querySelector('[data-tooth="11"] [data-face="palatina"]'));
  assert.ok(d.querySelector('[data-tooth="11"] [data-face="incisal"]'));
  assert.ok(d.querySelector('[data-tooth="46"] [data-face="oclusal"]'));
});
function physio(){
  const source=fs.readFileSync('templates/portal/physiotherapy_record_form.html','utf8');
  const script=source.match(/<script>([\s\S]*?)<\/script>/)[1];
  const areas=[['knee_left','Joelho esquerdo · anterior'],['knee_back_left','Joelho esquerdo · posterior']];
  const dom=new JSDOM(`<input name="record_type" type="radio" value="physio_evaluation" checked><section data-kind="physio_evaluation"></section><section data-kind="physio_evolution"></section><div id="area-list"></div><div id="body-canvas"></div><div id="body-inputs"></div><div id="selected-area-summary"></div><input id="id_body_findings" value="{}"><div id="region-details"></div><button data-view="anterior"></button><button data-view="posterior"></button><script id="physio-body-areas" type="application/json">${JSON.stringify(areas)}</script><script id="physio-body-selected" type="application/json">[]</script>`,{runScripts:'outside-only'});
  dom.window.eval(script);return dom;
}
test('body map uses patient laterality and saves per-region pain',()=>{
  const {window}=physio(),d=window.document;
  assert.equal(d.querySelector('.hotspot').style.left,'65.5%');
  d.querySelector('.hotspot').click();
  const pain=d.querySelector('#region-details input');pain.value='8';pain.dispatchEvent(new window.Event('input'));
  assert.equal(JSON.parse(d.querySelector('#id_body_findings').value).knee_left.pain,8);
  assert.equal(d.querySelector('input[name="body_regions"]').value,'knee_left');
  d.querySelector('[data-view="posterior"]').click();
  assert.equal(d.querySelector('.hotspot').style.left,'34.5%');
});
