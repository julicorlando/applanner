# Bloqueadores de segurança restantes

| ID | Severidade | Causa | Correção necessária | Motivo |
|---|---|---|---|---|
| SEC-ENV-001 | CRITICAL BLOCKER | PHP ativo sem `openssl`, `mbstring` e `curl` | habilitar extensões no PHP do servidor | configuração externa ao projeto |
| SEC-ENV-002 | CRITICAL BLOCKER | Sem MySQL/config/lock | instalar em banco exclusivo de teste e executar E2E | serviço externo ausente |
| SEC-MP-001 | HIGH | Credenciais Mercado Pago Sandbox ausentes | configurar token/secret e validar chamada real | BLOCKED EXTERNAL |
| SEC-E2E-001 | HIGH | Isolamento/double booking/estoque não executados com persistência | rodar testes em MySQL | depende de SEC-ENV-002 |

