# ApPlanner — Replatform Django

## Objetivo

Reescrever o ApPlanner em Python/Django sem remover funcionalidades do legado, preservando regras de negócio e dados, e preparar a aplicação para deploy reproduzível no Coolify.

## Inventário auditado do legado

- 1.127 arquivos versionados
- 799 arquivos PHP
- 63 controllers ativos
- 45 services ativos
- 159 views
- 49 migrations SQL
- 14 crons
- 37 arquivos de teste
- módulos de agenda, clientes, profissionais, planos, assinaturas, Mercado Pago/PIX, financeiro, comercial/CRM, marketing, WhatsApp, arena, automotivo, barbearia, saúde, LGPD, 2FA, branding, i18n, domínios e administração master

Há migrations com numeração duplicada (044 e 045), portanto a origem deve ser normalizada antes do ETL definitivo.

## Stack alvo

- Python 3.13
- Django 5.2 LTS
- Django REST Framework
- PostgreSQL 16+
- Redis
- Celery + Celery Beat
- Gunicorn
- Docker / Docker Compose
- Coolify
- Argon2 para novas senhas
- compatibilidade temporária com bcrypt legado do PHP
- observabilidade via logs e Sentry opcional

## Mapeamento de domínios

| Legado | App Django alvo |
|---|---|
| Auth, 2FA, trusted devices, RBAC | accounts |
| Tenants, branding, domínios | tenants / platform |
| Customers, professionals, services, schedule | scheduling |
| Plans, subscriptions, billing, Mercado Pago, PIX | billing |
| Notifications, e-mail, WhatsApp, marketing | communications |
| Commercial, leads, sales, commissions | crm |
| Arena/sports/reservations/tournaments | arena |
| Auto/vehicles | auto |
| Barber/membership/goals | barber |
| Medical records | healthcare |
| Finance/banking/stock/packages | finance |
| Funil, UTM, Meta CAPI, blog, growth, i18n | growth |
| Master, support, incidents, audit, integrations | platform |

## Estratégia

1. Saneamento de segredos e arquivos gerados.
2. Modelagem Django/PostgreSQL e migrations nativas.
3. ETL MySQL -> PostgreSQL com validação por contagem/checksum.
4. Compatibilidade de login com hashes PHP e rehash automático em Argon2.
5. Migração das telas e APIs por domínio.
6. Conversão dos crons para Celery Beat.
7. Webhooks idempotentes e com verificação de assinatura.
8. Testes de regressão por módulo.
9. Homologação paralela.
10. Cutover com rollback documentado.

## Regra de preservação

Nenhuma funcionalidade deve ser removida apenas por ser antiga. Recursos serão migrados e só poderão ser desativados após decisão explícita.
