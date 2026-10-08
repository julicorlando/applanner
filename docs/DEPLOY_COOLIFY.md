# Deploy Coolify

1. Publicar a branch aprovada e selecionar `django-replatform` no serviço web.
2. Configurar `PUBLIC_BASE_URL=https://applanner.com.br` sem incluir o nome da variável no valor.
3. Manter web, worker e beat apontando para o mesmo PostgreSQL/Redis; worker e beat aguardam web saudável.
4. O entrypoint executa `bootstrap_application`, que serializa migrations, seeds e collectstatic com advisory lock PostgreSQL.
5. Conferir logs, `/healthz`, um único beat e volumes persistentes de PostgreSQL/media/sessões.
6. Fazer rollback para a imagem anterior se health check, migrations ou seed falharem.

O CI executa check, collectstatic, drift de migrations, suíte Django, Node e smoke de restore em banco PostgreSQL descartável. Isso não substitui restore off-site de produção.
