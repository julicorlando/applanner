# Production Readiness — Agenda Inteligente SaaS

Revisão em 07/08/2026. O sistema **ainda não deve receber clientes pagantes**. A base Core está mais segura, mas o escopo comercial anunciado é muito maior que o backend entregue.

## Notas atuais

| Área | Nota | Evidência principal |
|---|---:|---|
| Segurança | 7/10 | CSRF, PDO, RBAC, tenant context, logs, lock de agenda e reset seguro; faltam 2FA e suíte dinâmica |
| Arquitetura | 6/10 | MVC e migrations; controllers ainda concentram persistência |
| UX | 4/10 | Responsiva básica; sem sidebar premium, paginação ou onboarding |
| Performance | 5/10 | Índices básicos e limites; faltam paginação real e EXPLAIN em banco-alvo |
| SaaS readiness | 3/10 | Master somente leitura; cobrança, módulos e lifecycle incompletos |
| Instalação | 6/10 | Instalação bloqueável e migrations; falta wizard completo/teste assíncrono do banco |
| Manutenibilidade | 6/10 | Código pequeno e tipado; faltam repositories, CI e testes integrados |

## Auditoria de rotas

| Rotas | Auth | Tenant | Permissão | CSRF |
|---|---|---|---|---|
| `/login` GET/POST | pública | n/a | n/a | POST sim |
| `/logout` POST | sessão | n/a | n/a | sim |
| `/dashboard` | sessão | obrigatório | `dashboard.view` | n/a |
| `/customers*` | sessão | obrigatório | `customers.view/create` | escrita sim |
| `/services*` | sessão | obrigatório | `services.view/create` | escrita sim |
| `/appointments*` | sessão | obrigatório | `agenda.view/create/edit` | escrita sim |
| `/api/behavior/*` | sessão | obrigatório | dashboard/customer | POST sim |
| `/master*` | sessão | n/a | role `master` | somente leitura |

Consultas comerciais revisadas usam `tenant_id`; joins do dashboard foram corrigidos. IDs de cliente, serviço e profissional são validados dentro da empresa antes do agendamento.

## Matriz de permissões inicial

| Recurso | Master | Owner | Manager | Reception | Professional | Finance |
|---|---:|---:|---:|---:|---:|---:|
| Master | sim | não | não | não | não | não implementado |
| Dashboard tenant | não | sim | sim | sim | sim | não implementado |
| Clientes visualizar | não | sim | sim | sim | sim | não implementado |
| Clientes criar | não | sim | sim | sim | não | não implementado |
| Serviços criar | não | sim | sim | não | não | não implementado |
| Agenda criar | não | sim | sim | sim | não | não implementado |
| Agenda alterar | não | sim | sim | sim | sim | não implementado |

## Bloqueadores de produção

1. Confirmação de e-mail e 2FA ainda não existem; recuperação segura e revogação de sessões foram implementadas.
2. Cadastro/lifecycle de empresas, planos, módulos e assinaturas ainda não têm CRUD comercial completo.
3. Onboarding, página pública e agendamento público não existem.
4. Financeiro, campanhas, providers, webhook idempotente e backup não existem. Fila cifrada e worker CLI de e-mail já estão disponíveis.
5. Não há suíte integrada em MySQL nem teste real HTTP/browser.
6. Não há política jurídica/LGPD validada nem fluxos de exportação/anonimização.
7. Bootstrap ainda depende de CDN e CSP mantém `unsafe-inline` para estilos.

## Entregue nesta revisão

Páginas 403/419, security log sanitizado, health check Master, BehaviorEngine robusto com mediana/MAD/desvio e perfil por cliente+serviço, migration versionada e testes locais do algoritmo/controles estáticos.
