# Checklist de paridade funcional

## Fundação concluída

- [x] Base Django e Docker/Coolify
- [x] PostgreSQL + Redis + Celery/Celery Beat
- [x] Migrations iniciais versionadas
- [x] Healthcheck real de banco/cache
- [x] Tenant/multiempresa inicial
- [x] Usuário por e-mail e compatibilidade bcrypt PHP -> Argon2
- [x] Isolamento de tenant na API inicial
- [x] CI com PostgreSQL/Redis, checks, migrations e testes

## Em andamento

- [x] Núcleo clientes/profissionais/serviços/agendamentos
- [x] Agenda 2.0: expediente, intervalos, folgas, regras, slots e conflito concorrente
- [x] Núcleo de planos/assinaturas/pagamentos
- [x] Billing comercial: ciclos, checkout, cupom, fatura, addons e solicitações de módulo
- [x] Catálogo de módulos + entitlement por plano/tenant
- [x] Branding e multiunidade no modelo
- [x] Financeiro/estoque/POS/comissões — núcleo e operações atômicas
- [x] Notificações + campanhas + e-mail marketing — núcleo
- [x] Celery: fila de notificações, e-mail marketing e lembretes de agenda
- [x] ETL núcleo MySQL -> PostgreSQL com preservação de IDs e bcrypt
- [x] Recriptografia compatível AES-256-GCM PHP -> chave Django
- [ ] 2FA completo: serviços prontos; falta integrar challenge/login/UI
- [ ] Branding/domínios/i18n completo: modelo base pronto; falta editor e rotas públicas
- [ ] Financeiro/banking/stock/packages: financeiro/stock/POS prontos; faltam banking e packages
- [ ] Marketing/e-mail/WhatsApp: e-mail e campanhas base prontos; falta provider WhatsApp e tracking
- [ ] Importação total: núcleo pronto; faltam tabelas especializadas
- [ ] Conversão dos 14 crons: primeiros jobs migrados; faltam jobs especializados
- [ ] Testes de regressão e segurança: CI + testes-base prontos; cobertura ainda incompleta

## Ainda a portar integralmente

- [ ] RBAC completo e permissões do legado
- [ ] Mercado Pago + PIX + webhooks
- [ ] Comercial/CRM/leads/equipe/comissões comerciais
- [ ] Arena/sports/tournaments/memberships/dynamic pricing
- [ ] Automotivo/vehicles/jobs/estimates/commands
- [ ] Barbearia/memberships/goals/maintenance
- [ ] Saúde/prontuário
- [ ] Loyalty/referrals/waitlist/packages
- [ ] Blog/public directory/landings
- [ ] Funil/UTM/Meta CAPI
- [ ] Master/support/incidents/operations center
- [ ] Legal/LGPD completo
- [ ] Homologação paralela
- [ ] Cutover e rollback
