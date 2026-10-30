/* Explicit opt-in; encryption key lives only in this tab's memory. */
(async () => {
  'use strict';
  const $ = id => document.getElementById(id), vault = globalThis.ClinicVault;
  let state, key, salt, release, syncing=false, busy=false, touched=Date.now(), hiddenAt=0;
  const status = message => { $('co-status').textContent = message; };
  const text = (tag, value, className='') => { const node=document.createElement(tag);node.textContent=value;node.className=className;return node; };
  const expired = () => !state || new Date(state.snapshot.expires_at).getTime() <= Date.now();
  const localTime = () => { const now=new Date();return new Date(now-now.getTimezoneOffset()*60000).toISOString().slice(0,16); };
  const connection = () => { $('co-connection').textContent=navigator.onLine?'Conectado · confirmação pelo servidor':'Sem conexão · lançamentos pendentes'; };
  connection();
  async function acquire() {
    if (!navigator.locks) throw Error('Este navegador não oferece proteção contra edição simultânea. Use uma versão atual do Chrome, Edge, Firefox ou Safari.');
    await new Promise((resolve,reject) => {
      navigator.locks.request('applanner-clinic-vault', {ifAvailable:true}, async lock => {
        if (!lock) { reject(Error('O cofre está aberto em outra aba. Bloqueie a outra aba primeiro.'));return; }
        await new Promise(done => { release=done;resolve(); });
      }).catch(reject);
    });
  }
  function lock() {
    state=key=salt=undefined;release?.();release=undefined;
    $('co-work').hidden=true;$('co-lock').hidden=false;
    // Remove PHI from DOM and inputs, not just visually hidden containers.
    for (const id of ['co-queue','co-agenda','co-patients','co-identity','co-downloaded']) $(id).replaceChildren();
    document.querySelectorAll('#co-work form').forEach(form => form.reset());
    document.querySelectorAll('#co-work select').forEach(select => select.replaceChildren());
    $('co-password').value='';status('Cofre bloqueado.');
  }
  async function persist() { if (!state || !key) throw Error('Cofre bloqueado.');await vault.save(await vault.seal(state,key,salt)); }
  async function serverSnapshot() {
    const response=await fetch('/app/clinica/operacao/snapshot/', {credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000),headers:{Accept:'application/json'}});
    if (!response.ok || !response.headers.get('Content-Type')?.includes('application/json')) throw Error('Entre na sua conta da clínica e confira suas permissões antes de sincronizar.');
    return response.json();
  }
  async function prepareShell() {
    const registration=await navigator.serviceWorker.ready;
    const worker=registration.active;
    await new Promise((resolve,reject) => {
      const channel=new MessageChannel();const timeout=setTimeout(()=>reject(Error('Não foi possível preparar a página offline. Tente novamente conectado.')),20000);
      channel.port1.onmessage=event=>{clearTimeout(timeout);event.data?.ok?resolve():reject(Error('Não foi possível preparar os arquivos offline.'));};
      worker.postMessage({type:'CLINICAL_PREPARE'},[channel.port2]);
    });
    if (navigator.storage?.persist) await navigator.storage.persist();
  }
  $('co-unlock').addEventListener('submit', async event => {
    event.preventDefault();if(busy)return;busy=true;
    try {
      if (!isSecureContext || !crypto.subtle || !navigator.serviceWorker) throw Error('Use HTTPS e um navegador com criptografia e suporte offline.');
      await acquire();
      const stored=await vault.load(), password=$('co-password').value;
      if (stored) { const opened=await vault.open(stored,password);state=opened.value;key=opened.key;salt=opened.salt; }
      else {
        const snapshot=await serverSnapshot();
        await prepareShell();salt=crypto.getRandomValues(new Uint8Array(16));key=await vault.derive(password,salt);
        state={snapshot,queue:[]};await persist();
      }
      $('co-password').value='';touched=Date.now();$('co-lock').hidden=true;$('co-work').hidden=false;render();
      if(navigator.onLine) await sync();
    } catch(error) { lock();status(error.message); }
    finally { busy=false; }
  });
  function option(select,value,label) { const node=document.createElement('option');node.value=value;node.textContent=label;select.append(node); }
  function render() {
    if (!state)return;
    const snap=state.snapshot, patients=[...snap.patients,...state.queue.filter(x=>x.kind==='customer').map(x=>({...x.data,id:'local:'+x.id}))];
    $('co-identity').textContent=`${snap.company} · ${snap.user}`;
    $('co-downloaded').textContent=`Cópia de ${new Date(snap.downloaded_at).toLocaleString('pt-BR')} · validade até ${new Date(snap.expires_at).toLocaleString('pt-BR')}. Limites: 1.000 pacientes, 500 atendimentos e 100 registros recentes. ${Object.values(snap.truncated).some(Boolean)?'A lista foi limitada; consulte os demais dados online.':''}`;
    $('co-sensitive').hidden=expired();
    $('co-evolution-card').hidden=!snap.permissions.clinical;
    $('co-queue').replaceChildren();
    for (const op of state.queue) {
      const row=text('div',`${({customer:'Paciente',appointment:'Agendamento',evolution:'Evolução',checkin:'Chegada',cash:'Dinheiro recebido'})[op.kind]} · ${op.id.slice(0,8)} · ${op.error||'Pendente de confirmação'}`,'co-item');
      if(op.error)row.classList.add('co-error');
      const details=document.createElement('details');details.append(text('summary','Revisar lançamento'));
      for(const [name,value] of Object.entries(op.data)) {
        if(['version','attestation'].includes(name))continue;
        const labels={name:'Nome',phone:'Telefone',email:'E-mail',birth_date:'Nascimento',customer:'Paciente',professional:'Profissional',service:'Serviço',appointment:'Atendimento',starts_at:'Data do agendamento',occurred_at:'Data do registro',content:'Evolução',amount:'Valor recebido',method:'Forma'};
        const label=labels[name]||name;details.append(text('p',`${label}: ${value}`));
      }
      if(op.error && op.revisable){
        const edit=text('button','Corrigir lançamento pendente');edit.type='button';edit.disabled=syncing;
        edit.onclick=()=>run(async()=>{
          const before=structuredClone(state), draft=structuredClone(op.data);
          const fields=op.kind==='customer'?['name','phone','email','birth_date']:op.kind==='evolution'?['content']:op.kind==='appointment'?['starts_at']:[];
          if(!fields.length){
            const current=state.snapshot.appointments.find(x=>x.id===op.data.appointment);
            if(!current)throw Error('Atendimento não está na cópia atual. Confira-o online.');
            if(!confirm(`Revisar operação usando o estado atual do atendimento (${current.status})? Confirme os valores antes de reenviar.`))return;
            draft.version=current.version;
          }
          for(const field of fields){const value=prompt(`Corrigir ${({name:'nome',phone:'telefone',email:'e-mail',birth_date:'nascimento (AAAA-MM-DD)',content:'evolução',starts_at:'data e hora com fuso (ISO)'})[field]}`,draft[field]||'');if(value===null)return;draft[field]=value;}
          op.data=draft;delete op.error;delete op.revisable;
          try{await persist();}catch(error){state=before;throw error;}render();
        });details.append(edit);
      }
      row.append(details);
      const remove=text('button','Descartar da fila');remove.type='button';remove.disabled=syncing;
      remove.onclick=()=>run(async()=>{
        if(!confirm('Descartar este lançamento local? Ele não será enviado ao servidor.'))return;
        if(op.kind==='customer' && state.queue.some(x=>x.data.customer==='local:'+op.id))throw Error('Existem lançamentos vinculados a este paciente. Revise-os antes de descartá-lo.');
        const before=state.queue;state.queue=state.queue.filter(x=>x.id!==op.id);try{await persist();}catch(error){state.queue=before;throw error;}render();
      });row.append(document.createElement('br'),remove);$('co-queue').append(row);
    }
    document.querySelectorAll('[data-patients]').forEach(select=>{const selected=select.value;select.replaceChildren();option(select,'','Selecione');patients.forEach(p=>option(select,p.id,p.name+(String(p.id).startsWith('local:')?' · pendente':'')));select.value=selected;});
    const booking=$('co-appointment');for(const [name,list] of [['professional',snap.professionals],['service',snap.services]]){const select=booking.elements[name],selected=select.value;select.replaceChildren();list.forEach(p=>option(select,p.id,p.name));if(selected)select.value=selected;}
    const select=$('co-evolution').elements.appointment, selectedAppointment=select.value;select.replaceChildren();option(select,'','Sem atendimento');snap.appointments.forEach(a=>option(select,a.id,`${a.customer_name} · ${new Date(a.starts_at).toLocaleString('pt-BR')}`));select.value=selectedAppointment;
    if(!$('co-evolution').elements.occurred_at.value)$('co-evolution').elements.occurred_at.value=localTime();
    const term=$('co-filter').value.toLocaleLowerCase('pt-BR');
    $('co-agenda').replaceChildren();$('co-patients').replaceChildren();
    if(!expired()) {
      for(const a of snap.appointments.filter(a=>a.customer_name.toLocaleLowerCase('pt-BR').includes(term))){
        const row=text('div','', 'co-item');row.append(text('strong',`${a.customer_name} · ${a.service_name}`),text('p',`${new Date(a.starts_at).toLocaleString('pt-BR')} · ${a.status}`));
        if(['pending','confirmed'].includes(a.status)){const button=text('button','Registrar chegada');button.disabled=state.queue.some(x=>x.kind==='checkin'&&x.data.appointment===a.id);button.onclick=()=>queue('checkin',{appointment:a.id,version:a.version,occurred_at:new Date().toISOString()});row.append(button);}
        if(snap.permissions.cash && ['pending','confirmed','waiting','in_progress'].includes(a.status)){
          const button=text('button',`Concluir · dinheiro recebido: R$ ${a.price}`);button.disabled=state.queue.some(x=>x.kind==='cash'&&x.data.appointment===a.id);button.onclick=()=>{if(confirm(`Confirma a conclusão do atendimento e o recebimento integral de R$ ${a.price} em dinheiro? O servidor conciliará ao reconectar.`))queue('cash',{appointment:a.id,version:a.version,method:'cash',amount:a.price,occurred_at:new Date().toISOString()});};row.append(button);
        }$('co-agenda').append(row);
      }
      for(const p of patients.filter(p=>`${p.name} ${p.phone}`.toLocaleLowerCase('pt-BR').includes(term))){
        const details=document.createElement('details');details.className='co-item';details.append(text('summary',`${p.name} · ${p.phone||'sem telefone'}`));
        for(const entry of snap.entries.filter(x=>x.customer===p.id)){details.append(text('h3',entry.title),text('small',new Date(entry.at).toLocaleString('pt-BR')),text('pre',entry.content));}
        $('co-patients').append(details);
      }
    }
    status(expired()?'Cópia expirada. Conecte para atualizar e revisar a fila. Os lançamentos pendentes foram preservados.':`${state.queue.length} lançamento(s) pendente(s). ${navigator.onLine?'Sincronização disponível.':'Operando sem internet.'}`);
  }
  async function run(action) {if(busy||syncing)return;busy=true;try{await action();}catch(error){status(error.message);}finally{busy=false;}}
  function queue(kind,data){let saved=false;return run(async()=>{
    if(expired())throw Error('Atualize a cópia antes de novos lançamentos.');
    if(state.queue.length>=200)throw Error('Limite de 200 lançamentos locais atingido. Sincronize antes de continuar.');
    if(state.queue.some(x=>x.kind===kind&&JSON.stringify(x.data)===JSON.stringify(data)))throw Error('Este lançamento já está na fila.');
    const op={id:crypto.randomUUID(),scope:state.snapshot.scope,kind,data};state.queue.push(op);
    try{await persist();}catch(error){state.queue.pop();throw error;}saved=true;
    if(['customer','appointment','evolution'].includes(kind))$('co-'+({customer:'patient',appointment:'appointment',evolution:'evolution'})[kind]).reset();
    render();status('Salvo no cofre local. Pendente de confirmação pelo servidor.');
  }).then(()=>{if(saved&&navigator.onLine)return sync();});}
  $('co-patient').onsubmit=event=>{event.preventDefault();queue('customer',Object.fromEntries(new FormData(event.target)));};
  $('co-appointment').onsubmit=event=>{event.preventDefault();const data=Object.fromEntries(new FormData(event.target));data.starts_at=new Date(data.starts_at).toISOString();queue('appointment',data);};
  $('co-evolution').onsubmit=event=>{event.preventDefault();const data=Object.fromEntries(new FormData(event.target));data.attestation=true;data.occurred_at=new Date(data.occurred_at).toISOString();queue('evolution',data);};
  $('co-filter').oninput=render;
  async function sync() {
    if(syncing||!state||!navigator.onLine)return;
    syncing=true;render();
    try {
      const current=await serverSnapshot();
      if(current.scope!==state.snapshot.scope){lock();throw Error('Conta ou clínica diferente. Entre na conta que criou este cofre; nenhuma operação foi enviada.');}
      const token=document.cookie.split('; ').find(x=>x.startsWith('csrftoken='))?.split('=').slice(1).join('=');
      if(!token)throw Error('Atualize o login para sincronizar com segurança.');
      for(const op of [...state.queue]) {
        // Keep the original content/UUID for retries after ambiguous network failures.
        const body={id:op.id,scope:op.scope,kind:op.kind,data:op.data};
        const response=await fetch('/app/clinica/operacao/sincronizar/',{method:'POST',credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000),headers:{'Content-Type':'application/json','X-CSRFToken':token},body:JSON.stringify(body)});
        if(!response.headers.get('Content-Type')?.includes('application/json')){op.error='Sessão ou permissão indisponível. Faça login e tente novamente.';await persist();break;}
        const payload=await response.json();
        if(!response.ok){op.error=payload.detail||'Acesso negado. Revise as permissões online.';op.revisable=response.status===409;await persist();break;}
        const before=structuredClone(state);
        state.queue=state.queue.filter(x=>x.id!==op.id);
        if(op.kind==='customer'){
          for(const next of state.queue)if(next.data.customer==='local:'+op.id)next.data.customer=payload.result.customer;
        }
        if(payload.result.version)for(const next of state.queue)if(next.data.appointment===payload.result.appointment && next.data.version===op.data.version)next.data.version=payload.result.version;
        try{await persist();}catch(error){state=before;throw error;}
      }
      state.snapshot=await serverSnapshot();await persist();render();
    } catch(error) {status(error.message);}
    finally {syncing=false;if(state)render();}
  }
  $('co-sync').onclick=()=>{if(!busy)sync();};
  $('co-refresh').onclick=()=>run(async()=>{const snap=await serverSnapshot();if(snap.scope!==state.snapshot.scope){lock();throw Error('Faça login na conta original deste cofre.');}await prepareShell();state.snapshot=snap;await persist();render();});
  $('co-export').onclick=()=>run(async()=>{const sealed=await vault.load();const url=URL.createObjectURL(new Blob([JSON.stringify(sealed)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='applanner-cofre-criptografado.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  $('co-lock-button').onclick=()=>{if(!busy&&!syncing)lock();};
  $('co-erase').onclick=()=>run(async()=>{
    if(!confirm('Apagar a cópia local e TODOS os lançamentos ainda não sincronizados deste dispositivo? Esta ação não altera o servidor.'))return;
    await acquire();try{await vault.erase();}finally{lock();}status('Cópia local apagada.');
  });
  addEventListener('offline',connection);addEventListener('online',()=>{connection();if(!busy)sync();});
  for(const type of ['pointerdown','keydown','touchstart'])addEventListener(type,()=>{touched=Date.now();},{passive:true});
  document.addEventListener('visibilitychange',()=>{hiddenAt=document.hidden?Date.now():hiddenAt;if(!document.hidden && hiddenAt && Date.now()-hiddenAt>60000&&!busy&&!syncing)lock();});
  setInterval(()=>{if(state&&!busy&&!syncing&&(Date.now()-touched>300000||(document.hidden&&Date.now()-hiddenAt>60000)))lock();},5000);
  addEventListener('beforeunload',event=>{if(state?.queue.length){event.preventDefault();event.returnValue='';}});
})();
