# Clientes de desenvolvimento

Área exclusiva do superusuário ativo, fora de impersonação: Master → Clientes de desenvolvimento. Não cria empresas, assinaturas ou planos de agendamento e não altera o financeiro dessas operações.

## Cadastro e senha

Pessoa física: CPF válido e nome completo. Pessoa jurídica: CNPJ válido, razão social e nome fantasia opcional. E-mail único para login, WhatsApp brasileiro com DDD e link opcional. A conta é sem tenant, sem staff, sem permissões Master, com papel development-client. E-mails de contas existentes são rejeitados, nunca reaproveitados. CPF/CNPJ é criptografado com a chave existente; o hash serve para deduplicação. O e-mail de acesso fica fixo na edição para preservar a identidade.

Ao cadastrar, a mesma transação grava um convite de senha e dois envios, e-mail e WhatsApp Master. O worker os processa a cada minuto. Link aleatório de 256 bits; só o hash do token fica na tabela de convites. Mensagens pendentes ficam criptografadas. Convite expira em 24h, exige senha validada (mínimo de 12 caracteres), é invalidado após uso ou reemissão. Limite de tentativas na ativação. O link não autentica automaticamente nem comprova confirmação do endereço de e-mail. Após senha criada, o cliente usa a página de login existente e é direcionado aos seus pagamentos. Esqueci minha senha existente continua disponível fora de sessão autenticada.

Desativar o cliente bloqueia seu portal e os envios sem apagar históricos. Logout continua permitido. As demais páginas não foram redesenhadas. Apenas um item foi acrescentado à lateral Master; a restrição de navegação do novo perfil não afeta os perfis existentes.

## Cobranças

Descrição, valor positivo, vencimento e conta bancária ativa já cadastrada em finance.PlatformBankAccount; aceita também boleto por link HTTPS ou PDF de até 5 MB, e linha digitável. O PDF é criptografado no banco, sem arquivo público em /media. Download exige sessão do próprio cliente ou Master. Formulários protegidos por CSRF; criação tem chave única contra duplo envio. O portal mostra somente a conta selecionada, titular, agência, conta e chave Pix (quando cadastrada); não expõe notas internas, documento bancário ou credenciais.

**Não emite nem registra boletos bancários**: anexe/vincule o boleto emitido pelo banco. Cadastro de conta não é API de emissão ou conciliação. Boleto e Pix direto à chave bancária continuam com baixa pelo Master, com justificativa e auditoria. Não existe botão do cliente para marcar como pago. Cobranças baixadas não são reabertas por esse fluxo.

## Pix e cartão online

A cobrança pode permitir Pix com QR/copia e cola e cartão tokenizado, reutilizando exclusivamente o PaymentGateway Mercado Pago já cadastrado, ativo, validado e em produção no Master. Não cria nem modifica credenciais, contas, planos ou assinaturas. O dinheiro é recebido na conta vinculada a esse provedor, não automaticamente na conta PlatformBankAccount selecionada para boleto/Pix direto. Só dados bancários (inclusive Nubank) não habilitam captura de cartão nem conciliação automática. Cartão requer public key; o formulário seguro usa o SDK oficial e o servidor não armazena PAN, CVV ou token. O valor mínimo online segue a validação existente do provedor (R$ 0,50).

Somente o cliente autenticado inicia o pagamento de uma cobrança própria, por POST com CSRF. Valor, identificação e e-mail vêm do cadastro no servidor. Tentativa persistida antes do pedido financeiro, referência exclusiva/idempotente, snapshot de valor/revisão/recebedor, locks de cliente e cobrança e bloqueio de tentativas simultâneas de outros meios. Resposta perdida fica em conferência, nunca libera uma segunda captura só por timeout. Pagamento pendente bloqueia edição/cancelamento e esconde os outros meios no portal para reduzir pagamentos duplicados. O Master pode consultar o acompanhamento no detalhe da cobrança.

Webhook específico da tentativa exige assinatura HMAC do segredo já configurado; consulta o pagamento autenticado na API e não confia em status enviado pelo navegador/webhook. Confere identificador, referência, valor, BRL, produção, recebedor e método antes da baixa. Só approved baixa; authorized aguarda. Aprovação cancela os lembretes pendentes. Worker também concilia a cada dois minutos as tentativas dos últimos 30 dias. Estorno/chargeback é registrado e exige revisão do Master, sem reabrir dívida ou lembretes automaticamente. Pagamento tardio de cobrança alterada/cancelada ou já baixada manualmente fica para revisão. Não há reembolso/cancelamento financeiro automático.

O notification_url de cada pagamento aponta para /webhooks/desenvolvimento/pagamentos/<UUID>/. Deve estar publicamente acessível via HTTPS e o segredo de assinatura deve corresponder à aplicação do provedor. Testes usam mocks sem transações reais; validação financeira controlada após publicação depende de credenciais e autorização próprias.

## Lembretes

Texto configurável por cliente com {nome}, {descricao}, {valor}, {vencimento}, {link}. O link para a página protegida é obrigatório. Envia pelo WhatsApp Master 10 e 5 dias antes, no vencimento, e D+2, D+4, D+6 etc. enquanto em aberto. Entre 9h e 18h em America/Recife. Datas sem lembrete não são disparadas retroativamente. O PDF, se cadastrado, vai como documento; link/linha digitável/dados bancários ficam disponíveis no portal. SMS, canais dos estabelecimentos e campanhas não são usados.

Fila durável, chave única por cobrança/revisão/etapa, chave idempotente no gateway WhatsApp, revalidação imediatamente antes do envio e locks por cliente e cobrança. Após baixa/cancelamento, desativação ou mudança de vencimento, envios antigos pendentes são cancelados. Envio já em andamento é serializado antes da baixa; mensagens já entregues não podem ser recolhidas. Falha WhatsApp: até 5 tentativas com espera crescente, no mesmo dia, com a mesma chave; exceções não aparecem ao cliente nem são gravadas com dados sensíveis. Falhas SMTP ou worker interrompido ficam em “Conferir envio”, evitando repetição automática de convite possivelmente entregue. Para primeira senha, reemitir convite invalida o anterior. O Master vê o histórico dos últimos envios, não o conteúdo do token. Mensagens processadas/canceladas têm o payload apagado. Nenhum envio real foi realizado durante implementação/testes.

## Publicação

Migrations aditivas development.0001 e 0002 criam cinco tabelas novas e o controle de pagamento online; nenhum registro existente é removido. Sem nova biblioteca de pagamentos. Pillow foi atualizado para 13 para corrigir vulnerabilidades da versão anterior, com autorização do usuário e testes de imagens. Backup normal antes do deploy; preservar chave de criptografia, bancos e volumes existentes. Bootstrap aplica migrations e seed_periodic_tasks inclui development.tasks.process_development_billing a cada minuto e development.tasks.reconcile_development_payments a cada dois minutos. Exige worker e beat ativos, PUBLIC_BASE_URL HTTPS, SMTP já configurado e WhatsApp Master pareado. Sem esses canais, cadastros e cobranças permanecem registrados, e o resultado do envio aparece no histórico.

Validar após publicação com um cadastro controlado: convite recebido, senha, login, acesso a um boleto próprio, tentativa de outro ID negada, lembrete e baixa. Não execute cadastros de clientes reais como teste automático. Para reverter o código, preservar as tabelas e desativar somente a tarefa “Cobranças de clientes de desenvolvimento”. Não desfazer a migration nem excluir usuários/cobranças.
