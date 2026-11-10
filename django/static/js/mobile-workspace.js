(function () {
  "use strict";
  var trigger = document.querySelector("[data-mobile-menu]");
  var menu = document.querySelector(".mobile-nav");
  if (!trigger || !menu) return;
  menu.id = "mobile-workspace-menu";
  trigger.setAttribute("aria-controls", menu.id);
  trigger.setAttribute("aria-expanded", String(menu.open));
  trigger.addEventListener("click", function () {
    menu.open = !menu.open;
    trigger.setAttribute("aria-expanded", String(menu.open));
    if (menu.open) { var first = menu.querySelector("a,button"); if (first) first.focus(); }
  });
  menu.addEventListener("toggle", function () { trigger.setAttribute("aria-expanded", String(menu.open)); });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && menu.open) { menu.open = false; trigger.focus(); }
  });
})();
