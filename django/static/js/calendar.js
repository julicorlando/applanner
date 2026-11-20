(() => {
  const board=document.querySelector('.calendar-board');if(!board)return;
  const status=document.getElementById('agenda-live-status');let dragged=null,busy=false;
  board.addEventListener('dragstart',event=>{const card=event.target.closest('[data-appointment]');if(!card||busy)return;dragged={id:card.dataset.appointment,time:card.dataset.time};event.dataTransfer.setData('text/plain',card.dataset.appointment);});
  board.addEventListener('dragover',event=>{if(dragged&&event.target.closest('[data-calendar-date]'))event.preventDefault();});
  board.addEventListener('dragend',()=>dragged=null);
  board.addEventListener('drop',async event=>{const day=event.target.closest('[data-calendar-date]');if(!day||!dragged||busy)return;event.preventDefault();const item=dragged;dragged=null;if(!window.confirm(`Mover para ${day.dataset.calendarDate} às ${item.time}?`))return;busy=true;status.textContent='Verificando disponibilidade…';
    try{const response=await fetch(`/app/agenda/agendamentos/${encodeURIComponent(item.id)}/mover/`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('#calendar-csrf [name=csrfmiddlewaretoken]').value},body:JSON.stringify({starts_at:`${day.dataset.calendarDate}T${item.time}:00`})});const data=await response.json();status.textContent=data.detail;if(response.ok)window.location.reload();}catch{status.textContent='Não foi possível confirmar a alteração. Atualize a agenda antes de tentar novamente.';}finally{busy=false;}
  });
})();
