(function(){
 var page=document.querySelector('[data-meta-pixel-id]');if(!page)return;var id=page.dataset.metaPixelId;
 function load(){if(!/^\d{5,30}$/.test(id)||window.fbq)return;!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}(window,document,'script','https://connect.facebook.net/en_US/fbevents.js');fbq('init',id);fbq('track','PageView')}
 var consent=localStorage.getItem('applanner_marketing_consent');if(consent==='yes'){load();return}if(consent==='no'||!id)return;
 var box=document.createElement('div');box.className='ap-consent';box.innerHTML='<p><strong>Privacidade e desempenho</strong><br>Podemos usar dados de navegação para medir campanhas e melhorar esta página.</p><div><button type="button" data-no>Agora não</button><button type="button" data-yes>Permitir medição</button></div>';document.body.appendChild(box);
 box.querySelector('[data-no]').onclick=function(){localStorage.setItem('applanner_marketing_consent','no');box.remove()};box.querySelector('[data-yes]').onclick=function(){localStorage.setItem('applanner_marketing_consent','yes');box.remove();load()};
 document.addEventListener('click',function(e){var a=e.target.closest('a[href*="cadastro"],a[href*="interesse-comercial"]');if(a&&window.fbq)fbq('track','Lead')});
})();
