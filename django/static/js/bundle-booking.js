(() => {
  const form=document.getElementById('bundle-booking');if(!form)return;
  const unit=document.getElementById('bundle-unit'),date=document.getElementById('bundle-date'),slot=document.getElementById('bundle-slot');
  const container=document.getElementById('bundle-items'),summary=document.getElementById('bundle-preview'),feedback=document.getElementById('bundle-feedback'),submit=document.getElementById('bundle-submit');
  const csrf=form.querySelector('[name=csrfmiddlewaretoken]').value,url=`/api/public/${encodeURIComponent(form.dataset.slug)}/bundle/`;
  let previewId=0,confirmed=false;
  const items=()=>[...container.querySelectorAll('.bundle-item')].map(row=>({service_id:row.querySelector('.bundle-service').value,professional_id:row.querySelector('.bundle-professional').value}));
  const base=()=>({unit_id:unit.value,starts_at:slot.value,items:items()});
  const picker=createBookingSlotPicker({container:document.getElementById('bundle-slots'),input:slot,status:document.getElementById('bundle-slot-status'),onChange:(selected)=>{previewId++;submit.disabled=true;summary.replaceChildren();if(selected)preview();}});
  async function preview(){
    const id=previewId;summary.textContent='Conferindo a sequência completa…';
    try{const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify({...base(),preview:true})});const data=await response.json();if(id!==previewId)return;
      summary.replaceChildren();if(!response.ok){summary.textContent=data.detail;return;}
      data.items.forEach(row=>{const p=document.createElement('p');p.textContent=`${row.service} · ${row.professional} · ${new Intl.DateTimeFormat('pt-BR',{timeStyle:'short',timeZone:form.dataset.timezone}).format(new Date(row.starts_at))} · ${new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(Number(row.price))}`;summary.appendChild(p);});const total=document.createElement('strong');total.textContent=`Total dos serviços: ${new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(Number(data.total))}`;summary.appendChild(total);submit.disabled=false;
    }catch{if(id===previewId)summary.textContent='Não foi possível conferir a sequência. Selecione o início novamente.';}
  }
  function refresh(){if(confirmed)return;previewId++;submit.disabled=true;summary.replaceChildren();const rows=items();if(rows.some(row=>!row.service_id)){picker.reset('Escolha todos os serviços.');return;}const q=new URLSearchParams({unit_id:unit.value,service_id:rows[0].service_id,date:date.value});if(rows[0].professional_id)q.set('professional_id',rows[0].professional_id);picker.load(`/api/public/${encodeURIComponent(form.dataset.slug)}/availability/?${q}`);}
  container.addEventListener('change',refresh);container.addEventListener('click',event=>{if(event.target.classList.contains('bundle-remove')){event.target.closest('.bundle-item').remove();refresh();}});
  document.getElementById('bundle-add').addEventListener('click',()=>{if(container.children.length>=5)return;const row=container.firstElementChild.cloneNode(true);row.querySelectorAll('select').forEach(select=>select.selectedIndex=0);row.querySelector('.bundle-remove').hidden=false;container.appendChild(row);refresh();});
  date.addEventListener('change',refresh);unit.addEventListener('change',()=>location.assign(`?unit=${encodeURIComponent(unit.value)}`));
  form.addEventListener('submit',async event=>{event.preventDefault();if(confirmed||submit.disabled||!form.reportValidity())return;submit.disabled=true;feedback.textContent='Confirmando os serviços…';const payload={...base(),name:document.getElementById('bundle-name').value,phone:document.getElementById('bundle-phone').value,email:document.getElementById('bundle-email').value,payment_choice:document.getElementById('bundle-payment').value};
    try{const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf,'Idempotency-Key':form.dataset.key},body:JSON.stringify(payload)});const data=await response.json();feedback.replaceChildren();if(!response.ok){feedback.textContent=data.detail;submit.disabled=false;return;}confirmed=true;feedback.textContent='Sequência confirmada. Acompanhe cada serviço:';data.items.forEach(row=>{const p=document.createElement('p'),a=document.createElement('a');a.href=row.manage_url;a.textContent=`${row.service.name} · ${row.professional.name} — acompanhar / pagar`;p.appendChild(a);feedback.appendChild(p);});form.querySelectorAll('input,select,button').forEach(field=>field.disabled=true);}catch{feedback.textContent='A confirmação não foi recebida. Tente novamente sem alterar os dados; a reserva não será duplicada.';submit.disabled=false;}
  });
})();
