# Correções da avaliação após redeploy

Branch: `django-replatform`. Sem alteração ou merge na `main`.

## Problemas corrigidos

- **Histórico de clientes:** o agendamento público deixa de alterar nome, telefone e e-mail do cadastro compartilhado. Cada atendimento guarda `customer_name_snapshot`, usado na agenda, confirmação pública, área do profissional, avaliações e mensagens de WhatsApp. Novos agendamentos internos também guardam o nome. Alterar posteriormente o cadastro do cliente não muda esse histórico.
- **Reagendamento:** a seleção pública mostra somente profissionais ativos da empresa que atendem o serviço. A consulta de horários exibe a explicação do backend quando a seleção é inválida. Falhas de rede continuam com mensagem em português.
- **Arena Sports:** a carga inicial corrige exclusivamente o plano legado com esse nome quando ele não possui nenhum vínculo de módulo: acrescenta Arena e, se ausente, sua identificação de segmento. Não altera preços, assinaturas, limites, descrições, visibilidade ou vínculos previamente desativados pelo Master. A execução é idempotente.
- **Comparação comercial:** módulos ativos refletem inclusão efetiva; descrições livres distinguem benefício declarado de informação ausente. Mostra limites cadastrados e preços reais por ciclo, com o mesmo cálculo utilizado pela cobrança. Não inventa vantagens para justificar planos com preços diferentes.
- **Cadastro:** resumo de plano, teste, exigência de cartão e valor por ciclo acompanha a seleção; os segmentos disponíveis também acompanham a troca de plano. Explica que o teste sem cartão não gera cobrança agora e exige pagamento para continuar depois. Não muda as regras de cobrança.
- **Agenda:** filtros de hoje, próximos atendimentos e situação, inclusive reservas Arena, preservam isolamento por empresa e atualização automática. “Hoje” respeita o fuso da empresa.
- **Primeiros passos:** apresenta os bloqueios operacionais separadamente da personalização opcional. Horários precisam comportar serviços atendidos; Arena exige compatibilidade entre quadra, horário, duração e regra de preço. Sem pagamento na unidade, a agenda identifica a falta de configuração online.
- **WhatsApp:** estados da conexão da empresa exibidos em português; valores internos do gateway preservados.

## Dados e publicação

A migration `scheduling.0014_appointment_customer_name_snapshot` preserva os nomes atuais dos agendamentos existentes. Ela **não consegue reconstruir nomes já sobrescritos pelo fluxo antigo**: essa recuperação depende de backup ou outra fonte histórica.

Fazer redeploy no Coolify usando `django-replatform`. O entrypoint aplica migrations, atualiza o catálogo e coleta os arquivos estáticos. Confirmar nos logs a migration 0014 e a carga de planos. Revisar na página de planos o vínculo de Arena Sports e os limites que ainda não foram informados pelo Master.

## Verificação

Testes de regressão cobrem preservação do cliente e do histórico, profissionais elegíveis, filtros e isolamento, fuso horário, configuração mínima e pagamentos opcionais, compatibilidade de Arena, tradução de WhatsApp, catálogo idempotente e preços por ciclo. Verificação Django, migrations, coleta de estáticos, sintaxe JavaScript e suíte completa devem passar antes da publicação.

As alterações precisam ser homologadas no site após redeploy. Testes com provedores simulados não certificam entrega de e-mail/WhatsApp ou cobrança real de Pix/cartão. Esta entrega corrige os pontos da avaliação; não declara a migração inteira como 100% homologada.

Verificação local concluída: 244 testes aprovados, `check` sem problemas, `makemigrations --check --dry-run` sem diferenças, migration 0014 aplicada e coleta de estáticos concluída. Os scripts foram verificados em sintaxe e em execução controlada para troca de plano/ciclo/segmento, mensagem de erro do backend e falha de rede.
