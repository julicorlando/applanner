# Production Remaining Blockers

| ID | Módulo | Severidade | Sintoma/causa | Correção necessária |
|---|---|---|---|---|
| ENV-001 | Servidor | Blocker | PHP sem OpenSSL, mbstring e cURL | habilitar extensões |
| ENV-002 | Banco | Blocker | MySQL e configuração ausentes | instalar banco de teste e executar instalador |
| MP-EXT-001 | Billing | High externo | sem credenciais Sandbox | configurar e validar provider real |
| FUNC-001 | Public booking | High | slots/jornada/folgas ainda incompletos | implementar disponibilidade persistente |
| FUNC-002 | Support | High | conversa e acesso assistido incompletos | implementar policy, timeline e sessão auditada |
| FUNC-003 | Sales | High | cancelamento/estorno ainda ausente | transação de reversão auditada |
| FUNC-004 | Master | High | CRUD de planos incompleto | operações protegidas e snapshots |

