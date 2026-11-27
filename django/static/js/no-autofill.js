// Patient and clinic forms must not be filled with the browser's saved data
// (it mixes the receptionist's own name, e-mail and address into patient records).
// Sign-in and password forms keep autofill so password managers still work.
(function () {
  var KEEP = /^(current-password|new-password|one-time-code|username)$/;
  function apply(root) {
    (root.querySelectorAll ? root : document).querySelectorAll('form').forEach(function (form) {
      if (form.hasAttribute('data-allow-autofill') || form.querySelector('input[type=password]')) return;
      form.setAttribute('autocomplete', 'off');
      form.querySelectorAll('input, textarea, select').forEach(function (field) {
        var type = (field.getAttribute('type') || '').toLowerCase();
        if (type === 'hidden' || type === 'submit' || type === 'button' || type === 'file') return;
        if (KEEP.test(field.getAttribute('autocomplete') || '')) return;
        field.setAttribute('autocomplete', 'off');
      });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { apply(document); });
  else apply(document);
})();
