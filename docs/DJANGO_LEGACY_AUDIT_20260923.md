# ApPlanner — auditoria do dump de 23/09/2026

Branch auditada: `django-replatform` (base `363fe40`). Arquivo de origem: `appnannerbr_planner(1).sql`, SHA-256 `340f0f177e976d874eb8d86f472ed63afb17ec468b5af9ced1c795e5a21416ee`. O dump **não** foi versionado. [Inventário de esquema](legacy-schema-inventory-20260923.csv): para cada uma das 192 tabelas, relaciona todas as colunas/tipos, FKs e número de tuplas dos `INSERT` do dump, sem valores de linhas.

## Estado encontrado antes das correções

A branch já possuía base Django, migrations, portais Master/Comercial/Barber/Auto/Arena/Financeiro/relacionamento, RBAC, planos, módulos, pagamentos, comunicação, LGPD, backup, ETL core/especializado e auditoria de contagens/IDs. O importador tinha 165 especificações de tabelas especializadas, 25 estratégias diretas e duas tabelas transformadas. Os portais e modelos existentes não constituem prova isolada de paridade em produção.

## Descobertas no SQL

192 tabelas, 2.150 colunas e 413 relações de chave estrangeira. Há linhas `INSERT` em 54 tabelas (25.061 tuplas, contadas por linha `VALUES`). Catálogo presente: 17 módulos, sete planos, 50 vínculos de planos e módulos, uma assinatura e uma empresa. Outros volumes relevantes: 1.209 leads de marketing, 1.284 entregas, 1.610 eventos de produto, 18.014 batimentos de cron, 1.292 jobs, quatro usuários e 223 vínculos de papel/permissão. Não há linhas de clientes, serviços, profissionais, agendamentos, vendas, comandas Auto/Barber/Arena, mensalidades ou arquivos de mídia nesse dump. A existência de suas tabelas não valida esses fluxos com dados reais.

A comparação das colunas do SQL com o destino Django encontrou 13 campos especializados sem destino: três de `customer_memberships`, sete de `support_tickets`, um de `support_access_sessions`, e duas datas `created_at` em Auto. Também identificou o vínculo `appointments.vehicle_id`, presente no SQL mas ausente do modelo e do ETL. O fluxo de criação de recorrência armazenava o link de autorização apenas em memória. A rotina de cobranças manuais considerava mensalidades processadas pelo provedor e avançava datas por 30/90 dias, quando o legado usa meses de calendário.

## Alterações feitas nesta auditoria

- Novos campos e migrations preservam cobrança automática, contexto/consentimento de suporte e datas de criação de Auto; migration de dados recupera vínculos com assinaturas do provedor já gravadas no Django.
- O vínculo agendamento→veículo agora é preenchido após o ETL de veículos, com verificação de empresa e cliente. O formulário da agenda permite associar o veículo com essa mesma validação. A auditoria estrita compara os vínculos migrados.
- Criação e webhook de recorrência persistem estado e URL do provedor. O portal mostra o estado e o link HTTPS de autorização. A rotina de cobrança manual exclui assinaturas do provedor e usa meses de calendário.
- A tela de suporte permite ao solicitante registrar e revogar consentimento para acesso; a revogação encerra registros de acesso ainda abertos. A execução de uma sessão de impersonação não foi implementada nesta revisão.
- Testes cobrem persistência da recorrência, prevenção da cobrança manual, datas mensais, isolamento do vínculo com veículo e autorização/revogação de suporte.

## Limites para declarar 100%

Ainda é necessário executar `django/scripts/import-legacy-dump.ps1` contra o dump em MariaDB isolado e PostgreSQL real, com `LEGACY_APP_KEY` quando aplicável, e validar `audit_legacy_parity --strict`. A auditoria existente compara contagens, IDs e cobertura de colunas especializadas, mais o novo vínculo de veículo; não compara todos os valores campo a campo. O catálogo (preços, regras, addons, assinatura) precisa de reconciliação funcional e financeira com a produção antes de cutover.

Os uploads reais, segredos/chaves de integração e acesso aos provedores não acompanham o SQL. Necessitam migração de mídia, recriptografia, testes de webhooks, e-mail, WhatsApp e pagamentos em sandbox. É necessária homologação paralela PHP/Django com agenda, PDV, estoque, comissões, segmentos Auto/Arena/Barber e suporte, pois essas tabelas não têm linhas no dump. O fluxo de impersonação do suporte ainda carece de uma implementação segura com sessão e auditoria ativa. CI PostgreSQL/Redis da branch e ensaio de cutover/rollback devem ficar verdes antes de qualquer alegação de paridade total. A `main` não foi alterada.
