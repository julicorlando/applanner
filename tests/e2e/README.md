# E2E de homologação

Os testes desta pasta são deliberadamente **opt-in** e nunca devem rodar contra produção.

## Banco MySQL/MariaDB
Use um banco dedicado cujo nome contenha `test`, `teste`, `homolog` ou `staging`:

```bash
E2E_MYSQL_DSN='mysql:host=127.0.0.1;port=3306;dbname=agenda_homolog;charset=utf8mb4' \
E2E_MYSQL_USER='agenda_homolog' E2E_MYSQL_PASS='***' \
php tests/e2e/mysql_environment_smoke.php
```

Esse smoke é não destrutivo: valida conexão, tabelas/colunas V3 e suporte a transação/lock.

## HTTP/HTTPS

```bash
E2E_BASE_URL='https://homologacao.seudominio.com' php tests/e2e/http_smoke.php
```

Valida páginas públicas essenciais e confirma que `config/` e `storage/logs/` não são expostos.

## Fluxos que ainda exigem execução humana/automação de navegador no ambiente real

- cadastro self-service → onboarding;
- agendamento público → portal do profissional;
- conclusão → pacote/comissão/financeiro;
- PDV → estoque → relatório;
- suporte → autorização → Modo Suporte;
- Mercado Pago Sandbox → webhook real.

Esses fluxos constam do checklist `V3_PRODUCTION_STATUS.md` e não devem ser marcados como PASS sem evidência do servidor de homologação.
