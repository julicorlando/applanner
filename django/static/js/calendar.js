(() => {
  const board=document.querySelector('.calendar-board');if(!board)return;
  const status=document.getElementById('agenda-live-status');let dragged=null,busy=false;
  const pad=n=>String(n).padStart(2,'0');
  // In the time grid the drop height gives the new time (15-minute steps); in the month view the time is kept.
  const timeAt=(col,event)=>{
    if(!col.dataset.slots)return null;
    const box=col.getBoundingClientRect(),slots=+col.dataset.slots,first=+col.dataset.firstHour;
    const slot=Math.max(0,Math.min(slots-1,Math.floor((event.clientY-box.top)/(box.height/slots))));
    const minutes=first*60+slot*15;return `${pad(Math.floor(minutes/60))}:${pad(minutes%60)}`;
  };
  board.addEventListener('dragstart',event=>{const card=event.target.closest('[data-appointment]');if(!card||busy)return;dragged={id:card.dataset.appointment,time:card.dataset.time};event.dataTransfer.setData('text/plain',card.dataset.appointment);});
  board.addEventListener('dragover',event=>{const col=event.target.closest('[data-calendar-date]');if(dragged&&col){event.preventDefault();board.querySelectorAll('.is-drop').forEach(c=>c!==col&&c.classList.remove('is-drop'));col.classList.add('is-drop');}});
  board.addEventListener('dragend',()=>{dragged=null;board.querySelectorAll('.is-drop').forEach(c=>c.classList.remove('is-drop'));});
  board.addEventListener('drop',async event=>{const day=event.target.closest('[data-calendar-date]');if(!day||!dragged||busy)return;event.preventDefault();day.classList.remove('is-drop');
    const item=dragged;dragged=null;const time=timeAt(day,event)||item.time;const [y,m,d]=day.dataset.calendarDate.split('-');
    if(!window.confirm(`Mover para ${d}/${m}/${y} às ${time}?`))return;busy=true;if(status)status.textContent='Verificando disponibilidade…';
    try{const response=await fetch(`/app/agenda/agendamentos/${encodeURIComponent(item.id)}/mover/`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('#calendar-csrf [name=csrfmiddlewaretoken]').value},body:JSON.stringify({starts_at:`${day.dataset.calendarDate}T${time}:00`})});const data=await response.json();
      if(status)status.textContent=data.detail;if(response.ok)window.location.reload();else window.alert(data.detail);}
    catch{const msg='Não foi possível confirmar a alteração. Atualize a agenda antes de tentar novamente.';if(status)status.textContent=msg;window.alert(msg);}finally{busy=false;}
  });
})();
