# Segurança e LGPD

Foram revisados isolamento por tenant/unidade, CSRF, cookies, 2FA, sessões, tokens com escopo, suporte assistido, exportação, exclusão e consentimento. Correções incluídas: proteção do `/admin/`, limite de tentativas de login/2FA, consumo atômico de recovery/TOTP, bloqueio de ações LGPD durante impersonação e redirects jurídicos somente same-origin.

A evidência é de código e testes automatizados. Ainda faltam pentest externo, revisão de infraestrutura/Cloudflare, rotação observada de segredos e validação de políticas de retenção com dados de produção.
