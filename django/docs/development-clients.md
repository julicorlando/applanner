# Clientes de desenvolvimento

Área exclusiva do superusuário ativo, fora de impersonação: Master → Clientes de desenvolvimento. Não cria empresas, assinaturas ou planos de agendamento e não altera o financeiro dessas operações.

## Cadastro e senha

Pessoa física: CPF válido e nome completo. Pessoa jurídica: CNPJ válido, razão social e nome fantasia opcional. E-mail único para login, WhatsApp brasileiro com DDD e link opcional. A conta é sem tenant, sem staff, sem permissões Master, com papel development-client. E-mails de contas existentes são rejeitados, nunca reaproveitados. CPF/CNPJ é criptografado com a chave existente; o hash serve para deduplicação. O e-mail de acesso fica fixo na edição para preservar a identidade.

Ao cadastrar, a mesma transação grava um convite de senha e dois envios, e-mail e WhatsApp Master. O worker os processa a cada minuto. Link aleatório de 256 bits; só o hash do token fica na tabela de convites. Mensagens pendentes ficam criptografadas. Convite expira em 24h, exige senha validada (mínimo de 12 caracteres), é invalidado após uso ou reemissão. Limite de tentativas na ativação. O link não autentica automaticamente nem comprova confirmação do endereço de e-mail. Após senha criada, o cliente usa a página de login existente e é direcionado aos seus pagamentos. Esqueci minha senha existente continua disponível fora de sessão autenticada.

Desativar o cliente bloqueia seu portal e os envios sem apagar históricos. Logout continua permitido. As demais páginas não foram redesenhadas. Apenas um item foi acrescentado à lateral Master; a restrição de navegação do novo perfil não afeta os perfis existentes.

## Cobranças

Descrição, valor positivo, vencimento e conta bancária ativa já cadastrada em finance.PlatformBankAccount; aceita também boleto por link HTTPS ou PDF de até 5 MB, e linha digitável. O PDF é criptografado no banco, sem arquivo público em /media. Download exige sessão do próprio cliente ou Master. Formulários protegidos por CSRF; criação tem chave única contra duplo envio. O portal mostra somente a conta selecionada, titular, agência, conta e chave Pix (quando cadastrada); não expõe notas internas, documento bancário ou credenciais.

**Não emite nem registra boletos bancários**: anexe/vincule o boleto emitido pelo banco. Cadastro de conta não é API de emissão ou conciliação. Não cria cobranças no Mercado Pago nem toca nas credenciais. O cliente pode abrir/baixar boleto ou consultar os dados Pix/transferência; confirmação do recebimento e cancelamento são feitos pelo Master com justificativa e auditoria. Não existe botão do cliente para marcar como pago. Cobranças baixadas não são reabertas nem alteradas por esse fluxo. Emissão e baixa automáticas exigem uma integração bancária específica futura.

## Lembretes

Texto configurável por cliente com {nome}, {descricao}, {valor}, {vencimento}, {link}. O link para a página protegida é obrigatório. Envia pelo WhatsApp Master 10 e 5 dias antes, no vencimento, e D+2, D+4, D+6 etc. enquanto em aberto. Entre 9h e 18h em America/Recife. Datas sem lembrete não são disparadas retroativamente. O PDF, se cadastrado, vai como documento; link/linha digitável/dados bancários ficam disponíveis no portal. SMS, canais dos estabelecimentos e campanhas não são usados.

Fila durável, chave única por cobrança/revisão/etapa, chave idempotente no gateway WhatsApp, revalidação imediatamente antes do envio e locks por cliente e cobrança. Após baixa/cancelamento, desativação ou mudança de vencimento, envios antigos pendentes são cancelados. Envio já em andamento é serializado antes da baixa; mensagens já entregues não podem ser recolhidas. Falha WhatsApp: até 5 tentativas com espera crescente, no mesmo dia, com a mesma chave; exceções não aparecem ao cliente nem são gravadas com dados sensíveis. Falhas SMTP ou worker interrompido ficam em “Conferir envio”, evitando repetição automática de convite possivelmente entregue. Para primeira senha, reemitir convite invalida o anterior. O Master vê o histórico dos últimos envios, não o conteúdo do token. Mensagens processadas/canceladas têm o payload apagado. Nenhum envio real foi realizado durante implementação/testes.

## Publicação

Migration aditiva development.0001 cria quatro tabelas novas; nenhum registro existente é removido ou transformado. Sem dependências novas. Backup normal antes do deploy; preservar chave de criptografia, bancos e volumes existentes. Bootstrap aplica migration e seed_periodic_tasks inclui development.tasks.process_development_billing a cada minuto. Exige worker e beat ativos, PUBLIC_BASE_URL HTTPS, SMTP já configurado e WhatsApp Master pareado. Sem esses canais, cadastros e cobranças permanecem registrados, e o resultado do envio aparece no histórico.

Validar após publicação com um cadastro controlado: convite recebido, senha, login, acesso a um boleto próprio, tentativa de outro ID negada, lembrete e baixa. Não execute cadastros de clientes reais como teste automático. Para reverter o código, preservar as tabelas e desativar somente a tarefa “Cobranças de clientes de desenvolvimento”. Não desfazer a migration nem excluir usuários/cobranças.
