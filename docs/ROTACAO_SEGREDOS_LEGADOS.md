# Rotação e saneamento de segredos legados

Nenhum valor confidencial deve ser anexado a issues, PRs, logs ou mensagens. Credenciais identificadas: chave legada `LEGACY_APP_KEY` (`config/app.php:10`) e senha do MySQL legado (`config/database.php:7`), ambas originadas no commit `e5c60c4b`. Remover o arquivo da árvore não revoga o segredo nem o elimina do histórico.

## MySQL legado

1. Identificar ambientes e clientes que ainda usam a credencial e restringir temporariamente o acesso por rede.
2. Fazer backup e criar nova credencial com privilégio mínimo para os consumidores necessários. Não reutilizar o mesmo segredo em PostgreSQL, SMTP ou gateways.
3. Atualizar configurações privadas e variáveis `LEGACY_MYSQL_PASSWORD`, testar cada conexão e importação em cópia isolada.
4. Revogar a credencial anterior, revisar auditoria do banco e verificar que a aplicação antiga não depende mais dela.

## Chave de criptografia legada

Não alterar diretamente a chave no ambiente: pode tornar integrações, dados e backups antigos irrecuperáveis. Não usar a chave do Django como substituta improvisada.

1. Inventariar os campos PHP criptografados e arquivos de backup que dependem da chave antiga. Validar uma restauração em ambiente privado antes de alterar qualquer consumidor.
2. Preservar a chave antiga em cofre separado com acesso restrito para a migração/recuperação; não armazená-la junto com backups públicos.
3. Implementar procedimento isolado e auditado de descriptografia pela chave antiga e recriptografia pela nova, com contagens, hashes e teste de amostras. Campos AES-GCM legados e backups precisam de tratamento compatível com seu formato específico.
4. Testar importação, integrações e restauração; só depois atualizar o ambiente e retirar a chave antiga do uso ativo. Planejar retenção privada para restauração de backups antigos ou recriptografar os backups.

As chaves `DJANGO_FIELD_ENCRYPTION_KEY` e `DJANGO_SECRET_KEY` não foram encontradas como segredos reais nesta varredura. Não foram rotacionadas. A chave Fernet continua a mesma; a atualização da biblioteca não é uma rotação.

## Histórico Git

Depois da rotação e mediante autorização específica, planejar saneamento com `git-filter-repo` em clone espelho separado. Antes:

- Exportar arquivos de recuperação indispensáveis para armazenamento privado e testar sua leitura/restauração.
- Inventariar refs, tags, forks, clones e integrações de deploy; agendar janela e comunicar aos colaboradores.
- Produzir clone saneado removendo configs privados e artefatos sensíveis; repetir Gitleaks e comparar código público antes/depois.
- Revisar o plano de atualização de refs e solicitar autorização explícita para force push. Nenhum comando de force push está automatizado nesta entrega.
- Pedir remoção de caches/referências no GitHub se necessário; colaboradores deverão reclonar ou seguir o procedimento definido. Forks/clones antigos ainda podem conter os segredos.

Proteção futura: exigir checks de Django e segurança nas configurações da branch e impedir bypass não revisado. Não usar allowlist para aceitar segredo real revogado no histórico de commits novos.
