# Checklist de paridade funcional

## Fundação concluída

- [x] Base Django e Docker/Coolify
- [x] PostgreSQL + Redis + Celery/Celery Beat
- [x] Migrations versionadas e CI com PostgreSQL/Redis reais
- [x] Healthcheck de banco/cache
- [x] Multi-tenant / multiempresa
- [x] Usuário por e-mail, bcrypt PHP -> Argon2
- [x] 2FA, recovery codes e trusted devices
- [x] RBAC estrutural e revogação de sessão
- [x] Staticfiles/WhiteNoise e ambiente local VS Code/Docker
- [x] Portal operacional inicial fora do Django Admin

## Núcleo operacional

- [x] Clientes, profissionais, serviços e agendamentos
- [x] Expediente, intervalos, folgas, slots e bloqueio de conflito
- [x] Portal: clientes, profissionais, serviços e agenda
- [x] Financeiro, estoque, POS e comissões
- [x] Portal: lançamentos, produtos e comissões
- [x] Notificações, campanhas e e-mail marketing
- [x] WhatsApp provider/webhook, tracking de e-mail e handoff humano
- [x] Planos, assinaturas, módulos, checkout e Mercado Pago
- [x] Pix, cartão tokenizado, recorrência e webhooks HMAC
- [x] Branding, multiunidade e páginas públicas base

## Segmentos

- [x] Barbearia: fila, comanda, remuneração, metas, estoque e financeiro
- [x] Portal de fila/comandas (consulta de comandas; operações avançadas ainda em evolução)
- [x] Arena: quadras, reservas, preços, bloqueios, mensalistas, jogos, waitlist, turmas, torneios e comandas — modelos
- [x] Arena: reserva com cálculo/validação de disponibilidade e preço
- [x] Portal Arena: quadras, reservas, mensalistas, turmas e torneios
- [x] Auto: veículos, boxes, OS, inspeção, materiais, orçamento, comanda, manutenção e CRM — modelos/serviços
- [x] Portal Auto: veículos, boxes, OS e orçamentos
- [x] Saúde: prontuário criptografado e auditoria de acesso
- [x] Portal Saúde: criação/leitura criptografada de prontuário

## Relacionamento e crescimento

- [x] Pacotes, créditos, mensalidades
- [x] Fidelidade e recompensas
- [x] Lista de espera
- [x] Referral estrutural
- [x] Portal de relacionamento
- [x] Blog, diretório público e landings
- [x] UTM/acquisition, Meta CAPI e traduções públicas
- [x] Comercial: leads, propostas, aceite, comissões e LGPD — backend
- [x] Support tickets, incidents, homologation, cron health e backup metadata — backend

## Migração de dados e jobs

- [x] ETL de núcleo MySQL -> PostgreSQL
- [x] ETL especializado para tabelas de módulos
- [x] Recriptografia AES-256-GCM PHP -> Fernet Django
- [x] Celery Beat para jobs principais e especializados
- [ ] Validar ETL especializado contra clone real do MySQL legado
- [ ] Migrar/copy de uploads e mídia do legado
- [ ] Validar contagens/checksums por tabela antes do cutover

## Paridade ainda necessária antes de substituir o PHP

- [ ] Portal Comercial completo (fila de leads, proposta, aprovação/aceite e comissões)
- [ ] Portal Master completo (tenants, planos, financeiro plataforma, suporte, incidentes, backups e homologação)
- [ ] Arena: UI de jogos/rachas, jogadores, attendance/makeup, chaveamento de torneio e fechamento de comanda
- [ ] Auto: UI de inspeção/fotos/materiais/etapas/orçamento público e fechamento de comanda
- [ ] Barbearia: UI de itens/pagamentos/fechamento de comanda, metas e remuneração
- [ ] Financeiro: UI de venda/POS, caixa e baixa/pagamento de comissões
- [ ] Pacotes: compra, consumo de crédito e billing recorrente pela UI
- [ ] Fidelidade/referral: emissão/resgate/referral attribution pela UI
- [ ] Custom domain: roteamento por Host + validação/ativação do domínio
- [ ] Legal/LGPD: aceite obrigatório e telas de consentimento/documentos
- [ ] Backup real: execução/restauração, não apenas catálogo/verificação
- [ ] Aplicar RBAC granular em todas as telas do portal
- [ ] Ampliar testes de regressão das operações especializadas
- [ ] Homologação paralela PHP x Django com dados reais
- [ ] Cutover/rollback documentado e executado

## Regra de produção

A branch `django-replatform` permanece de homologação. A `main` não deve ser substituída enquanto ETL real, paridade crítica, backups, CI e smoke tests não estiverem aprovados.
