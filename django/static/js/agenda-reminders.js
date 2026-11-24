// Lembretes da recepção: alerta na tela (e notificação do computador, se permitida) 15 min antes de cada horário.
(() => {
  const source=document.getElementById('ag-alarms-data'),button=document.querySelector('[data-reminder-toggle]'),toast=document.querySelector('[data-reminder-toast]');
  if(!source||!button||!toast)return;
  let alarms=[];try{alarms=JSON.parse(source.textContent)||[];}catch{return;}
  const KEY='agenda-reminders-on',SEEN='agenda-reminders-seen',LEAD=15*60*1000;
  const store={get:(k,d)=>{try{return JSON.parse(localStorage.getItem(k))??d}catch{return d}},set:(k,v)=>{try{localStorage.setItem(k,JSON.stringify(v))}catch{}}};
  let on=store.get(KEY,false);
  const paint=()=>{button.setAttribute('aria-pressed',on?'true':'false');button.textContent=on?'Aviso 15 min antes: ligado':'Avisar 15 min antes de cada horário';};
  const show=a=>{
    toast.replaceChildren();const title=document.createElement('strong');title.textContent=`${a.time} · ${a.patient}`;
    const body=document.createElement('div');body.textContent=`${a.service}${a.professional?' com '+a.professional:''} — ${a.status}`;
    const close=document.createElement('button');close.type='button';close.className='ag-btn';close.textContent='Ok, avisado';close.onclick=()=>{toast.hidden=true;};
    toast.append(title,body,close);toast.hidden=false;
    if('Notification' in window&&Notification.permission==='granted'){try{new Notification(`Paciente às ${a.time}: ${a.patient}`,{body:body.textContent,tag:'agenda-'+a.id});}catch{}}
  };
  const check=()=>{
    if(!on)return;const now=Date.now(),seen=store.get(SEEN,{});
    for(const a of alarms){const at=Date.parse(a.at);if(at-now<=LEAD&&at-now>-5*60*1000&&!seen[a.id]){seen[a.id]=now;store.set(SEEN,seen);show(a);break;}}
    for(const id of Object.keys(seen))if(now-seen[id]>36*3600*1000)delete seen[id];store.set(SEEN,seen);
  };
  button.addEventListener('click',async()=>{on=!on;store.set(KEY,on);paint();
    if(on&&'Notification' in window&&Notification.permission==='default'){try{await Notification.requestPermission();}catch{}}check();});
  // New bookings made after the page opened are picked up every 5 minutes.
  const reload=async()=>{try{const r=await fetch(location.href,{credentials:'same-origin',cache:'no-store'});if(!r.ok)return;
    const page=new DOMParser().parseFromString(await r.text(),'text/html');const next=page.getElementById('ag-alarms-data');if(next)alarms=JSON.parse(next.textContent)||[];}catch{}};
  paint();check();setInterval(check,30000);setInterval(reload,300000);
})();
