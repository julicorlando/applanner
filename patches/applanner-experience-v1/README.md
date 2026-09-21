# ApPlanner Experience V1

Patch incremental para experiência visual, painel Master, idiomas, páginas públicas, aquisição e saúde dos crons. Não remove tabelas, empresas, usuários, planos, assinaturas, pagamentos ou módulos.

## Instalação

1. Extraia o ZIP na raiz de `public_html`.
2. Execute `php tools/install-experience-v1.php --dry-run`.
3. Execute `php tools/install-experience-v1.php`.
4. Execute `php tools/applanner-cron-health.php`.

O instalador exige PHP 8.2, cria backup do banco, preserva os arquivos alterados, aplica a migration 044, executa lint e testes, e tenta registrar os crons. No cPanel que bloqueia `crontab`, use as linhas exibidas por `php tools/install-experience-crons.php`.

## Idiomas

Idiomas habilitados: Português (Brasil), Português (Portugal), English e Español. A base usa fallback para PT-BR, portanto uma chave ausente nunca derruba a tela. Novas telas e navegação utilizam o catálogo central em `app/Lang`.

## Diagnóstico dos crons

- Relatório humano: `php tools/applanner-cron-health.php`
- JSON para monitoramento: `php tools/applanner-cron-health.php --json`
- Modo rigoroso: `php tools/applanner-cron-health.php --strict`
- Teste de um cron: `php tools/applanner-cron-health.php --run=worker`

Saídas: `0=OK`, `1=ALERTA`, `2=FALHA`. O wrapper `cron/run.php` registra início, fim, duração, host e erro em `cron_heartbeats`.

## Rollback

Execute `php tools/rollback-experience-v1.php`. O código anterior é restaurado; as colunas aditivas permanecem para evitar perda dos textos e configurações já salvos.
