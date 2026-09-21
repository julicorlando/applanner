-- Funções operacionais apresentadas ao Master na configuração dos planos.
UPDATE modules SET active=1,name='Produtos, PDV e vendas',description='Cadastro de produtos, frente de caixa (PDV) e venda de produtos.' WHERE slug='products';
UPDATE modules SET active=1,name='Controle de estoque',description='Saldos, movimentações e alerta de estoque mínimo.' WHERE slug='stock';
UPDATE modules SET active=1,name='Financeiro e controle de caixa',description='Receitas, despesas, formas de pagamento, abertura e fechamento de caixa.' WHERE slug='finance';
UPDATE modules SET description='Pacotes de serviços, créditos e mensalidades recorrentes.' WHERE slug='packages';
UPDATE modules SET description='Pontos, regras e recompensas para fidelização.' WHERE slug='loyalty';
UPDATE modules SET description='Fila para preencher horários que ficarem disponíveis.' WHERE slug='waitlist';
UPDATE modules SET description='Gestão de mais de uma unidade no mesmo estabelecimento.' WHERE slug='multiunit';
UPDATE modules SET description='Convites de retorno e relacionamento com os clientes.' WHERE slug='behavior';
