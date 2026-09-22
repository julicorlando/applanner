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
