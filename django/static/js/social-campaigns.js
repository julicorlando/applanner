(() => {
  'use strict';
  document.querySelectorAll('[data-social-copy]').forEach(button => {
    button.addEventListener('click', async () => {
      const field = document.getElementById(button.dataset.socialCopy);
      const status = document.querySelector('[data-social-copy-status]');
      if (!field || !status) return;
      try {
        await navigator.clipboard.writeText(field.value);
        status.textContent = 'Copiado. Você já pode colar na sua publicação.';
      } catch {
        field.focus(); field.select();
        status.textContent = 'Texto selecionado. Use a opção Copiar do seu dispositivo.';
      }
    });
  });
})();
