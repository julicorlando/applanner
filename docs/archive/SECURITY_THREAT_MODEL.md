# Threat Model — Agenda Inteligente SaaS

## Ativos

Credenciais e sessões; dados pessoais e consentimentos; agenda e comportamento de consumo; faturamento e pagamentos; segredos SMTP, WhatsApp e gateways; logs, backups e configurações. Dados clínicos não existem nesta versão e não devem ser inferidos nem acessados pelo motor comercial.

## Atores

Visitante público, cliente final, profissional, recepção, financeiro, gerente, proprietário, Master SaaS, tenant malicioso, atacante não autenticado e integração comprometida.

## Fronteiras de confiança

1. Navegador público → página/agendamento público.
2. Navegador autenticado → sessão PHP, CSRF, RBAC e TenantContext.
3. Gateway externo → webhook assinado, sem sessão/CSRF.
4. Jobs cifrados → workers CLI.
5. Aplicação → MySQL com prepared statements.
6. Aplicação → storage privado protegido pelo servidor.

## Superfícies prioritárias

- Login, reset, confirmação de e-mail, TOTP e recovery codes.
- Rotas Master e alteração de tenant/plano.
- IDs de cliente, agenda, finanças, campanhas e consentimentos.
- Reserva pública concorrente e rate limit.
- Webhooks, idempotência e alteração de pagamento.
- Configuração de SMTP/WhatsApp e exposição de segredos.
- Backup, exportação LGPD e downloads.
- Instalador, config, logs, migrations e `.git`.

## Ameaças e controles

| Ameaça | Impacto | Controles exigidos |
|---|---|---|
| Tenant escape/IDOR | Crítico | TenantContext, filtro composto e testes A×B |
| Webhook forjado/replay | Crítico | HMAC, timestamp, event ID único e transação |
| Double booking | Alto | lock por tenant/profissional e transação |
| Roubo de segredo | Alto | AES-GCM, mascaramento e no-store |
| Escalação de privilégio | Alto | autorização no controller e campos explícitos |
| CSRF/XSS | Alto | token em mutações e escaping contextual |
| Backup/export público | Alto | storage privado, autorização e auditoria |
| Brute force | Médio | limites IP/conta e backoff |
| Job entre tenants | Alto | tenant explícito em cada job e payload cifrado |

## Decisões

Webhooks nunca confiam em preço/status do navegador. Master não recebe acesso implícito a dados clínicos. Backups não têm rota pública. Integrações externas permanecem desativadas até credenciais válidas e teste explícito.
