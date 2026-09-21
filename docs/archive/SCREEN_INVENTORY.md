# Inventário de telas

| Rota | Tela | Perfil | Backend | Responsiva |
|---|---|---|---|---|
| `/login`, `/forgot-password`, `/reset-password`, `/two-factor-challenge` | Identidade | Público | Sim | Sim |
| `/security` | Segurança da conta | Autenticado | Sim | Sim |
| `/dashboard` | Visão da empresa | Tenant | Sim | Sim |
| `/appointments`, `/appointments/create` | Agenda | Tenant/RBAC | Sim | Sim |
| `/customers`, `/customers/create`, `/customers/{id}/privacy` | Clientes/LGPD | Tenant/RBAC | Sim | Sim |
| `/services`, `/services/create` | Serviços | Tenant/RBAC | Sim | Sim |
| `/finance` | Financeiro | Tenant/RBAC | Sim | Sim |
| `/campaigns` | Campanhas | Tenant/RBAC | Sim | Sim |
| `/settings/integrations` | Integrações | Owner/Manager | Sim | Sim |
| `/onboarding` | Primeiros passos | Owner | Sim | Sim |
| `/{slug}` | Página/agendamento público | Público | Sim | Sim |
| `/master` | Dashboard SaaS | Master | Sim | Sim |
| `/master/tenants*` | Empresas | Master | Sim | Sim |
| `/master/plans` | Planos | Master | Leitura | Sim |
| `/master/system-health` | Saúde | Master | Sim | Sim |
| erros 403/404/419/500 | Estados de erro | Todos | Sim | Sim |

Telas não existentes no backend — estoque, prontuário, CRM dedicado, relatórios e caixa — não foram adicionadas ao menu para evitar fachada visual.
