(() => {
  const catalog = JSON.parse(document.getElementById('signup-plan-conditions').textContent);
  const select = document.getElementById('id_plan');
  const cycle = document.getElementById('id_billing_cycle');
  const category = document.getElementById('id_category');
  const labels = {monthly: 'mensal', quarterly: 'trimestral', semiannual: 'semestral', annual: 'anual'};
  function update() {
    const plan = catalog.find(item => item.id === select.value);
    if (plan) {
      const previous = category.value;
      category.replaceChildren(...plan.categories.map(item => {
        const option = document.createElement('option');
        option.value = item.value;
        option.textContent = item.label;
        return option;
      }));
      category.value = plan.categories.some(item => item.value === previous) ? previous : '';
    }
    document.getElementById('signup-plan-name').textContent = plan ? plan.name : 'Condições do plano';
    document.getElementById('signup-plan-trial').textContent = !plan ? 'Selecione um plano.' : plan.days ? `${plan.days} dias de teste${plan.withoutCard ? ' sem cartão e sem cobrança agora' : ''}.` : 'Este plano não tem período de teste.';
    document.getElementById('signup-plan-price').textContent = plan ? `R$ ${plan.prices[cycle.value]} por ciclo ${labels[cycle.value]}.` : '';
    const offer = plan?.offers?.[cycle.value];
    document.getElementById("id_price_quote").value = plan?.quotes?.[cycle.value] || "";
    const money = value => new Intl.NumberFormat('pt-BR', {style:'currency', currency:'BRL'}).format(Number(value));
    if (offer) document.getElementById('signup-plan-price').textContent = `Total do ciclo ${labels[cycle.value]}: ${money(offer.amount)}${offer.months ? `. Promoção por ${offer.months} meses após o teste; depois ${money(offer.regular)}/mês.` : '.'}${Number(offer.saving) > 0 ? ` Economia por ciclo: ${money(offer.saving)}.` : ''}`;
    document.getElementById('signup-plan-composition').textContent = plan ? `Plano: ${offer ? money(offer.amount) : '—'} · Unidades incluídas: ${plan.included_units} · Profissionais incluídos: ${plan.included_professionals ?? 'Consultar'}. Adicionais pagos: R$ 0,00. Unidades, profissionais e módulos extras só são cobrados após contratação adicional.` : '';
    document.getElementById('signup-plan-billing').textContent = !plan ? '' : plan.days && plan.withoutCard ? 'Para continuar após o teste, será necessário pagar o ciclo escolhido.' : plan.days ? 'Este plano exige configurar o pagamento para iniciar o teste. Confira as condições de cobrança no checkout.' : 'Pagamento necessário para liberar o acesso.';
  }
  select.addEventListener('change', update);
  cycle.addEventListener('change', update);
  update();
})();
