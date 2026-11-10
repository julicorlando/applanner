# Continuação da auditoria da migração — 29/09/2026

Branch: `django-replatform`. O SQL original permanece fora do repositório.

## Antes desta continuação

Já havia os portais Master, empresa e Comercial; segmentação Barber/Auto/Arena; agenda, financeiro/PDV, relacionamento, suporte, RBAC, modelos e jobs de campanhas, Growth/Meta CAPI e conexões de pagamento, ETL e auditoria de paridade. Os modelos de campanha e de conexão por empresa não tinham uma operação completa para cadastrar pela interface; os formulários públicos não geravam eventos de aquisição.

## Verificação do dump

O arquivo `appnannerbr_planner(1).sql` foi processado com `legacy_dump_inventory.py`: 192 tabelas, 2.150 colunas, 413 chaves estrangeiras e cerca de 25.061 linhas `INSERT` em 54 tabelas. A comparação de nomes com `import_legacy_specialized.SPECS`, `audit_legacy_parity.DIRECT` e `TRANSFORMED` mostrou 192/192 tabelas cobertas por estratégia. O inventário de todos os campos, tipos e relacionamentos já está em `legacy-schema-inventory-20260923.csv`. Essa análise estática não comprova valores importados no PostgreSQL.

Os dados relevantes deste dump incluem 17 módulos, sete planos, 50 vínculos plano/módulo, uma assinatura/empresa, 1.209 contatos de marketing, 1.284 entregas, 546 eventos de aquisição, 1.610 eventos de produtos, 1.292 jobs e 18.014 registros de cron. O dump não possui dados de agendamentos, clientes, profissionais, vendas ou operações Barber/Auto/Arena para ensaiar a paridade desses fluxos.

## Implementação

- Master cria, acompanha e interrompe campanhas de e-mail; importa contatos autorizados por CSV, sem reativar opt-outs. As entregas são geradas somente para contatos ativos com consentimento registrado, e o envio confere novamente esse estado.
- E-mail de campanha inclui descadastro público com confirmação explícita e URL absoluta quando `PUBLIC_BASE_URL` está configurada.
- O proprietário conecta sua conta Mercado Pago, vê o webhook da própria empresa e gira credenciais sem revelar segredos. A conexão é validada pelo serviço existente.
- Os formulários públicos de cadastro e plano personalizado preservam parâmetros UTM na sessão e registram eventos de aquisição. Esses eventos não são marcados com consentimento de marketing para Meta CAPI automaticamente.
- Testes verificam autorização, isolamento de empresas, segredos, consentimento/opt-out e captura de UTM. Não houve mudança de modelo ou migration.

## Ainda necessário para declarar paridade total

Executar `import-legacy-dump.ps1` com MariaDB isolado, PostgreSQL de homologação e `LEGACY_APP_KEY` aplicável, e depois `audit_legacy_parity --strict`. Confirmar importação dos uploads com `sync_legacy_media`, reconciliação de saldos/transações, plano/módulos/assinatura e papéis, além de fluxos PHP/Django com dados de operação reais. A auditoria de valores existente é aprofundada no catálogo/RBAC/assinaturas; não compara todo campo das 192 tabelas. É preciso validar credenciais SMTP, Mercado Pago, WhatsApp e Meta, webhooks externos, entregas e pagamentos em sandbox, segurança/retentativa e rollback do cutover. A interface permanece Django templates em grande parte; a reescrita integral em React solicitada anteriormente não está concluída. Não houve deploy nem alteração da `main` nesta continuação.
