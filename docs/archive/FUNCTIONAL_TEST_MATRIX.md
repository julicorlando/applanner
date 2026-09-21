# Matriz final de testes

| ID | Módulo | Cenário | Pré-condição | Esperado | Obtido | Status | Bug/Fix |
|---|---|---|---|---|---|---|---|
| QA-001 | PHP | Lint de todos os PHP | PHP CLI | zero erros | zero erros | PASS | - |
| SEC-001 | Tenant | SQL sempre escopado | código atual | sem escape | assertions aprovadas | PASS | - |
| SEC-002 | Auth | reset seguro | código atual | hash/expiração/uso único | assertions aprovadas | PASS | - |
| SEC-003 | CSRF | mutações protegidas | código atual | rejeitar token inválido | assertions estáticas | PASS | E2E bloqueado |
| PUBLIC-001 | Booking | link tenant curto | migration+rota | resolver sem ID | assertions aprovadas | PASS | compatibilidade legada adicionada |
| PUBLIC-002 | Booking | link profissional | migration+rota | profissional ativo do tenant | assertions aprovadas | PASS | tela dedicada parcial |
| PUBLIC-003 | Booking | persistir e impedir duplicidade | MySQL teste | 1 appointment | não executado | BLOCKED | sem MySQL/config |
| PROF-001 | Profissional | criar acesso | MySQL+SMTP | convite e senha única | não executado | BLOCKED | envio do convite incompleto |
| PROF-002 | Agenda | profissional vê somente a sua | MySQL | filtro por professional_id | controller não filtra | FAIL | Critical aberto |
| SALE-001 | PDV | preço server-side | código atual | ignorar preço cliente | SQL usa product.sale_price | PASS | inspecionado |
| SALE-002 | Estoque | venda concorrente | MySQL | lock e estoque 10→9 | `FOR UPDATE` presente | PARTIAL | execução bloqueada |
| BILL-001 | Checkout | adulterar preço | código atual | quote do banco | assertion aprovada | PASS | inspecionado |
| BILL-002 | Gateway | Mercado Pago oficial | credencial sandbox | assinatura/webhook | provider ausente | FAIL | Blocker comercial |
| SUP-001 | Suporte | abrir chamado | MySQL | persistir protocolo | não executado | BLOCKED | sem DB |
| SUP-002 | Suporte | conversa/impersonation | implementação | auditado | ausente | FAIL | High aberto |
| AUTH-001 | Auditoria | login sucesso/falha | MySQL | 2 registros | SQL presente | PARTIAL | execução bloqueada |
| INST-001 | Instalação | banco vazio | MySQL | configs+Master+lock | não executado | BLOCKED | serviço MySQL ausente |
| E2E-001 | Navegador | landing→booking | app instalada | fluxo persistente | não executado | BLOCKED | app não instalada |
| BKP-001 | Backup | criar/restaurar | MySQL | arquivo restaurável | não executado | BLOCKED | sem DB |

Execute a regressão local com `php tests/run.php` e a prontidão ambiental com `php system-check.php`.
