# Security Scorecard Remediated — 07/08/2026

| Controle | Antes | Depois | Evidência |
|---|---:|---:|---|
| Isolamento profissional | 3 | 8 | ProfessionalIsolationTest PASS |
| Sessão | 7 | 8 | timeout ocioso + absoluto |
| Migration/installer | 3 | 7 | MigrationPdoCompatibilityTest PASS |
| Webhook Mercado Pago | 1 | 7 | assinatura HMAC oficial + janela temporal PASS |
| Provider Mercado Pago | 1 | 6 | `/preapproval`, trial e idempotência testáveis por transport mock |
| Secrets | 7 | 8 | token somente server-side; instalador exige OpenSSL |
| Headers/config exposure | 7 | 8 | CSP/no-store/regras Apache |

CRITICAL corrigíveis no código trabalhado: 0 abertos. A ativação externa continua bloqueada até o servidor satisfazer os requisitos e receber credenciais Sandbox.

