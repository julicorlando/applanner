/* Apply before styles load so navigation never flashes the other theme. */
(function () {
  "use strict";
  var key = "applanner.theme";
  var preference = null;
  var media = window.matchMedia("(prefers-color-scheme: dark)");
  try { preference = window.localStorage.getItem(key); } catch (error) { /* Private storage can be unavailable. */ }
  function apply(theme) {
    var dark = theme === "dark";
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
      var label = dark ? "Ativar tema claro" : "Ativar tema escuro";
      button.setAttribute("aria-label", label);
      button.setAttribute("title", label);
      button.setAttribute("aria-pressed", String(dark));
    });
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = dark ? "#101722" : "#f5f7fa";
  }
  function preferredTheme() { return preference === "dark" || preference === "light" ? preference : media.matches ? "dark" : "light"; }
  apply(preferredTheme());
  document.addEventListener("DOMContentLoaded", function () {
    apply(preferredTheme());
    document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
      button.addEventListener("click", function () {
        preference = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
        apply(preference);
        try { window.localStorage.setItem(key, preference); } catch (error) { /* The toggle still works for this page. */ }
      });
    });
  });
  media.addEventListener("change", function () { if (preference !== "light" && preference !== "dark") apply(preferredTheme()); });
  window.addEventListener("storage", function (event) {
    if (event.key === key || event.key === null) { preference = event.newValue; apply(preferredTheme()); }
  });
})();
