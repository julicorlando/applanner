(() => {
  const list = document.querySelector('[data-live-preview]');
  if (!list) return;

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reducedMotion) return;

  const samples = [
    {time:'16:00', title:'Novo agendamento', detail:'Corte + barba · Pedro', accent:false},
    {time:'16:40', title:'Pagamento confirmado', detail:'Pix recebido', accent:true},
    {time:'17:20', title:'Cliente confirmado', detail:'Corte · Lucas', accent:false},
    {time:'18:00', title:'Novo agendamento', detail:'Reserva feita pelo celular', accent:false},
    {time:'18:30', title:'Próximo horário', detail:'Profissional avisado', accent:true},
    {time:'19:10', title:'Agendamento online', detail:'Barba · Rafael', accent:false},
    {time:'20:00', title:'Cliente confirmado', detail:'Corte premium · Bruno', accent:false},
    {time:'20:40', title:'Pagamento confirmado', detail:'Pagamento integrado', accent:true},
  ];

  let index = 0;
  let running = false;

  function buildRow(item) {
    const row = document.createElement('div');
    row.className = 'preview-new-event';

    const time = document.createElement('time');
    time.textContent = item.time;

    const event = document.createElement('span');
    event.className = item.accent ? 'event accent' : 'event';

    const title = document.createElement('b');
    title.textContent = item.title;

    const detail = document.createElement('small');
    detail.textContent = item.detail;

    event.append(title, detail);
    row.append(time, event);
    return row;
  }

  function advance() {
    if (running || document.hidden || list.children.length < 2) return;
    running = true;

    const first = list.firstElementChild;
    const styles = getComputedStyle(list);
    const gap = parseFloat(styles.rowGap || styles.gap || '9') || 9;
    const distance = first.getBoundingClientRect().height + gap;

    list.style.transition = 'transform 560ms cubic-bezier(.22,.8,.24,1)';
    list.style.transform = `translateY(-${distance}px)`;

    const finish = () => {
      list.removeEventListener('transitionend', finish);
      first.remove();

      const next = buildRow(samples[index % samples.length]);
      index += 1;
      list.appendChild(next);

      list.style.transition = 'none';
      list.style.transform = 'translateY(0)';
      void list.offsetHeight;
      requestAnimationFrame(() => next.classList.remove('preview-new-event'));
      running = false;
    };

    list.addEventListener('transitionend', finish, {once:true});
    window.setTimeout(() => {
      if (running) finish();
    }, 800);
  }

  window.setInterval(advance, 3000);
})();
