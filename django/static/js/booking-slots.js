window.createBookingSlotPicker = ({container, input, status, onChange = () => {}, onAvailability = () => {}}) => {
  let requestId = 0;

  function reset(message) {
    requestId += 1;
    input.value = '';
    container.replaceChildren();
    status.textContent = message;
    onChange(false);
    onAvailability(null);
  }

  async function load(url) {
    reset('Carregando horários disponíveis...');
    const currentRequest = requestId;
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error('Consulta indisponível');
      const data = await response.json();
      if (currentRequest !== requestId) return;
      const slots = data.slots || [];
      onAvailability(slots.length);
      if (!slots.length) {
        status.textContent = 'Não há horários disponíveis nessa data.';
        return;
      }
      status.textContent = 'Selecione um horário disponível.';
      slots.forEach(slot => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'booking-slot';
        button.textContent = slot.label;
        button.setAttribute('aria-pressed', 'false');
        button.setAttribute('aria-label', `Selecionar ${slot.label}${slot.professional_name ? ` com ${slot.professional_name}` : ''}`);
        if (slot.professional_name) {
          const name = document.createElement('small');
          name.textContent = slot.professional_name;
          button.appendChild(name);
        }
        button.addEventListener('click', () => {
          container.querySelectorAll('button').forEach(item => item.setAttribute('aria-pressed', 'false'));
          button.setAttribute('aria-pressed', 'true');
          input.value = slot.value;
          status.textContent = `Horário selecionado: ${slot.label}.`;
          onChange(true);
        });
        container.appendChild(button);
      });
    } catch (error) {
      if (currentRequest === requestId) status.textContent = 'Não foi possível consultar os horários. Tente novamente.';
    }
  }

  return {load, reset};
};
