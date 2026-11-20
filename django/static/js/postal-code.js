/* Same-origin CEP lookup. Number/complement stay with the user; coordinates resolve on save. */
(function () {
  "use strict";
  var script=document.querySelector("script[data-postal-code-url]");
  if (!script) return;
  document.querySelectorAll('form input[name="postal_code"]').forEach(function (cep) {
    var form=cep.form;
    var names=["address","district","city","state"];
    if (!names.every(function (name) { return form.elements.namedItem(name); })) return;
    cep.inputMode="numeric";cep.autocomplete="postal-code";
    var status=document.createElement("small");status.setAttribute("role","status");status.setAttribute("aria-live","polite");cep.insertAdjacentElement("afterend",status);
    var last="",generation=0,controller=null,timer=null;
    function invalidateCoordinates() {
      ["latitude","longitude"].forEach(function (name) { var field=form.elements.namedItem(name);if(field)field.value=""; });
    }
    names.concat(["address_number"]).forEach(function(name){var field=form.elements.namedItem(name);if(field)field.addEventListener("input",invalidateCoordinates);});
    async function lookup() {
      var value=cep.value.replace(/\D/g,"");
      if(value.length!==8){if(cep.value)status.textContent="Informe um CEP com 8 dígitos.";return;}
      if(value===last)return;
      last=value;var current=++generation;
      if(controller)controller.abort();controller=new AbortController();
      var beforeCoordinates={};["latitude","longitude"].forEach(function(name){var field=form.elements.namedItem(name);if(field)beforeCoordinates[name]=field.value;});
      var before={};names.forEach(function(name){before[name]=form.elements.namedItem(name).value;});
      status.textContent="Buscando endereço…";cep.setAttribute("aria-busy","true");
      try {
        var response=await fetch(script.dataset.postalCodeUrl+"?cep="+encodeURIComponent(value),{signal:controller.signal,credentials:"same-origin",headers:{Accept:"application/json"}});
        var data=await response.json();
        if(current!==generation||cep.value.replace(/\D/g,"")!==value)return;
        if(!response.ok){var failure=Error();failure.userMessage=data.error||"Não foi possível consultar o CEP.";throw failure;}
        names.forEach(function(name){var field=form.elements.namedItem(name);if(field.value===before[name])field.value=data[name]||"";});
        ["latitude","longitude"].forEach(function(name){var field=form.elements.namedItem(name);if(field&&field.value===beforeCoordinates[name])field.value="";});
        cep.value=value.slice(0,5)+"-"+value.slice(5);
        status.textContent="Endereço preenchido. Informe o número e confira os dados. Latitude e longitude serão calculadas ao salvar; o ponto pode ser aproximado. Você também pode informá-las manualmente.";
      } catch(error) {
        if(error.name!=="AbortError"&&current===generation){last="";status.textContent=error.userMessage||"Consulta indisponível. Tente novamente ou preencha o endereço manualmente.";}
      } finally {if(current===generation)cep.removeAttribute("aria-busy");}
    }
    cep.addEventListener("input",function(){clearTimeout(timer);last="";generation++;if(controller)controller.abort();cep.removeAttribute("aria-busy");status.textContent="";invalidateCoordinates();timer=setTimeout(lookup,350);});
    cep.addEventListener("blur",function(){clearTimeout(timer);lookup();});
  });
})();
