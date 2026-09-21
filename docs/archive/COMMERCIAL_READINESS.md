# Prontidão comercial

| Área | Estado |
|---|---|
| Landing | Implementada |
| Planos dinâmicos | Implementados |
| Signup self-service | Implementado |
| Trial e owner automáticos | Implementados |
| Checkout server-side | Implementado |
| Billing e faturas | Implementados |
| Onboarding | Implementado |
| Conta bancária Master | Implementada e cifrada |
| Gateway sandbox | Implementado |
| Gateway financeiro real | **Bloqueador** — credenciais e adapter específico ausentes |
| E2E MySQL/navegador | **Bloqueador** — projeto não instalado neste ambiente |

## Veredito

O fluxo self-service de trial está implementado. Não liberar cobrança real até configurar um gateway específico, validar sandbox, executar migrations em MySQL 8/MariaDB compatível e concluir testes E2E de signup, checkout, webhook duplicado, renovação, suspensão e reativação.
