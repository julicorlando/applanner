<?php
$e=fn($v)=>htmlspecialchars((string)$v,ENT_QUOTES,'UTF-8');
$cta=$plans?'/cadastro':'/interesse-comercial';
$ctaLabel=$plans?'Começar teste grátis':'Falar com um consultor';
$trialDays=$plans?max(array_map(fn($p)=>(int)($p['trial_days']??0),$plans)):0;
?>
<div class="conversion-page showcase-home">
<section class="conversion-hero showcase-hero">
  <div class="conversion-copy">
    <span class="conversion-pill">Agenda • Operação • Clientes • Financeiro</span>
    <h1>Seu cliente agenda. Sua equipe executa. <em>Você enxerga o negócio.</em></h1>
    <p>O ApPlanner reúne agendamento online, gestão da operação, relacionamento, vendas e módulos específicos para cada segmento — sem obrigar sua empresa a trabalhar do jeito de um sistema genérico.</p>
    <div class="conversion-actions">
      <a class="btn btn-light btn-lg" href="<?=$cta?>"><?=$e($ctaLabel)?> <span>→</span></a>
    </div>
    <div class="conversion-reassurance">
      <?php if($plans&&$trialDays):?><span>✓ Até <?=$trialDays?> dias para testar</span><?php endif;?>
      <span>✓ Implantação guiada</span><span>✓ Funciona no celular e computador</span><span>✓ Evolui por módulos</span>
    </div>
  </div>
  <div class="product-stage" aria-label="Visão resumida do ApPlanner">
    <div class="stage-top"><i></i><i></i><i></i><span>ApPlanner · Central da operação</span></div>
    <div class="stage-body"><aside><b>A</b><i></i><i></i><i></i><i></i></aside><main>
      <div class="stage-welcome"><span>Visão em tempo real</span><strong>Hoje no seu negócio</strong></div>
      <div class="stage-kpis"><article><small>Atendimentos</small><b>18</b><span>programados</span></article><article><small>Ocupação</small><b>82%</b><span class="up">operação organizada</span></article><article><small>Receita prevista</small><b>R$ 2.460</b><span>do dia</span></article></div>
      <div class="stage-agenda"><header><strong>Próximas operações</strong><span>Ver painel</span></header>
      <?php foreach([['09:00','Cliente confirmado','Serviço agendado','Confirmado'],['10:30','Equipe em atendimento','Comanda em andamento','Executando'],['13:00','Horário disponível','Seu link pode preencher','Disponível']] as $row):?><div><time><?=$row[0]?></time><i></i><span><b><?=$row[1]?></b><small><?=$row[2]?></small></span><em><?=$row[3]?></em></div><?php endforeach;?>
      </div>
    </main></div>
  </div>
</section>

<section class="conversion-proof">
<?php if(($proof['businesses']??0)>=3):?><div><strong>+<?=(int)$proof['businesses']?></strong><span>negócios na plataforma</span></div><?php endif;?>
<?php if(($proof['appointments']??0)>=50):?><div><strong>+<?=number_format((int)$proof['appointments'],0,',','.')?></strong><span>agendamentos registrados</span></div><?php endif;?>
<?php if(($proof['reviews']??0)>=3):?><div><strong><?=number_format((float)$proof['rating'],1,',','')?>/5</strong><span>média nas avaliações públicas</span></div><?php endif;?>
<div><strong>24h</strong><span>para o cliente agendar</span></div><div><strong>1 link</strong><span>para divulgar seu negócio</span></div><div><strong>Modular</strong><span>você adiciona o que precisa</span></div>
</section>

<section class="conversion-section showcase-verticals" id="segmentos">
  <div class="conversion-title centered"><span>Uma plataforma, várias operações</span><h2>O ApPlanner muda conforme o seu negócio.</h2><p>O mesmo núcleo de clientes, financeiro e gestão recebe fluxos especializados para cada segmento.</p></div>
  <div class="vertical-showcase-grid">
    <article><span class="vertical-badge">BARBER</span><h3>ApPlanner Barber</h3><p>Agenda por barbeiro, check-in, fila de encaixe, comandas, produtos, comissão, gorjeta, metas e Clube do Corte.</p><ul><li>Profissionais e serviços</li><li>Comanda integrada</li><li>Comissões e fidelidade</li></ul><a href="<?=$cta?>">Quero usar na barbearia →</a></article>
    <article><span class="vertical-badge">ARENA</span><h3>ApPlanner Arena</h3><p>Reservas diretamente por quadra, mensalistas, rachas, lista de espera, aulas, torneios, comandas e preço dinâmico.</p><ul><li>Agenda por quadra</li><li>Sinal e pagamentos</li><li>Operação esportiva completa</li></ul><a href="<?=$cta?>">Quero usar na Arena →</a></article>
    <article class="featured"><span class="vertical-badge">AUTO</span><h3>ApPlanner Auto</h3><p>Veículos, boxes, check-in, checklist, orçamento adicional, detailing, estoque técnico, garantia e CRM por veículo.</p><ul><li>Agenda por box/vaga</li><li>Histórico por veículo</li><li>Fotos, etapas e comanda</li></ul><div class="vertical-actions"><a href="<?=$cta?>">Quero usar →</a></div></article>
  </div>
</section>

<section class="conversion-section segment-choice"><div class="conversion-title"><span>Veja na sua rotina</span><h2>Escolha um segmento.</h2><p>A proposta muda automaticamente para mostrar o fluxo mais importante daquele negócio.</p></div>
<div class="segment-tabs" role="tablist">
<?php foreach(['barbearia'=>'Barbearia','salao'=>'Salão','estetica'=>'Estética','arena'=>'Arena','automotivo'=>'Auto / Detailing','saude'=>'Saúde','outros'=>'Outros'] as $key=>$label):?><button type="button" class="<?=$key==='automotivo'?'active':''?>" data-segment="<?=$key?>"><?=$label?></button><?php endforeach;?>
</div>
<div class="segment-result"><div><span data-segment-kicker>Para lava-jato e detailing</span><h3 data-segment-title>Do check-in do veículo à próxima manutenção.</h3><p data-segment-text>Organize carros, boxes, serviços, checklist, orçamento, estoque e retorno do cliente em um fluxo único.</p><ul data-segment-list><li>Veículos e histórico por placa</li><li>Boxes, check-in e etapas</li><li>Comanda, garantia e CRM</li></ul><div class="segment-inline-actions"><a class="btn btn-primary btn-lg" href="<?=$cta?>">Aplicar no meu negócio</a></div></div>
<div class="segment-phone"><div class="phone-bar"><b data-phone-company>Auto Prime</b><span>● Online</span></div><div class="phone-service"><small data-phone-label>Escolha um serviço</small><strong data-phone-service>Lavagem técnica</strong><span data-phone-duration>90 minutos</span></div><div class="phone-slots"><small data-phone-slots-title>Boxes disponíveis hoje</small><div><b>09:30</b><b>11:00</b><b>14:30</b><b>16:00</b></div></div><button data-phone-button>Reservar horário</button></div></div></section>

<section class="conversion-section" id="demonstracao"><div class="conversion-title centered"><span>Do primeiro clique ao retorno</span><h2>Uma jornada que continua depois do agendamento.</h2></div>
<div class="journey-grid"><?php foreach([
['01','Cliente agenda','Página pública com sua marca, serviços e disponibilidade real.'],
['02','Operação executa','Equipe acompanha agenda, recursos, check-in, comandas e tarefas.'],
['03','Gestão acompanha','Financeiro, estoque, produtividade, vendas e indicadores no mesmo ambiente.'],
['04','Cliente retorna','Lembretes, CRM, fidelidade, pacotes e oportunidades de retorno.']
] as $item):?><article><span><?=$item[0]?></span><h3><?=$item[1]?></h3><p><?=$item[2]?></p></article><?php endforeach;?></div></section>

<section class="conversion-section outcome-section"><div class="conversion-title"><span>Menos improviso</span><h2>Troque conversas espalhadas por um processo visível.</h2><p>O objetivo não é colocar mais uma ferramenta na rotina. É concentrar o que hoje costuma ficar dividido entre WhatsApp, caderno, planilha e memória.</p></div><div class="outcome-grid"><?php foreach([
['Agendamento','Cliente consulta horários e agenda pelo seu link.'],['Operação','Equipe sabe o que fazer, quando e para quem.'],['Clientes','Histórico, preferências, veículos, pacotes ou recorrências ficam organizados.'],['Financeiro','Receitas, despesas, caixa, vendas e cobranças conversam entre si.'],['Estoque','Produtos e materiais acompanham vendas e consumo operacional.'],['Crescimento','CRM, lista de espera e módulos adicionais acompanham a evolução do negócio.']
] as $o):?><article><strong><?=$o[0]?></strong><p><?=$o[1]?></p></article><?php endforeach;?></div></section>

<section class="conversion-section result-section"><div><span class="conversion-eyebrow">Simule sua oportunidade</span><h2>Quanto horários não preenchidos representam por mês?</h2><p>A simulação não é promessa de faturamento. Ela ajuda a visualizar o valor potencial de melhorar ocupação e retorno.</p><div class="roi-fields"><label>Ticket médio (R$)<input type="number" min="1" step="1" value="80" data-roi-ticket></label><label>Horários vagos por semana<input type="number" min="0" step="1" value="8" data-roi-slots></label><label>Percentual recuperável (%)<input type="number" min="0" max="100" step="5" value="40" data-roi-rate></label></div></div><aside><small>Potencial mensal estimado</small><strong data-roi-result>R$ 1.024,00</strong><span data-roi-detail>aproximadamente 13 atendimentos recuperados</span><a class="btn btn-light btn-lg" href="<?=$cta?>">Organizar minha operação</a></aside></section>

<section class="conversion-section benefits-grid"><div class="conversion-title"><span>Base completa</span><h2>Comece simples e evolua por módulos.</h2><p>O estabelecimento solicita novos recursos e o valor adicional pode ser incorporado à própria assinatura.</p></div><div class="benefit-cards"><?php foreach([
['◷','Agenda inteligente','Disponibilidade, duração, intervalos, bloqueios, remarcações e recursos do segmento.'],
['◎','Clientes 360','Histórico, preferências, recorrência, pacotes, veículos e relacionamento.'],
['↗','Página pública','Link próprio para apresentar o negócio e receber agendamentos.'],
['▦','Equipe e operação','Acessos por perfil, produtividade, comissões e execução organizada.'],
['R$','Financeiro e vendas','Produtos, estoque, comandas, caixa, receitas, despesas e pagamentos.'],
['✦','Automação e CRM','Lembretes, lista de espera, retorno e oportunidades baseadas na operação.']
] as $b):?><article><b><?=$b[0]?></b><h3><?=$b[1]?></h3><p><?=$b[2]?></p></article><?php endforeach;?></div></section>

<?php if($plans):?><section class="conversion-section" id="planos"><div class="conversion-title centered"><span>Comece do seu jeito</span><h2>Escolha a base e adicione módulos quando precisar.</h2><p>O ApPlanner acompanha a maturidade da sua empresa sem obrigar você a contratar tudo no primeiro dia.</p></div><?php require __DIR__.'/plans-grid.php';?><div class="conversion-safe"><span>🔒 Cobrança pela plataforma</span><span>✓ Módulos podem entrar na assinatura</span><span>🛟 Suporte centralizado</span></div></section><?php else:?><section class="conversion-section consultative-cta"><div><span>Atendimento consultivo</span><h2>Vamos montar a configuração ideal para o seu negócio.</h2><p>Conte como sua operação funciona e o comercial prepara a implantação.</p></div><a class="btn btn-light btn-lg" href="/interesse-comercial">Solicitar demonstração →</a></section><?php endif;?>


<section class="conversion-section trust-conversion"><div><span class="conversion-eyebrow">Estrutura para operar com confiança</span><h2>Dados de cada empresa permanecem separados.</h2><p>Controle de acesso, auditoria, backups, privacidade, permissões por perfil e integrações financeiras configuráveis.</p></div><div><span>✓ Multiempresa</span><span>✓ Perfis e permissões</span><span>✓ Auditoria administrativa</span><span>✓ LGPD e consentimentos</span><span>✓ Backups e suporte</span><span>✓ Integrações por provider</span></div></section>

<section class="conversion-section faq-conversion"><div class="conversion-title centered"><span>Dúvidas frequentes</span><h2>Antes de começar</h2></div><?php foreach([
['Preciso instalar aplicativo?','Não. Empresa, equipe e clientes usam o navegador no celular ou computador.'],
['O cliente precisa criar senha para agendar?','Não. A página pública permite o agendamento sem criar uma conta tradicional.'],
['Serve apenas para barbearia?','Não. O ApPlanner possui fluxos especializados, como Barber, Arena e Auto, além dos segmentos de atendimento já suportados.'],
['Posso contratar módulos depois?','Sim. A empresa pode solicitar módulos adicionais e, após aprovação, o valor pode ser incorporado à assinatura.'],
['Consigo personalizar a página?','Sim. Logo, cores, capa, dados da empresa, formas de pagamento e seções públicas são configuráveis.'],
['Existe suporte?','Sim. A empresa pode abrir chamados e acompanhar o atendimento dentro da plataforma.']
] as $i=>$faq):?><details <?=$i===0?'open':''?>><summary><?=$faq[0]?><b>+</b></summary><p><?=$faq[1]?></p></details><?php endforeach;?></section>

<?php require __DIR__.'/latest-blog.php';?>
<section class="conversion-final"><span>Seu negócio já tem uma operação. O ApPlanner ajuda você a enxergá-la.</span><h2>Organize hoje. Adicione recursos conforme crescer.</h2><p>Conheça os recursos e escolha a configuração que faz sentido para sua empresa.</p><div><a class="btn btn-light btn-lg" href="<?=$cta?>"><?=$e($ctaLabel)?> →</a></div><small>Ao continuar, você poderá consultar os Termos de Uso e a Política de Privacidade.</small></section>
<div class="mobile-conversion-bar"><div><strong>ApPlanner</strong><span><?=$plans&&$trialDays?'Teste grátis disponível':'Fale com o comercial'?></span></div><a class="btn btn-primary" href="<?=$cta?>"><?=$plans?'Começar agora':'Solicitar contato'?></a></div>
</div><script src="/public/assets/js/index-conversion.js?v=20260826-prehomologacao" defer></script>
