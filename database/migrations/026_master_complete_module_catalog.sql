-- Garante que todo o catálogo operacional exista e possa ser controlado pelo Master.
INSERT IGNORE INTO modules(slug,name,active) VALUES
('products','Produtos, PDV e vendas',1),
('stock','Controle de estoque',1),
('finance','Financeiro e controle de caixa',1),
('behavior','Inteligência de retorno',1),
('whatsapp','WhatsApp',0),
('multiunit','Multiunidade',1),
('packages','Pacotes e mensalidades',1),
('loyalty','Fidelidade',1),
('waitlist','Lista de espera inteligente',1),
('custom_domain','Domínio personalizado',1),
('medical_records','Prontuários',0),
('odontology','Odontologia',0),
('api','API',0);

UPDATE modules SET name='Produtos, PDV e vendas',description='Cadastro de produtos, frente de caixa (PDV) e venda de produtos.' WHERE slug='products';
UPDATE modules SET name='Controle de estoque',description='Saldos, movimentações e alerta de estoque mínimo.' WHERE slug='stock';
UPDATE modules SET name='Financeiro e controle de caixa',description='Receitas, despesas, formas de pagamento, abertura e fechamento de caixa.' WHERE slug='finance';
UPDATE modules SET name='Inteligência de retorno',description='Convites de retorno e relacionamento com os clientes.' WHERE slug='behavior';
UPDATE modules SET name='Multiunidade',description='Gestão de mais de uma unidade no mesmo estabelecimento.' WHERE slug='multiunit';
UPDATE modules SET name='Pacotes e mensalidades',description='Pacotes de serviços, créditos e mensalidades recorrentes.' WHERE slug='packages';
UPDATE modules SET name='Fidelidade',description='Pontos, regras e recompensas para fidelização.' WHERE slug='loyalty';
UPDATE modules SET name='Lista de espera inteligente',description='Fila para preencher horários que ficarem disponíveis.' WHERE slug='waitlist';
UPDATE modules SET name='Domínio personalizado',description='Uso de domínio próprio na página pública.' WHERE slug='custom_domain';
