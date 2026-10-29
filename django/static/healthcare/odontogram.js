/* FDI schematic: patient right appears on the viewer's left. No clinical data
   is transmitted; the containing form persists an encrypted encounter. */
(function () {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const colors = {higido:'#dceee7',carie:'#dc3545',restauracao:'#2474ca',ausente:'#94a3b8',extracao_indicada:'#ea580c',endodontia:'#8b5cf6',coroa:'#ca8a04',implante:'#475569',fratura:'#db2777',selante:'#0891b2',protese:'#a16207',outro:'#64748b'};
  function svg(tag, attrs) { const node=document.createElementNS(NS,tag); Object.entries(attrs||{}).forEach(([k,v])=>node.setAttribute(k,v)); return node; }
  function setup(root) {
    const field = root.querySelector('[data-chart-input]');
    let chart={}; try { chart=JSON.parse(field.value||'{}'); } catch (_) { /* server displays validation error */ }
    const selected=new Set(), surfaces=new Set();
    const canvas=root.querySelector('[data-arches]');
    const status=root.querySelector('[data-selection]');
    const readonly=root.dataset.readonly==='true';
    let primary=false;
    function draw() {
      canvas.replaceChildren();
      const board=svg('svg',{viewBox:'0 0 800 620',role:'group','aria-label':'Arcadas dentárias FDI'});
      for (const [lower, quadrants] of [[false,primary?[5,6]:[1,2]],[true,primary?[8,7]:[4,3]]]) {
        const max=primary?5:8, ids=[];
        for(let n=max;n>=1;n--)ids.push(`${quadrants[0]}${n}`);
        for(let n=1;n<=max;n++)ids.push(`${quadrants[1]}${n}`);
        const label=svg('text',{x:400,y:lower?600:25,'text-anchor':'middle',fill:'#334155','font-size':18});
        label.textContent=lower?'Arcada inferior':'Arcada superior';board.append(label);
        ids.forEach((id,i)=>{
          const angle=Math.PI*(i/(ids.length-1)), x=400-345*Math.cos(angle);
          const y=lower?360+155*Math.sin(angle):260-155*Math.sin(angle);
          const group=svg('g',{transform:`translate(${x},${y})`,tabindex:readonly?-1:0,role:'button','aria-label':`Dente ${id}`,'aria-pressed':selected.has(id),'data-tooth':id});
          const n=Number(id[1]),molar=n>=6,canine=n===3;
          // Crown and anatomically distinct root silhouettes, kept schematic.
          const rootPath=molar?'M-18,18 Q-24,59 -10,52 L0,26 L10,52 Q24,59 18,18':canine?'M-13,18 Q-7,72 0,59 Q7,50 13,18':'M-15,18 Q-6,61 0,54 Q6,50 15,18';
          group.append(svg('path',{d:rootPath,fill:'#f8fafc',stroke:'#94a3b8','stroke-width':2,transform:lower?'scale(1,-1)':''}));
          const observations=chart[id]||[];
          const condition=observations.filter(o=>!o.surfaces.length).at(-1)?.condition||'higido';
          const crown=svg('rect',{x:-23,y:-24,width:46,height:45,rx:molar?12:canine?17:7,fill:colors[condition],stroke:selected.has(id)?'#0f766e':'#64748b','stroke-width':selected.has(id)?4:1.5});group.append(crown);
          const paths={vestibular:'M-22,-23 L22,-23 L10,-10 L-10,-10Z',lingual:'M-22,20 L22,20 L10,9 L-10,9Z',mesial:'M-22,-23 L-10,-10 L-10,9 L-22,20Z',distal:'M22,-23 L10,-10 L10,9 L22,20Z',oclusal:'M-10,-10 L10,-10 L10,9 L-10,9Z'};
          Object.entries(paths).forEach(([position,d])=>{
            let face=position;
            if(['1','4','5','8'].includes(id[0]) && ['mesial','distal'].includes(face))face=face==='mesial'?'distal':'mesial';
            if(!lower && face==='lingual')face='palatina';
            if(n<=3 && face==='oclusal')face='incisal';
            const marked=observations.filter(o=>o.surfaces.includes(face)).at(-1);
            const p=svg('path',{d,fill:marked?colors[marked.condition]:'transparent',stroke:'#ffffff99','stroke-width':1,'data-face':face});group.append(p);
          });
          const text=svg('text',{x:0,y:lower?-36:83,'text-anchor':'middle','font-size':16,fill:'#334155'});text.textContent=id;group.append(text);
          if(condition==='ausente'){group.append(svg('path',{d:'M-18,-18 L18,17 M18,-18 L-18,17',stroke:'#fff','stroke-width':3}));}
          function toggle(event){if(readonly)return; if(selected.has(id))selected.delete(id);else selected.add(id); if(event.target.dataset.face){surfaces.clear();surfaces.add(event.target.dataset.face);root.querySelectorAll('[data-surface]').forEach(b=>{b.checked=surfaces.has(b.value);});}refresh();}
          group.addEventListener('click',toggle);
          group.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle(e);}});
          board.append(group);
        });
      }
      canvas.append(board);
    }
    function refresh(){field.value=JSON.stringify(chart);draw();status.textContent=selected.size?'Dentes selecionados: '+[...selected].join(', '):'Selecione um ou mais dentes';const summary=root.querySelector('[data-chart-summary]');summary.replaceChildren();Object.entries(chart).forEach(([id,items])=>{const line=document.createElement('p');line.textContent=`${id}: ${items.map(o=>`${o.condition} · ${o.surfaces.join(', ')} · ${o.note}`).join('; ')}`;summary.append(line);});}
    root.querySelectorAll('[data-dentition]').forEach(b=>b.addEventListener('click',()=>{primary=b.dataset.dentition==='primary';selected.clear();refresh();}));
    root.querySelectorAll('[data-surface]').forEach(b=>b.addEventListener('change',()=>{if(b.checked)surfaces.add(b.value);else surfaces.delete(b.value);}));
    root.querySelector('[data-add]')?.addEventListener('click',()=>{if(!selected.size){status.textContent='Selecione pelo menos um dente.';return;}selected.forEach(id=>{(chart[id]??=[]).push({condition:root.querySelector('[data-condition]').value,surfaces:[...surfaces],note:root.querySelector('[data-note]').value});});refresh();});
    root.querySelector('[data-clear]')?.addEventListener('click',()=>{selected.forEach(id=>delete chart[id]);refresh();});
    const legend=root.querySelector('[data-legend]');Object.entries(colors).forEach(([name,color])=>{const item=document.createElement('span');item.style.borderLeft=`12px solid ${color}`;item.style.padding='0 10px 0 5px';item.textContent=name.replaceAll('_',' ');legend.append(item);});
    root.addEventListener('odontogram:load',event=>{chart=event.detail||{};selected.clear();refresh();});
    const patient=document.getElementById('id_customer'),form=root.closest('form');
    if(!readonly&&patient&&form?.dataset.chartUrl){
      let pending,epoch=0;
      patient.addEventListener('change',async()=>{
        const current=++epoch;pending?.abort();pending=new AbortController();chart={};selected.clear();refresh();
        if(!/^\d+$/.test(patient.value))return;
        try{const response=await fetch(form.dataset.chartUrl.replace('/0/','/'+patient.value+'/'),{credentials:'same-origin',signal:pending.signal,headers:{Accept:'application/json'}});
          if(!response.ok)throw new Error('unavailable');
          const result=await response.json();if(current!==epoch)return;chart=result.odontogram||{};refresh();
        }catch(error){if(current===epoch&&error.name!=='AbortError')status.textContent='Não foi possível carregar o odontograma anterior. Confira o histórico antes de salvar.';}
      });
    }
    refresh();
  }
  document.querySelectorAll('[data-odontogram]').forEach(setup);
})();
