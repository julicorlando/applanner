(function(){
  var supported={pt_BR:'Português (Brasil)',pt_PT:'Português (Portugal)',en:'English',es:'Español'};
  var query=new URLSearchParams(location.search), cookie=(document.cookie.match(/(?:^|; )applanner_locale=([^;]+)/)||[])[1];
  var current=query.get('lang')||decodeURIComponent(cookie||'pt_BR');
  if(!supported[current])current='pt_BR';
  document.documentElement.lang=current.replace('_','-');
  var form=document.createElement('form');form.className='ap-language-switcher';form.setAttribute('aria-label','Language');
  var select=document.createElement('select');select.setAttribute('aria-label','Language');
  Object.keys(supported).forEach(function(code){var o=document.createElement('option');o.value=code;o.textContent=supported[code];o.selected=code===current;select.appendChild(o)});
  select.addEventListener('change',function(){var url=new URL(location.href);url.searchParams.set('lang',select.value);location.assign(url.toString())});
  form.appendChild(select);document.body.appendChild(form);
})();
