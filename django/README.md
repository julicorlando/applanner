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
