# Segurança da migração

## Ação imediata

A auditoria identificou credenciais de banco e chave de aplicação com aparência de produção versionadas no repositório público. Elas devem ser consideradas comprometidas.

Antes do cutover:

1. Rotacionar a senha do banco legado.
2. Rotacionar a chave de aplicação/criptografia do PHP.
3. Rotacionar tokens de provedores que tenham passado pelo Git.
4. Remover segredos dos arquivos versionados.
5. Limpar o histórico Git e manter a rotação mesmo após a limpeza.
6. Manter segredos somente em variáveis/Secrets do Coolify.
7. Invalidar sessões/dispositivos confiáveis quando a troca de chaves exigir.

## Controles da base Django

- cookies Secure/HttpOnly/SameSite
- HSTS em produção
- CSRF nativo
- Argon2 para novas senhas
- compatibilidade temporária com bcrypt legado
- isolamento por tenant
- trilha de auditoria
- throttling na API
- segredos somente por ambiente
- healthcheck dedicado
- container executando como usuário sem privilégios
- Redis/Celery separados do processo web
