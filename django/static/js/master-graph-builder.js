(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const graphField = $('id_graph_json');
  if (!graphField) return;
  const viewport = $('graph-viewport'), canvas = $('graph-canvas'), nodes = $('graph-nodes'), svg = $('graph-links');
  const script = document.querySelector('script[data-simulate-url]');
  const sidebar = $('graph-sidebar'), sidebarToggle = $('graph-side-toggle'), layout = $('graph-layout');
  function setSidebarCollapsed(collapsed, persist=false) {
    if (!sidebar || !sidebarToggle || !layout) return;
    sidebar.hidden = collapsed;
    layout.classList.toggle('side-collapsed', collapsed);
    sidebarToggle.setAttribute('aria-expanded', String(!collapsed));
    sidebarToggle.textContent = collapsed ? 'Mostrar painel' : 'Ocultar painel';
    if (persist) { try { localStorage.setItem('applanner.master.flow.sidebar.collapsed', String(collapsed)); } catch {} }
  }
  if (sidebarToggle) sidebarToggle.onclick = () => setSidebarCollapsed(!sidebar.hidden, true);
  try { setSidebarCollapsed(localStorage.getItem('applanner.master.flow.sidebar.collapsed') === 'true'); } catch {}
  const metadata = {
    knowledge:['Dúvidas do ApPlanner','#13a5bb'],commercial:['Cadastro de lead','#1ab767'],start:['Início','#ef365f'],message:['Mensagem','#336cf2'],menu:['Opções / menu','#ef9e09'],input:['Entrada de texto','#1ab767'],
    condition:['Condição / se','#13a5bb'],set:['Definir variável','#00a87b'],api:['Chamada API','#ff781b'],ai:['Agente IA','#ce2fba'],
    wait:['Aguardar','#19a5af'],handoff:['Atendimento humano','#9b44ed'],finish:['Finalizar','#263344'],legacy:['Resposta por palavra','#456bf3']
  };
  let graph, integrations = [], selected = null, pending = null, zoom = 1, undo = [], redo = [];
  let simulation = {}, simBusy = false;
  try { graph = JSON.parse(graphField.value); integrations = JSON.parse($('id_integrations_json').value || '[]'); }
  catch { $('graph-status').textContent = 'Não foi possível abrir o fluxo. Recarregue a página.'; return; }
  const clone = value => JSON.parse(JSON.stringify(value));
  const element = (tag, text, className) => { const e=document.createElement(tag); if(text!==undefined)e.textContent=text; if(className)e.className=className; return e; };
  const button = (text, callback, cls) => { const b=element('button',text,cls); b.type='button'; b.onclick=callback; return b; };
  function status(text) { $('graph-status').textContent=text; }
  function saveDraft() { graphField.value=JSON.stringify(graph); $('graph-undo').disabled=!undo.length; $('graph-redo').disabled=!redo.length; }
  function remember() { undo.push(JSON.stringify(graph)); if(undo.length>40)undo.shift(); redo=[]; }
  function change(fn, redraw=true) { remember(); fn(); saveDraft(); if(redraw)render(); status('Alterações locais. Salve o fluxo para aplicar ao WhatsApp.'); }
  function panel(name) { for(const p of ['palette','editor','settings'])$('graph-'+p).hidden=p!==name; document.querySelectorAll('[data-panel]').forEach(b=>b.classList.toggle('active',b.dataset.panel===name)); }
  function outputs(node) {
    if(node.type==='menu')return (node.config.options||[]).map(o=>[o.id,o.label,'#16aa73']);
    if(node.type==='condition')return [['yes','Verdadeiro','#16aa73'],['no','Falso','#ef4566']];
    if(['handoff','finish'].includes(node.type))return [];
    if(['api','ai'].includes(node.type))return [['next','Sucesso','#16aa73'],['error','Falha','#ef4566']];
    return [['next','Próximo',metadata[node.type][1]]];
  }
  function point(e) { const r=canvas.getBoundingClientRect(); return {x:(e.clientX-r.left)/zoom,y:(e.clientY-r.top)/zoom}; }
  function path(a,b,color) { const p=document.createElementNS('http://www.w3.org/2000/svg','path'); const bend=Math.max(50,Math.abs(b.y-a.y)/2); p.setAttribute('d',`M${a.x} ${a.y} C${a.x} ${a.y+bend},${b.x} ${b.y-bend},${b.x} ${b.y}`);p.style.stroke=color;svg.append(p); }
  function center(e) { const r=e.getBoundingClientRect(),c=canvas.getBoundingClientRect();return {x:(r.left+r.width/2-c.left)/zoom,y:(r.top+r.height/2-c.top)/zoom}; }
  function draw(pointer) {
    svg.replaceChildren();
    for(const n of graph.nodes)for(const [port,,color] of outputs(n)) {
      const target=n.outputs?.[port]; if(!target)continue;
      const a=nodes.querySelector(`[data-node-id="${n.id}"] [data-port="${port}"]`),b=nodes.querySelector(`[data-node-id="${target}"] .graph-port-in`);
      if(a&&b)path(center(a),center(b),color);
    }
    if(pending&&pointer) { const a=nodes.querySelector(`[data-node-id="${pending.id}"] [data-port="${pending.port}"]`); if(a)path(center(a),pointer,'#ef365f'); }
  }
  function connect(id) {
    if(!pending)return;
    const source=graph.nodes.find(n=>n.id===pending.id),target=graph.nodes.find(n=>n.id===id);
    if(!target||target.type==='start'){status('Escolha um bloco de destino diferente do início.');return;}
    const port=pending.port;pending=null;change(()=>{source.outputs[port]=id;});select(source.id);
  }
  function render() {
    nodes.replaceChildren();
    for(const n of graph.nodes) {
      const card=element('article',undefined,'graph-card'+(selected===n.id?' selected':''));card.dataset.nodeId=n.id;
      card.style.left=n.x+'px';card.style.top=n.y+'px';card.style.setProperty('--node-color',metadata[n.type][1]);
      const input=button('',()=>pending?connect(n.id):select(n.id),'graph-port-in');input.setAttribute('aria-label','Conectar entrada de '+n.label);card.append(input);
      const head=element('header',metadata[n.type][0]);card.append(head,element('strong',n.label||n.id));
      const preview=n.type==='condition'?`${n.config.variable||'variável'} ${n.config.operator||'equals'} ${n.config.expected||''}`:n.type==='wait'?`${n.config.seconds} segundo(s)`:n.type==='api'?`${n.config.method||'GET'} ${n.config.integration||'integração'}${n.config.path||'/'}`:n.config.text||n.config.prompt||n.config.value||'Clique para configurar';
      card.append(element('p',preview));const ports=element('div',undefined,'graph-ports');
      for(const [key,label,color] of outputs(n)) {
        const wrap=element('div',undefined,'graph-port-wrap'+(n.outputs?.[key]?' connected':''));wrap.style.setProperty('--port-color',color);wrap.append(element('span',label));
        const port=element('button',undefined,'graph-port-out');port.type='button';port.dataset.port=key;port.setAttribute('aria-label',`${n.label}: conectar ${label}`);
        const begin=e=>{e.stopPropagation();pending={id:n.id,port:key};status('Escolha ou arraste até o conector de entrada do destino. Escape cancela.');};
        port.onpointerdown=begin;port.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();begin(e);}};wrap.append(port);ports.append(wrap);
      }
      card.append(ports);card.onclick=e=>{if(e.target.closest('.graph-port-out'))return; if(pending)connect(n.id);else select(n.id);};
      head.onpointerdown=e=>{
        if(pending)return; e.stopPropagation();head.setPointerCapture(e.pointerId);const start=point(e),original={x:n.x,y:n.y};let moved=false;
        head.onpointermove=ev=>{const p=point(ev);if(!moved&&Math.abs(p.x-start.x)+Math.abs(p.y-start.y)>3){remember();moved=true;}n.x=Math.max(0,Math.min(6000,original.x+p.x-start.x));n.y=Math.max(0,Math.min(6000,original.y+p.y-start.y));card.style.left=n.x+'px';card.style.top=n.y+'px';draw();};
        head.onpointerup=()=>{head.onpointermove=null;if(moved){saveDraft();status('Posição atualizada. Salve para aplicar.');}};
      };
      nodes.append(card);
    }
    requestAnimationFrame(()=>draw());
  }
  function select(id) { selected=id;render();edit();panel('editor'); }
  function edit() {
    const node=graph.nodes.find(n=>n.id===selected),container=$('graph-fields');container.replaceChildren();
    if(!node){$('graph-editor-title').textContent='Selecione um bloco';return;}
    $('graph-editor-title').textContent=metadata[node.type][0];
    function field(label,key,type='text',choices=null,source=node.config) {
      const l=element('label',label),f=element(type==='textarea'?'textarea':choices?'select':'input');
      if(type==='checkbox'){f.type='checkbox';f.checked=Boolean(source[key]);l.className='graph-check';}
      else if(choices){for(const [value,text] of choices){const o=element('option',text);o.value=value;f.append(o);}f.value=source[key]||choices[0][0];}
      else {if(type!=='textarea')f.type=type;f.value=source[key]??'';f.maxLength=key==='label'?80:4000;}
      f.oninput=()=>change(()=>{source[key]=type==='checkbox'?f.checked:type==='number'?Number(f.value):f.value;});l.append(f);container.append(l);return f;
    }
    field('Nome do bloco','label','text',null,node);
    if(node.type==='ai')field('Restringir à base oficial do ApPlanner','applanner_only','checkbox');
    if(node.type==='knowledge')field('Variável com a pergunta','variable');
    if(node.type==='commercial')container.append(element('p','Coleta nome, empresa, segmento, e-mail, unidades, profissionais, plano e necessidade; salva o lead progressivamente.'));
    if(['start','message','menu','input','handoff','finish','legacy'].includes(node.type))field(node.type==='input'?'Pergunta ao cliente':'Texto / mensagem','text','textarea');
    if(node.type==='input') {field('Salvar na variável','variable');field('Validação','validation','text',[['text','Texto'],['email','E-mail'],['phone','Telefone'],['number','Número']]);field('Mensagem quando inválido','invalid_text','textarea');}
    if(node.type==='set'){field('Variável','variable');field('Valor (aceita {{variavel}})','value','textarea');}
    if(node.type==='condition'){field('Variável ou caminho JSON','variable');field('Operador','operator','text',[['equals','Igual a'],['contains','Contém'],['exists','Existe'],['gt','Maior que'],['lt','Menor que']]);field('Valor esperado','expected');}
    if(node.type==='wait')field('Aguardar em segundos (1 a 86400)','seconds','number');
    if(node.type==='api') {field('Integração','integration','text',[['','Selecione'],...integrations.map(i=>[i.name,i.name])]);field('Método','method','text',[['GET','GET — consulta'],['POST','POST — operação']]);field('Caminho relativo (ex.: /clientes)','path');field('Corpo JSON (variáveis nas strings)','body','textarea');field('Guardar JSON na variável','variable');}
    if(node.type==='ai'){field('Instruções do agente','prompt','textarea');field('Salvar resposta na variável','variable');field('Enviar resposta ao cliente','send_output','checkbox');container.append(element('small','Chave e modelo em Configurar. Somente as instruções e a mensagem atual são enviadas à IA.'))}
    if(node.type==='legacy'){field('Palavras separadas por ;','keywords_text');const last=container.lastChild.querySelector('input');last.value=(node.config.keywords||[]).join(';');last.oninput=()=>change(()=>node.config.keywords=last.value.split(';').map(x=>x.trim()).filter(Boolean));field('Transferir ao humano','handoff','checkbox');field('Finalizar após resposta','finish','checkbox');}
    if(node.type==='menu') {
      for(const option of node.config.options||[]) {
        const row=element('section',undefined,'graph-option');const label=element('input');label.value=option.label;label.maxLength=100;label.setAttribute('aria-label','Texto da opção');label.oninput=()=>change(()=>option.label=label.value);
        const words=element('input');words.value=(option.keywords||[]).join(';');words.placeholder='Palavras ou números (; separa)';words.setAttribute('aria-label','Palavras da opção');words.oninput=()=>change(()=>option.keywords=words.value.split(';').map(x=>x.trim()).filter(Boolean));
        row.append(label,words,button('Remover opção',()=>{change(()=>{node.config.options=node.config.options.filter(o=>o!==option);delete node.outputs[option.id];});edit();},'danger'));container.append(row);
      }
      container.append(button('Adicionar opção',()=>{if(node.config.options.length>=10){status('Até dez opções por menu.');return;}change(()=>{let id='option_'+(node.config.options.length+1);while(node.config.options.some(o=>o.id===id))id+='x';node.config.options.push({id,label:'Nova opção',keywords:[]});});edit();}));
    }
    container.append(element('h3','Conexões'));
    for(const [port,label] of outputs(node)) field(label,port,'text',[['','Sem conexão'],...graph.nodes.filter(n=>n.type!=='start').map(n=>[n.id,n.label])],node.outputs);
    if(node.type==='menu')field('Se a escolha for inválida','invalid','text',[['','Repetir orientação'],...graph.nodes.filter(n=>n.type!=='start').map(n=>[n.id,n.label])],node.outputs);
    if(node.type!=='start')container.append(button('Duplicar bloco',()=>{change(()=>{const copied=clone(node);copied.id=unique(node.type);copied.label+=' (cópia)';copied.x=Math.min(6000,node.x+280);copied.outputs={};graph.nodes.push(copied);selected=copied.id;});edit();}),button('Excluir bloco',()=>{if(!confirm('Excluir o bloco e suas conexões?'))return;change(()=>{graph.nodes=graph.nodes.filter(n=>n.id!==node.id);for(const n of graph.nodes)for(const k of Object.keys(n.outputs))if(n.outputs[k]===node.id)delete n.outputs[k];selected=null;});edit();},'danger'));
    container.append(element('small','Use {{nome}} para interpolar uma variável e {{resposta.campo}} para ler um JSON. Não é executado código JavaScript.'));
  }
  function unique(type) { let n=1;while(graph.nodes.some(node=>node.id===type+'_'+n))n++;return type+'_'+n; }
  function add(type) {
    if(graph.nodes.length>=80){status('O limite é de 80 blocos.');return;}
    const configs={message:{text:'Como podemos ajudar?'},menu:{text:'Escolha uma opção:',options:[{id:'option_1',label:'Opção 1',keywords:['1']},{id:'option_2',label:'Opção 2',keywords:['2']}]},input:{text:'Qual é seu nome?',variable:'nome',validation:'text',invalid_text:'Informe um dado válido.'},condition:{variable:'nome',operator:'exists',expected:''},set:{variable:'segmento',value:'Barbearia'},api:{integration:integrations[0]?.name||'',method:'GET',path:'/',body:'',variable:'resposta'},ai:{prompt:'Você atende empresas interessadas no ApPlanner. Responda em português, seja objetivo e não invente preços nem confirmações de pagamento.',variable:'resposta_ia',send_output:true},knowledge:{variable:'pergunta'},commercial:{},wait:{seconds:60},handoff:{text:$('id_handoff').value},finish:{text:'Obrigado pelo contato!'}};
    let id;change(()=>{id=unique(type);graph.nodes.push({id,type,label:metadata[type][0],x:Math.min(6000,viewport.scrollLeft/zoom+100+(graph.nodes.length%3)*270),y:Math.min(6000,viewport.scrollTop/zoom+130+(graph.nodes.length%2)*220),config:clone(configs[type]),outputs:{}});selected=id;});select(id);
  }
  function integrationEditor() {
    const host=$('graph-integrations');host.replaceChildren();
    for(const item of integrations) {
      const card=element('section',undefined,'graph-integration');
      for(const [key,title,type] of [['name','Identificador','text'],['url','URL base HTTPS','url'],['token',item.has_token?'Token Bearer (já cadastrado)':'Token Bearer','password']]) {
        const label=element('label',title),input=element('input');input.type=type;input.value=item[key]||'';input.autocomplete=type==='password'?'new-password':'off';input.oninput=()=>{item[key]=input.value;$('id_integrations_json').value=JSON.stringify(integrations);};label.append(input);card.append(label);
      }
      const label=element('label','Habilitar integração','graph-check'),check=element('input');check.type='checkbox';check.checked=Boolean(item.enabled);check.onchange=()=>{item.enabled=check.checked;$('id_integrations_json').value=JSON.stringify(integrations);};label.prepend(check);card.append(label,button('Remover integração',()=>{integrations=integrations.filter(i=>i!==item);$('id_integrations_json').value=JSON.stringify(integrations);integrationEditor();}));host.append(card);
    }
  }
  for(const b of document.querySelectorAll('[data-node]')) {b.style.setProperty('--node-color',metadata[b.dataset.node][1]);b.onclick=()=>add(b.dataset.node);}
  for(const b of document.querySelectorAll('[data-panel]'))b.onclick=()=>panel(b.dataset.panel);
  $('graph-add-integration').onclick=()=>{if(integrations.length>=10){status('Até dez integrações.');return;}integrations.push({name:'api_'+(integrations.length+1),url:'https://',enabled:false});$('id_integrations_json').value=JSON.stringify(integrations);integrationEditor();};
  $('graph-undo').onclick=()=>{if(!undo.length)return;redo.push(JSON.stringify(graph));graph=JSON.parse(undo.pop());saveDraft();render();edit();};
  $('graph-redo').onclick=()=>{if(!redo.length)return;undo.push(JSON.stringify(graph));graph=JSON.parse(redo.pop());saveDraft();render();edit();};
  function setZoom(value) {zoom=Math.max(.35,Math.min(1.6,value));canvas.style.transform=`scale(${zoom})`;$('graph-zoom').value=Math.round(zoom*100)+'%';requestAnimationFrame(()=>draw());}
  $('graph-minus').onclick=()=>setZoom(zoom-.1);$('graph-plus').onclick=()=>setZoom(zoom+.1);
  $('graph-fit').onclick=()=>{const maxX=Math.max(...graph.nodes.map(n=>n.x+280)),maxY=Math.max(...graph.nodes.map(n=>n.y+250));setZoom(Math.min((viewport.clientWidth-40)/maxX,(viewport.clientHeight-50)/maxY));viewport.scrollTo(0,0);};
  viewport.addEventListener('pointermove',e=>{if(pending)draw(point(e));});
  viewport.addEventListener('pointerup',e=>{if(!pending)return;const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-node-id]');if(target&&!e.target.closest('.graph-port-out'))connect(target.dataset.nodeId);});
  viewport.addEventListener('pointerdown',e=>{if(pending||e.target.closest('.graph-card')||e.target.closest('.graph-zoom'))return;const start={x:e.clientX,y:e.clientY,left:viewport.scrollLeft,top:viewport.scrollTop};viewport.setPointerCapture(e.pointerId);const move=ev=>{viewport.scrollLeft=start.left+start.x-ev.clientX;viewport.scrollTop=start.top+start.y-ev.clientY;};const stop=()=>{viewport.removeEventListener('pointermove',move);viewport.removeEventListener('pointerup',stop);};viewport.addEventListener('pointermove',move);viewport.addEventListener('pointerup',stop);});
  window.addEventListener('keydown',e=>{if(e.key==='Escape'){pending=null;draw();status('Conexão cancelada.');}if((e.ctrlKey||e.metaKey)&&e.key==='z'&&!['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)){e.preventDefault();(e.shiftKey?$('graph-redo'):$('graph-undo')).click();}});
  $('graph-export').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(graph,null,2)],{type:'application/json'}));const a=element('a');a.href=url;a.download='applanner-fluxo-master.json';a.click();URL.revokeObjectURL(url);};
  $('graph-import').onchange=async()=>{const f=$('graph-import').files[0];if(!f)return;if(f.size>150000){status('Arquivo excede 150 KB.');return;}try {const value=JSON.parse(await f.text());if(value.version!==2||!Array.isArray(value.nodes)||value.nodes.length>80||!value.nodes.length||value.nodes.some(n=>!metadata[n.type]||!/^[a-z][a-z0-9_-]{0,59}$/.test(n.id)||!n.config||!n.outputs||!Number.isFinite(n.x)||!Number.isFinite(n.y)))throw new Error();change(()=>{graph=value;selected=null;});status('Fluxo importado. O servidor validará todas as conexões ao salvar.');}catch{status('Arquivo de fluxo inválido.');}};
  $('graph-template').onclick=()=>{if(!confirm('Substituir o rascunho pelo atendimento comercial completo?'))return;change(()=>{graph=JSON.parse($('commercial-template').textContent);selected=null;});edit();};
  function bubble(text,user=false) {const b=element('div',text,'graph-sim-bubble'+(user?' user':''));$('graph-test-thread').append(b);$('graph-test-thread').scrollTop=$('graph-test-thread').scrollHeight;}
  async function simulate(incoming='',resume=false) {
    if(simBusy)return;simBusy=true;const submit=$('graph-test-form').querySelector('button');submit.disabled=true;
    if(incoming)bubble(incoming,true);
    try {
      const response=await fetch(script.dataset.simulateUrl,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':$('master-flow-form').querySelector('[name=csrfmiddlewaretoken]').value},body:JSON.stringify({graph,state:simulation.state,context:simulation.context,waiting:simulation.waiting,incoming,resume})});
      const result=await response.json();if(!response.ok)throw new Error(result.error||'Falha na simulação.');simulation=result;
      for(const text of result.messages)bubble(text);
      $('graph-test-resume').hidden=result.waiting!=='wait';$('graph-test-input').disabled=result.handoff||result.state==='__finished__';
      $('graph-test-trace').textContent=JSON.stringify({estado:result.state,esperando:result.waiting,variaveis:result.context.variables,caminho:result.trace,erro:result.error},null,2);
      if(result.handoff)bubble('Simulação: conversa transferida para atendimento humano.');
      else if(result.state==='__finished__')bubble('Simulação: atendimento finalizado.');
    } catch(error) {bubble(error.message);} finally {simBusy=false;submit.disabled=false;}
  }
  function resetTest() {simulation={};$('graph-test-thread').replaceChildren();$('graph-test-input').disabled=false;$('graph-test-input').value='';simulate();}
  $('graph-test').onclick=()=>{$('graph-simulator').showModal();resetTest();};$('graph-close-test').onclick=()=>$('graph-simulator').close();$('graph-test-reset').onclick=resetTest;
  $('graph-test-form').onsubmit=e=>{e.preventDefault();const value=$('graph-test-input').value.trim();if(value){$('graph-test-input').value='';simulate(value);}};
  $('graph-test-resume').onclick=()=>simulate('',true);
  $('master-flow-form').onsubmit=()=>{saveDraft();if($('graph-legacy').checked)graphField.value='';$('id_integrations_json').value=JSON.stringify(integrations);};
  saveDraft();render();integrationEditor();window.addEventListener('resize',()=>draw());
})();
