# Security Audit

## Corrigido

- **CRÍTICO — tenant escape/IDOR:** controllers comerciais usam TenantContext e filtros compostos.
- **CRÍTICO — webhook forjado/replay:** HMAC SHA-256, janela de 5 minutos, event ID único e transação; preço nunca vem do payload.
- **ALTO — double booking:** lock MySQL por tenant/profissional e nova validação dentro da transação.
- **ALTO — segredos expostos:** SMTP, WhatsApp e webhook são cifrados com AES-256-GCM e nunca retornam à tela.
- **ALTO — replay TOTP:** último timestep aceito é persistido e códigos anteriores são rejeitados.
- **ALTO — campanhas sem consentimento:** seleção exige o consentimento vigente específico do canal.
- **MÉDIO — double submit financeiro:** unique key por tenant/idempotency key.
- **MÉDIO — input de vencimento:** data agora usa formato estrito antes do PDO.

## Production Security Blockers

### Critical blocker

- Testes dinâmicos Tenant A×B, webhook e concorrência ainda não foram executados porque não há banco/configuração instalados.

### High priority

- Assets Bootstrap ainda usam CDN e CSP permite estilo inline.
- Não existe módulo clínico; qualquer lançamento futuro exige policy e suíte independente.
- Backup local ainda não possui criptografia/restore administrado.

### Recommended

- Sessões por dispositivo, reautenticação para ações Master e teste real dos providers.
# Red Team corretivo — 07/08/2026

## Resultado

- **CRÍTICO corrigido:** isolamento da agenda profissional. Listagem, seleção na criação, gravação e alteração de status agora derivam `professional_id` do vínculo server-side `users → professionals`; o valor enviado pelo navegador é ignorado para esse papel.
- **ALTO corrigido:** timeout absoluto de sessão, além do timeout ocioso, centralizado em `config/security.php`.
- **MÉDIO corrigido:** respostas autenticadas recebem `Cache-Control: no-store`.
- **MÉDIO corrigido:** CSP, Permissions-Policy e bloqueio HTTP de arquivos operacionais reforçados no Apache.
- SQL injection: INSPECIONADO; entradas de valor observadas usam prepared statements e PDO desativa emulação.
- XSS: INSPECIONADO; views auditadas fazem escaping de dados exibidos. Não houve browser E2E por ambiente não instalado.
- Segredos: INSPECIONADO; nenhum segredo literal encontrado no scan local. Configurações sensíveis usam `Encryption`.
- Upload/prontuário/impersonation: NOT IMPLEMENTED; não há endpoint exposto, mas estes fluxos precisam de nova auditoria quando implementados.
- Mercado Pago: BLOCKED/NOT IMPLEMENTED. O webhook genérico possui HMAC, janela temporal e idempotência, mas não equivale à validação oficial do Mercado Pago.

Decisão: **SECURITY PRODUCTION NO-GO** enquanto Mercado Pago oficial, MySQL E2E e extensões `openssl`/`mbstring` permanecerem ausentes.
