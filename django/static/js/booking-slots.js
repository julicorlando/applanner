window.createBookingSlotPicker = ({container, input, status, onChange = () => {}, onAvailability = () => {}, onNextDate = null}) => {
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
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error();
        error.userMessage = response.status === 400 && typeof data.detail === 'string' ? data.detail : 'Não foi possível consultar os horários. Tente novamente.';
        throw error;
      }
      if (currentRequest !== requestId) return;
      const slots = data.slots || [];
      onAvailability(slots.length);
      if (!slots.length) {
        status.textContent = 'Não há horários disponíveis nessa data.';
        if (data.next_available && onNextDate) {
          const next = document.createElement('button');
          next.type = 'button';
          next.className = 'button';
          next.textContent = `Ver próxima vaga: ${data.next_available.date_label} às ${data.next_available.label}`;
          next.addEventListener('click', () => onNextDate(data.next_available.date));
          container.appendChild(next);
        } else if (data.next_search_end) {
          status.textContent += ` Não encontramos vagas até ${data.next_search_end}. Tente outro profissional ou entre na lista de espera, se disponível.`;
        }
        return;
      }
      status.textContent = 'Selecione um horário disponível.';
      const groups = new Map();
      slots.forEach((slot, index) => {
        const hour = Number(String(slot.label).split(':')[0]);
        const period = hour < 12 ? 'Manhã' : hour < 18 ? 'Tarde' : 'Noite';
        if (!groups.has(period)) {
          const section = document.createElement('section'); section.className = 'booking-slot-group';
          const title = document.createElement('h4'); title.textContent = period;
          const list = document.createElement('div'); list.className = 'booking-slot-group__list';
          section.appendChild(title); section.appendChild(list); container.appendChild(section); groups.set(period, list);
        }
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'booking-slot';
        button.textContent = slot.label;
        button.setAttribute('aria-pressed', 'false');
        if (index === 0) {
          const badge = document.createElement('span'); badge.className = 'booking-slot__next'; badge.textContent = 'Próximo horário'; button.appendChild(badge);
        }
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
          onChange(true, slot);
        });
        groups.get(period).appendChild(button);
      });
    } catch (error) {
      if (currentRequest === requestId) status.textContent = error.userMessage || 'Não foi possível consultar os horários. Tente novamente.';
    }
  }

  return {load, reset};
};
