(() => {
  'use strict';
  const $=id=>document.getElementById(id), panel=$('tv-panel');
  let voice=false, started=false, lastCall=null, media=[], index=0, timer, lastOk=0;
  const node=(tag,value)=>{const el=document.createElement(tag);el.textContent=value;return el;};
  $('tv-link').textContent=location.host+location.pathname;
  $('tv-start').onclick=()=>{started=true;document.documentElement.requestFullscreen?.().catch(()=>{});$('tv-start').hidden=true;showMedia();};
  function showMedia(){
    clearTimeout(timer);const host=$('tv-media');host.replaceChildren();
    if(!media.length){const el=node('div','Bem-vindo! Cuide do seu bem-estar.');el.className='tv-welcome';host.append(el);return;}
    const item=media[index%media.length];index++;
    const el=document.createElement(item.mime==='video/mp4'?'video':'img');el.src=item.url;
    if(el.tagName==='VIDEO'){el.muted=true;el.autoplay=true;el.playsInline=true;el.onended=showMedia;el.onerror=()=>{timer=setTimeout(showMedia,5000);};el.play().catch(()=>{});timer=setTimeout(showMedia,300000);}
    else {el.alt=item.title;timer=setTimeout(showMedia,12000);}
    host.append(el);
  }
  function clearPrivate(message){$('tv-current').textContent='Aguarde a chamada';$('tv-history').replaceChildren();$('tv-connection').textContent=message;lastCall=null;}
  async function refresh(){
    try{
      const response=await fetch(panel.dataset.feed,{cache:'no-store',credentials:'omit',signal:AbortSignal.timeout(10000)});
      if(!response.ok){clearPrivate(response.status===404?'Painel desativado ou link revogado.':'Painel temporariamente indisponível.');clearTimeout(timer);$('tv-media').replaceChildren();media=[];return;}
      const data=await response.json();lastOk=Date.now();$('tv-connection').textContent='';$('tv-title').textContent=data.title;voice=data.voice;
      const [current,...previous]=data.calls;
      if(current){
        $('tv-current').replaceChildren(node('span',current.name),node('small',current.room));
        if(lastCall!==null&&current.id!==lastCall&&started&&voice&&'speechSynthesis'in window){speechSynthesis.cancel();const utterance=new SpeechSynthesisUtterance(`${current.name}. Dirija-se à ${current.room}.`);utterance.lang='pt-BR';speechSynthesis.speak(utterance);}
        lastCall=current.id;
      }else{clearPrivate('');}
      $('tv-history').replaceChildren();for(const call of previous){const el=node('div','');el.className='tv-row';el.append(node('span',call.name),node('span',call.room));$('tv-history').append(el);}
      if(JSON.stringify(media)!==JSON.stringify(data.media)){media=data.media;index=0;showMedia();}
    }catch{
      $('tv-connection').textContent='Sem conexão · aguardando atualização';
      // Never leave patient aliases visible indefinitely on a disconnected TV.
      if(Date.now()-lastOk>60000)clearPrivate('Sem conexão · chamadas ocultas até reconectar');
    }
  }
  function tick(){$('tv-clock').textContent=new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});}
  tick();refresh();setInterval(tick,1000);setInterval(refresh,5000);
})();
