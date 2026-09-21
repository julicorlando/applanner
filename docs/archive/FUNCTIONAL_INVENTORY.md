# Inventário funcional auditado

Status em 07/08/2026. `TESTADO` significa execução automatizada local; `INSPECIONADO` significa revisão de rota, controller, SQL e permissão; fluxos com persistência estão `BLOCKED` enquanto não houver MySQL de teste instalado.

| Módulo | Função | Rota | Perfil | Backend/Banco | Status | Evidência |
|---|---|---|---|---|---|---|
| Comercial | Landing e planos do banco | `/`, `/planos` | Público | CommercialController/plans | BLOCKED | requer DB |
| Comercial | Cadastro + trial sem cartão | `/cadastro` | Público | transação tenant/user/subscription | BLOCKED | requer DB |
| Auth | Login/logout/reset/e-mail | `/login`, `/logout`, `/forgot-password` | Todos | users/tokens/jobs | PARTIAL | segurança estática PASS; SMTP externo bloqueado |
| Auth | 2FA TOTP | `/security`, `/two-factor-challenge` | Autenticado | users/recovery codes | PARTIAL | código inspecionado; E2E requer DB |
| Master | Dashboard/empresas/planos/saúde | `/master*` | Master | consultas agregadas | PARTIAL | CRUD de planos incompleto |
| Master | Contas bancárias protegidas | `/master/bank-accounts` | Master | campos criptografados | PARTIAL | E2E requer APP_KEY/DB |
| Onboarding | Wizard 9 etapas | `/onboarding` | Owner | tenants/units/professionals/services | PARTIAL | etapas 6 e 8 são apenas informativas |
| Agenda | Listar/criar/status | `/appointments*` | Tenant | appointments | PARTIAL | remarcação e disponibilidade calculada ausentes |
| Público | Página e booking | `/a/{slug}` | Público | tenants/customers/appointments | PARTIAL | concorrência inspecionada; aceita data livre |
| Profissional | Link direto | `/a/{slug}/p/{professional}` | Público | professionals | PARTIAL | filtra profissional, mas tela ainda lista todos |
| Profissional | Cadastro e convite | `/professionals` | Owner | professionals/users/reset token | PARTIAL | job de e-mail do convite ausente |
| Profissional | Portal/agenda própria | `/dashboard`, `/appointments` | Professional | RBAC | FAIL | agenda não filtra profissional logado |
| Clientes | Cadastro/listagem/LGPD | `/customers*` | Tenant | customers/privacy | PARTIAL | cliente 360 incompleto |
| Serviços | Cadastro/listagem | `/services*` | Tenant | services | PARTIAL | editar/desativar ausentes |
| Produtos | Cadastro/listagem/estoque | `/products` | Owner | products | PARTIAL | editar/ajustar estoque ausentes |
| PDV | Venda e baixa concorrente | `/sales` | Owner/Professional | sales/items/movements | PARTIAL | criação inspecionada; cancelamento ausente |
| Behavior | Recalcular/oportunidades | `/api/behavior/*` | Tenant | behavior profiles/events | PASS | teste automatizado existente |
| Campanhas | Criar/segmentar fila | `/campaigns` | Permitido | campaigns/jobs | PARTIAL | interface não oferece executar/acompanhar mensagens |
| Financeiro tenant | Receita/despesa | `/finance` | Permitido | financial_entries | PARTIAL | caixa/comissão ausentes |
| Billing | Checkout/cupom/invoice | `/checkout/{plan}`, `/billing` | Tenant | checkout/invoices/payments | PARTIAL | provider é sandbox local |
| Webhook | Pagamento HMAC/idempotente | `/webhooks/payment/{provider}/{tenant}` | Provider | webhook_events/payments | PARTIAL | Mercado Pago oficial ausente |
| Integrações | SMTP/WhatsApp/webhook | `/settings/integrations` | Owner | settings criptografados | PARTIAL | teste de conexão ausente |
| Suporte | Abrir/listar chamado | `/support` | Tenant/Master | support_tickets | PARTIAL | conversa, upload e acesso assistido ausentes |
| Backup | Criar backup por cron | CLI | Servidor | storage/backups | BLOCKED | requer DB/config |
| Instalador | Instalação e lock | `/install/` | Instalador | schema/migrations/config | BLOCKED | serviço MySQL ausente |
| Saúde/odontologia | Prontuário | inexistente | Clínico | inexistente | NOT IMPLEMENTED | não apresentado no menu |
| Automotivo | Veículos | inexistente | Tenant | inexistente | NOT IMPLEMENTED | não apresentado no menu |

