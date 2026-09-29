# ApPlanner Django

Replatform do ApPlanner para Python/Django, mantendo o PHP legado como referência até concluir a paridade funcional.

## Stack

- Python 3.13
- Django 5.2 LTS
- PostgreSQL 16
- Redis 7
- Celery + Celery Beat
- Gunicorn
- Docker Compose / Coolify

## Desenvolvimento local

No Windows/PowerShell:

```powershell
cd django
Copy-Item env.local.example .env
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build
```

O arquivo `.env` é ignorado pelo Git. Troque os dois placeholders de segredo antes de iniciar.

A aplicação fica em `http://127.0.0.1:8000/` e usa PostgreSQL/Redis dentro do Docker. O Compose local monta o código-fonte em `/app`, aplica migrations/seeds e inicia o servidor de desenvolvimento do Django.

## Coolify

Use o repositório Git com Build Pack **Docker Compose**.

- Branch de homologação: `django-replatform`
- Base Directory: `/django`
- Compose: `docker-compose.yml`
- Serviço público: `web`
- Porta interna: `8000`
- Não publique PostgreSQL ou Redis diretamente na internet.
- Cadastre os segredos no ambiente do Coolify a partir de `.env.example`.

Ao implantar esta atualização, o `web` aplica migrations, sincroniza os módulos e cria três planos públicos de homologação (Profissional, Inicial e Empresarial, com sete dias de teste) **somente se não houver outro plano público ativo**. Planos importados do PHP e edições feitas no Master não são sobrescritos. Revise preços, módulos incluídos, segmentos e período de teste em **Master → Planos** antes de vender. Na ficha da empresa, marque **Página pública** e informe as coordenadas da unidade para aparecer e ordenar por distância em `/directory/`. O JSON anterior está em `/api/directory/`.

O cliente acompanha a assinatura e escolhe **cartão recorrente** ou **Pix por ciclo** em **Meu plano e pagamento** (`/billing/assinatura/`). O Pix exibe QR code e copia e cola, e só ativa a assinatura depois de um webhook de Order confirmado pelo provedor com valor e moeda correspondentes. O Master configura o gateway em **Master → Mercado Pago do ApPlanner** (`/master/pagamentos/mercado-pago/`): cadastra o webhook informado na tela no Mercado Pago Developers, ativa notificações de **Orders, pagamentos e assinaturas**, seleciona o ambiente correto, informa a Public Key, o Access Token e a chave secreta do webhook e clica em **Testar e ativar conexão**. A conexão é validada pela API e os segredos ficam criptografados no banco. As variáveis `MERCADOPAGO_ACCESS_TOKEN` e `MERCADOPAGO_WEBHOOK_SECRET` não ativam esse gateway sozinhas. Use credenciais de teste para homologar cobranças antes de selecionar Produção.

O Master configura um fluxo simples por empresa em `/master/chatbot/`, com mensagens, palavras-chave e transferência para humano. A automação por estabelecimento só pode ser ativada quando o número Cloud API e as credenciais de WhatsApp estiverem configurados. O WhatsApp separado da plataforma, com QR code e caixa de entrada exclusiva do Master, está em `/master/whatsapp/`; veja a seção específica abaixo.

Em **Master → Campanhas de e-mail** (`/master/marketing/`), importe CSV UTF-8 com `nome,email` somente após confirmar o consentimento registrado na origem. Contatos já descadastrados não são reativados. A campanha entra na fila do Celery Beat apenas para contatos ativos com `consent_at`; o link público permite descadastro, e o Master pode interromper os envios pendentes. Configure e teste o SMTP antes do disparo. `PUBLIC_BASE_URL` com HTTPS é obrigatório para permitir o descadastro em todos os e-mails.

O proprietário conecta seu próprio Mercado Pago em **Operação → Recebimentos da empresa** (`/app/pagamentos/mercado-pago/`). A tela mostra a URL de webhook por empresa, valida as credenciais e não revela os segredos armazenados. Esta conexão não configura o gateway da plataforma usado para cobrar assinaturas do ApPlanner.

## Estado

Esta branch é de migração/homologação e ainda não substitui a produção PHP. Veja `MIGRATION_CHECKLIST.md`, `ARCHITECTURE.md` e `SECURITY.md`.

## Segurança

Não reutilize nenhuma credencial encontrada no histórico do repositório. Credenciais expostas devem ser rotacionadas antes de qualquer cutover.


## Sincronizar catálogo do PHP legado

Para copiar somente módulos, planos, preços, ciclos e vínculos plano→módulo do MySQL legado:

```bash
python manage.py import_legacy_core --catalog-only --dry-run
python manage.py import_legacy_core --catalog-only
```

Configure antes as variáveis `LEGACY_MYSQL_HOST`, `LEGACY_MYSQL_PORT`, `LEGACY_MYSQL_DATABASE`, `LEGACY_MYSQL_USER` e `LEGACY_MYSQL_PASSWORD`. O modo `--catalog-only` não importa clientes ou agendamentos.


## Homologar a partir de um dump SQL

Não conecte o ETL diretamente à produção para o primeiro ensaio. Use o clone MariaDB isolado:

```powershell
.\scripts\import-legacy-dump.ps1 -SqlPath "C:\caminho\appnannerbr_planner.sql"
```

O primeiro uso faz apenas `--dry-run`. Depois de revisar a saída:

```powershell
.\scripts\import-legacy-dump.ps1 -SqlPath "C:\caminho\appnannerbr_planner.sql" -Apply
```

O fluxo restaura o dump em MariaDB 10.11, executa `import_legacy_core`,
`import_legacy_specialized` e finaliza com `audit_legacy_parity --strict`.

Nunca versione dumps reais do banco, pois podem conter dados pessoais, hashes,
tokens e configurações sensíveis.
# WhatsApp do Master via QR code

No Coolify, defina `MASTER_WHATSAPP_GATEWAY_TOKEN` com um segredo aleatório longo e faça o redeploy da aplicação Compose. Acesse **Master → WhatsApp do Master → Gerar QR code** e leia o código em **WhatsApp → Aparelhos conectados → Conectar aparelho** no celular do número usado pelo Master. O serviço `master-whatsapp` mantém a sessão no volume `master_whatsapp_session`; preserve esse volume nos redeploys e proteja o seu backup. O gateway fica acessível somente na rede interna do Compose. Apenas superusuários veem o QR code e podem ler, associar ou enviar mensagens. Contatos novos podem ser associados manualmente a uma empresa depois da primeira conversa.

### Atendimento vinculado à agenda

O agendamento público nasce confirmado e dispara o e-mail de confirmação já configurável pelo Master. Quando a empresa conecta seu WhatsApp em **Operação → Conectar WhatsApp da empresa**, a confirmação pronta também entra na fila do WhatsApp; lembretes próximos seguem a configuração da agenda (2h) e podem ser enviados manualmente pelo profissional. O serviço Compose `tenant-whatsapp` usa um volume próprio `tenant_whatsapp_session`, com arquivos de sessão separados por empresa. Preserve esse volume nos redeploys. Ele usa o mesmo segredo interno `MASTER_WHATSAPP_GATEWAY_TOKEN`, sem expor o token aos usuários, e exige `PUBLIC_BASE_URL` HTTPS para os links de avaliação enviados por e-mail.

O profissional encerra o atendimento em **Minha agenda e ganhos → Registrar atendimento**, registrando presença, forma de pagamento e, se houve, produto e quantidade. O serviço gera receita e comissão; o produto passa pelo PDV com baixa de estoque e comissão própria. A avaliação de 1 a 5 aparece para o cliente no link do agendamento concluído e por e-mail, e a gestão consulta as médias em **Operação → Avaliações da equipe**. Um cliente que escreve “cancelar” na conversa vinculada ao agendamento faz surgir **Cancelar agendamento e disponibilizar horário** para a equipe; após encerrar, a conversa não aceita novas mensagens de agendamento. Os lembretes automáticos de 2 horas dependem da configuração da agenda da empresa. Para homologar, conecte um telefone de teste por QR e confirme envio, callback de resposta, recibos e QR após reiniciar o container.

O WhatsApp consta como módulo ativo no catálogo, mas continua dependente do plano ou de liberação individual, sem alterar automaticamente planos existentes. O Master deve selecionar a empresa em **Operação → Trocar empresa**, abrir **Conectar WhatsApp da empresa** e, quando necessário, clicar **Liberar WhatsApp para esta empresa** antes de **Conectar / atualizar QR**. A empresa sem o módulo vê uma explicação em vez de uma página 403. Se a própria tela mostrar erro de autenticação 403 do gateway, confirme que `MASTER_WHATSAPP_GATEWAY_TOKEN` é o mesmo nos containers `web` e `tenant-whatsapp` e refaça o deploy Compose.

Esta conexão usa a biblioteca Baileys para vincular um dispositivo do WhatsApp Web. Ela é independente da integração oficial Cloud API dos estabelecimentos e depende da disponibilidade e do protocolo do WhatsApp Web; mudanças no protocolo podem exigir atualização do gateway. O chatbot por estabelecimento continua na integração Cloud API existente. Para testar a integração real, é preciso publicar o Compose, ler o QR code com um número do Master e trocar mensagens de teste.

Para receber respostas no Coolify, configure `PUBLIC_BASE_URL=https://applanner.axionwebdigital.com.br`. O gateway chama `web:8000` na rede privada com o Host interno `web`, autorizado pelo Django quando o token do gateway está configurado. Inclua o domínio público em `DJANGO_ALLOWED_HOSTS` para acesso pelo navegador e indica na caixa de entrada quantas mensagens aguardam e se o Django recusou o callback. Após o deploy, envie uma mensagem **de outro número para o número pareado** e confira Master → WhatsApp do Master. Conversas de novos contatos podem virar leads no funil por meio de **Adicionar ao Comercial**. Para contato `@lid`, informe o telefone antes de registrar o lead.

Se o Mercado Pago recusar uma compra porque pagador e recebedor são a mesma conta, informe outro **e-mail do pagador** no cadastro ou em **Meu plano e pagamento**. Na homologação, configure as credenciais da conta vendedora e pague com uma conta compradora de teste diferente. A conta já criada pode continuar pelo link de **Meu plano e pagamento**; nenhum pagamento é confirmado sem retorno do provedor e verificação do webhook.

No Master, crie o lead a partir da conversa, monte uma proposta a partir de um plano público e envie o link aprovado pelo WhatsApp. Quando o comprador aceitar a proposta, o link **Criar conta e contratar** usa o preço mensal combinado na assinatura e impede uso duplicado ou e-mail diferente do destinatário da proposta. Alterações nos módulos do plano depois da proposta exigem uma nova oferta. O checkout continua dependendo das credenciais, dos webhooks e dos testes reais do Mercado Pago.

## Identidade visual e notícias

No Master, acesse **Página inicial** para editar a logo e os textos da página de vendas.
Em **Master → Blog**, crie uma notícia, envie uma imagem de capa e marque o status
**Publicado** para exibi-la no index. Para a empresa, **Operação → Minha página**
permite editar a logo, capa e apresentação públicas; **Agenda → Profissionais**
permite enviar a foto opcional de cada profissional. Somente imagens de empresas
publicadas, profissionais ativos, notícias publicadas e a logo da plataforma são
servidas por URLs públicas específicas. Preserve o volume `media` do Compose nos
redeploys para manter os uploads.

No checkout, o responsável escolhe cartão recorrente ou Pix para o ciclo atual.
O Pix requer um webhook `order` do Mercado Pago confirmado pelo servidor antes
de ativar a assinatura; renovações por Pix requerem pagamento a cada ciclo.

## Primeira entrada de novas empresas

Contas criadas em `/cadastro/` passam obrigatoriamente por `/inicio/`: dados da
empresa e CPF/CNPJ validado, endereço da unidade, serviço, profissional, dias e
horários, identidade da página e meios aceitos. A página pública continua
desligada até o proprietário confirmar o e-mail e concluir a publicação.
Usuários da equipe aguardam o responsável concluir antes de acessar a operação.
Empresas importadas e já em uso preservam o acesso atual. Configure SMTP no
Coolify para que a confirmação por e-mail funcione; pagamentos de planos
continuam acessíveis durante a configuração inicial.

Para ativar o envio de confirmação no Coolify, configure `EMAIL_HOST`,
`EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` e `DEFAULT_FROM_EMAIL`
com os dados fornecidos pelo serviço SMTP. Na porta 587 use `EMAIL_USE_TLS=true`
e `EMAIL_USE_SSL=false`; na porta 465 use `EMAIL_USE_TLS=false` e
`EMAIL_USE_SSL=true`. O tempo limite `EMAIL_TIMEOUT` é 15 segundos por padrão.
O remetente deve ser autorizado pelo provedor. Após salvar e redeployar,
solicite a verificação em `/inicio/` e confira a entrega e os logs do serviço
`web`. Não use backend de console ou memória em produção: eles não entregam
e-mails reais. Nunca exponha a senha SMTP nos logs ou nas capturas de tela.

O Pix gera a Order na API do Mercado Pago com a expiração associada ao
pagamento. A conta recebedora precisa de chave Pix habilitada e o pagador
precisa ser outra conta. Na homologação, o ambiente de teste do Mercado Pago
tem regras próprias para valores e pagador; não trate o QR de teste como
cobrança real. Se a API recusar a criação, revise a mensagem mostrada na tela
e verifique as credenciais da conta vendedora em Master → Mercado Pago.

## Fluxo e recibos do WhatsApp Master

Se o painel mostrar HTTP 400, confirme
`PUBLIC_BASE_URL=https://applanner.axionwebdigital.com.br`, salve e
redeploye todos os serviços. O Django adiciona o host dessa URL HTTPS aos
hosts permitidos, mas um URL vazio ou inválido continua bloqueando o callback.
Um evento com formato inválido mostra um motivo específico; eventos recusados
permanecem na fila persistente do gateway para nova tentativa. Se o erro
continuar após o deploy, confira o horário do 400 nos logs do serviço `web`
e do `master-whatsapp` no Coolify para distinguir rejeição do Host, da
segurança ou do formato do evento.

Em **Master → WhatsApp do Master → Configurar fluxo**, o Master pode criar etapas
com a sintaxe `etapa | palavra;sinônimo | resposta | próxima etapa | sim/não`.
O estado da conversa avança conforme as palavras recebidas; `atendimento` ou
`humano` chama uma pessoa. Ao enviar uma resposta manual, o fluxo pausa nessa
conversa até **Retomar fluxo**. Configure worker, beat e a sessão do gateway.
Os eventos do WhatsApp atualizam **Enviada**, **Entregue** e **Lida**; a ausência
de recibo significa confirmação indisponível, nunca entrega comprovada.
O Master pode enviar imagens PNG/JPG/WebP e PDFs de até 5 MB; os anexos ficam no
volume persistente `media` e a rota de download requer superusuário. O fluxo é
executado pelo Celery e retomado pelo beat quando a fila estiver disponível.
Valide envio, entrega, leitura e transferência com o número real pareado antes
de assumir esses estados como homologados em produção.

## Gestão de conta e comunicação

O proprietário gerencia o plano em `/billing/assinatura/`: pode cancelar a assinatura com confirmação de senha ou solicitar exclusão da conta. A exclusão abre um chamado para análise; não elimina automaticamente dados financeiros, uploads nem cancela a assinatura. O Master acompanha o pedido nos chamados. Para assinatura por cartão, o cancelamento só é registrado após a confirmação do Mercado Pago; pagamentos via Pix continuam no histórico.

O Master pode dispensar a confirmação de e-mail no cadastro de uma empresa pelo recurso **Onboarding → Verificação e publicação**. A dispensa não valida o endereço informado. SMTP pode ser configurado e testado em **Master → E-mail e SMTP** sem revelar a senha; a configuração ativa do painel tem prioridade sobre as variáveis `EMAIL_*` do Coolify.

Em **Master → Modelos de e-mail** (`/master/email/modelos/`), personalize assunto e mensagem de conta criada, confirmação do e-mail, conta confirmada, redefinição de senha e agendamento confirmado. O formulário mostra as variáveis permitidas e exige os links de segurança e dados essenciais. A plataforma gera versões texto e HTML escapado. Mensagens de boas-vindas, conta confirmada e agendamento confirmado entram na fila de notificações, processada pelo Celery Beat; a verificação do e-mail e a redefinição de senha são enviadas no ato da solicitação. Revise a configuração SMTP e execute um teste real antes da homologação.

A lista de espera no agendamento público aparece após a consulta retornar zero horários e só aceita pedidos para uma data sem disponibilidade, respeitando o módulo contratado. A inteligência de retorno cria perfil no primeiro agendamento, sem contar visita ou disparar marketing antes de atendimento concluído e consentimento.
