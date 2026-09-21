# Relatório de bugs QA

## Abertos

| ID | Prioridade | Problema | Impacto |
|---|---|---|---|
| BUG-001 | Blocker | Mercado Pago oficial não implementado; checkout usa SandboxPaymentProvider | SaaS não cobra clientes reais |
| BUG-003 | Critical externo | Instalação ainda não executada num MySQL limpo | Upgrade não comprovado |
| BUG-ENV-001 | Blocker | PHP ativo sem extensões `mbstring` e `openssl` | Funções UTF-8 e criptografia podem falhar |
| BUG-004 | High | Página pública aceita data livre em vez de slots calculados | Reservas fora da jornada |
| BUG-005 | High | Convite profissional cria token, mas não enfileira e-mail | Convite não chega |
| BUG-006 | High | Suporte sem mensagens, anexos e impersonation | Fluxo incompleto |
| BUG-007 | High | PDV sem cancelamento e estorno | Venda não pode ser revertida |
| BUG-008 | High | Planos Master possuem somente listagem | Gestão comercial incompleta |
| BUG-009 | Medium | Onboarding possui etapas apenas informativas | Promessa visual sem persistência |
| BUG-010 | Medium | Link profissional reutiliza página com todos os profissionais | Experiência inconsistente |
| BUG-011 | Medium | Listas sem paginação real | Risco de performance |

## Corrigidos e retestados

| ID | Problema | Correção | Reteste |
|---|---|---|---|
| FIX-001 | Links antigos quebrariam com `/a/{slug}` | rota de compatibilidade | lint/teste de rotas PASS |
| FIX-002 | Sem executor único de testes | criado `tests/run.php` | PASS |
| FIX-003 | Sem verificador CLI de instalação | criado `system-check.php` | executado |
| FIX-004 | Isolamento profissional incompleto | escopo derivado do vínculo server-side | ProfessionalIsolationTest PASS |
| FIX-005 | Migration usava `DELIMITER`, incompatível com PDO | triggers convertidos para instrução única | MigrationPdoCompatibilityTest PASS |
| FIX-006 | Ausência de provider/validador Mercado Pago | provider `/preapproval` e assinatura oficial | MercadoPagoWebhookTest PASS |
