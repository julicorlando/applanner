(function () {
  "use strict";
  var strip = document.querySelector("[data-app-install-strip]");
  if (!strip) return;
  var button = strip.querySelector("[data-app-install]");
  var dismiss = strip.querySelector("[data-app-install-dismiss]");
  var dialog = document.querySelector("[data-app-install-dialog]");
  var standalone = window.matchMedia("(display-mode: standalone)");
  var dismissed = false;
  var prompt = null;
  try { dismissed = sessionStorage.getItem("applanner.install-dismissed") === "1"; } catch (error) { /* Optional preference. */ }
  function installed() { return standalone.matches || window.navigator.standalone === true; }
  function refresh() { strip.hidden = installed() || dismissed; }
  refresh();
  standalone.addEventListener("change", refresh);
  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault(); prompt = event; refresh();
  });
  window.addEventListener("appinstalled", function () { prompt = null; strip.hidden = true; });
  dismiss.addEventListener("click", function () {
    dismissed = true; refresh();
    try { sessionStorage.setItem("applanner.install-dismissed", "1"); } catch (error) { /* Optional preference. */ }
  });
  function instructions() {
    var ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    dialog.querySelector("[data-app-install-instructions]").textContent = ios
      ? "No Safari, abra o menu de compartilhamento e escolha ‘Adicionar à Tela de Início’. Se aparecer a opção ‘Abrir como App da Web’, mantenha-a ativada. Depois, abra pelo ícone do ApPlanner."
      : "No menu do navegador, escolha ‘Instalar aplicativo’ ou ‘Adicionar à tela inicial’. Se essa opção não aparecer, abra o ApPlanner no Chrome ou Edge. Depois, abra pelo novo ícone.";
    dialog.showModal();
  }
  button.addEventListener("click", async function () {
    if (!prompt) { instructions(); return; }
    var current = prompt; prompt = null; button.disabled = true;
    try {
      await current.prompt();
      var choice = await current.userChoice;
      if (choice.outcome === "accepted") strip.hidden = true;
    } catch (error) { instructions(); }
    finally { button.disabled = false; }
  });
})();
