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

O cliente acompanha a assinatura e inicia o pagamento em **Meu plano e pagamento** (`/billing/assinatura/`). O Master configura o gateway de cobrança das assinaturas em **Master → Mercado Pago do ApPlanner** (`/master/pagamentos/mercado-pago/`): cadastra o webhook informado na tela no Mercado Pago Developers, seleciona o ambiente correto, informa a Public Key, o Access Token e a chave secreta do webhook e clica em **Testar e ativar conexão**. A conexão é validada pela API e os segredos ficam criptografados no banco. As variáveis `MERCADOPAGO_ACCESS_TOKEN` e `MERCADOPAGO_WEBHOOK_SECRET` do exemplo de ambiente não ativam esse gateway sozinhas. Use credenciais de teste para homologar cobranças antes de selecionar Produção.

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
