(async function(){
 const root=document.getElementById('arena-card-payment'); if(!root||!window.MercadoPago)return;
 const message=root.querySelector('[data-card-message]');
 function show(text,ok){message.textContent=text;message.className='alert mt-2 '+(ok?'alert-success':'alert-danger');}
 try{
  const mp=new MercadoPago(root.dataset.publicKey,{locale:'pt-BR'}); const bricks=mp.bricks();
  await bricks.create('cardPayment','cardPaymentBrick_container',{
    initialization:{amount:Number(root.dataset.amount)},
    callbacks:{
      onReady:function(){},
      onSubmit:async function(formData){
        try{
          const payload=Object.assign({},formData,{attempt_id:(crypto.randomUUID?crypto.randomUUID():String(Date.now())+'-'+Math.random())});
          const csrf=document.querySelector('meta[name="csrf-token"]')?.content||'';
          const response=await fetch(root.dataset.endpoint,{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(payload)});
          const data=await response.json(); if(!response.ok||!data.ok)throw new Error(data.message||'Pagamento recusado.');
          show(data.message||'Pagamento processado.',data.status==='paid'); if(data.status==='paid')setTimeout(function(){location.reload();},900);
        }catch(e){show(e.message||'Não foi possível processar o pagamento.',false);throw e;}
      },
      onError:function(){show('Não foi possível carregar o pagamento por cartão.',false);}
    }
  });
 }catch(e){show('Não foi possível iniciar o pagamento por cartão.',false);}
})();
