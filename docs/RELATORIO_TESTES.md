# Relatório de testes

- `manage.py check`: aprovado.
- `makemigrations --check --dry-run`: aprovado.
- Node `tests-js/*.test.cjs`: 20 aprovados localmente, incluindo PWA/cache.
- CI anterior em `django-replatform`: 621 testes Django aprovados após a proteção do admin.
- CI da branch de qualidade: em execução nesta entrega; registrar o número final no PR.
- Testes direcionados de segurança, agenda/unidade, permissões de API, financeiro e backup foram adicionados.

Limitações: mocks não comprovam gateway externo; SQLite local não comprova locks PostgreSQL; o CI PostgreSQL comprova os cenários automatizados, não o ambiente Coolify.
