<section class="commercial-section appbarber-inspired-features" id="funcionalidades">
 <div class="sales-section-title centered"><span class="eyebrow">Tudo conectado</span><h2>Funcionalidades para atender, fidelizar e faturar mais.</h2><p>Da reserva ao pós-atendimento, o ApPlanner organiza cada etapa da experiência.</p></div>
 <div class="feature-showcase-grid">
 <?php foreach([
  ['Agenda e lembretes','Disponibilidade real, confirmações, remarcações, intervalos, folgas e bloqueios.'],
  ['Página pública','Link próprio com sua marca, serviços, equipe, unidades, produtos e pagamentos.'],
  ['Clientes e fidelidade','Histórico, pacotes, assinaturas, pontos, recompensas e oportunidades de retorno.'],
  ['Equipe e comissões','Acessos individuais, agenda por profissional, desempenho, vendas e comissões.'],
  ['Produtos e estoque','Cadastro, PDV, movimentações, estoque mínimo e visão de margem.'],
  ['Financeiro e relatórios','Receitas, despesas, caixa, projeções e indicadores para decidir melhor.'],
  ['Multiunidade','Dados, contatos, redes sociais e operação organizada por estabelecimento.'],
  ['Automação comercial','Lembretes, espera, notificações e inteligência de relacionamento.']
 ] as $i=>$feature):?>
  <article><span><?=str_pad((string)($i+1),2,'0',STR_PAD_LEFT)?></span><h3><?=$feature[0]?></h3><p><?=$feature[1]?></p></article>
 <?php endforeach;?>
 </div>
 <div class="text-center mt-4"><a class="btn btn-primary btn-lg" href="/planos">Conhecer planos e recursos</a></div>
</section>
