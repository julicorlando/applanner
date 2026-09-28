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

Esta conexão usa a biblioteca Baileys para vincular um dispositivo do WhatsApp Web. Ela é independente da integração oficial Cloud API dos estabelecimentos e depende da disponibilidade e do protocolo do WhatsApp Web; mudanças no protocolo podem exigir atualização do gateway. O chatbot por estabelecimento continua na integração Cloud API existente. Para testar a integração real, é preciso publicar o Compose, ler o QR code com um número do Master e trocar mensagens de teste.

Para receber respostas no Coolify, configure `PUBLIC_BASE_URL=https://applanner.axionwebdigital.com.br`, mantendo o domínio em `DJANGO_ALLOWED_HOSTS`. O gateway faz o callback para `web:8000` na rede privada com o Host público e indica na caixa de entrada quantas mensagens aguardam e se o Django recusou o callback. Após o deploy, envie uma mensagem **de outro número para o número pareado** e confira Master → WhatsApp do Master. Conversas de novos contatos podem virar leads no funil por meio de **Adicionar ao Comercial**. Para contato `@lid`, informe o telefone antes de registrar o lead.

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

## Fluxo e recibos do WhatsApp Master

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
