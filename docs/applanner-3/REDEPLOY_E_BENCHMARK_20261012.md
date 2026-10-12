# ApPlanner: versão consolidada e comparação funcional

Data: 12/10/2026. Base auditada: django-replatform 9221c704. Entrega reunida no PR #26.

## Objetivo da entrega

Reunir o redesign e melhorias operacionais em uma única versão publicável pelo pipeline existente. Não há troca de stack, credenciais novas obrigatórias ou alteração de protocolos de pagamentos/WhatsApp. O redeploy existente executa migrations, seeds e collectstatic por bootstrap_application com trava PostgreSQL antes de disponibilizar a aplicação. As fotos privadas usam o volume media existente. Não foi executado deploy de produção.

## O que esta versão acrescenta

| Perfil | Entrega concreta | Limite explícito |
|---|---|---|
| Gestor | Calendário diário/semanal por profissional ou quadra; mudança de dia por arraste com validação e auditoria; busca por clientes, profissionais e serviços | Arraste mantém profissional e horário; no celular/teclado existe edição acessível. Atualização por polling, sem WebSocket |
| Gestor | Estoque separado entre revenda e insumos; fichas de consumo por serviço; baixa automática na conclusão; consumo avulso | Cadastros antigos continuam revenda. Configurar insumos/fichas para ativar baixa automática; estoque insuficiente impede fechamento |
| Gestor | Suprimento e sangria idempotentes; saldo do caixa considerando dinheiro e pagamentos mistos da comanda | Não altera permissões atuais da recepção; gestor autorizado opera abertura/fechamento |
| Gestor | Demonstrativo por competência, período e unidade, com categorias e estados pago/pendente | Demonstrativo gerencial; não é uma DRE contábil completa com tributos, CMV e centros de custo |
| Recepção | Agenda operacional, mudança de data, estados e comanda existentes preservados; recibo não fiscal para impressão 80 mm | Impressora física/ESC-POS não homologada; acesso financeiro segue autorização do backend |
| Profissional | Bloqueios pessoais futuros sem sobrepor reservas existentes; fichas técnicas e fotos restritas; consumo adicional de bancada no próprio atendimento aberto | Fotos exigem autorização, são reduzidas e têm metadados removidos; não são publicadas. Administração de solicitações LGPD permanece assistida |
| Profissional | Comissão no fechamento passa a respeitar regra fixa/percentual específica por serviço já existente nas comandas | Metas/escalonamento e dedução automática de insumos não estão implementados |
| Cliente | Área privada por código de e-mail: próprios agendamentos, reservas Arena, fidelidade/pacotes/assinaturas conforme módulo contratado | Exige e-mail único no cadastro da empresa e SMTP existente funcional; sessão de 30 minutos, código de 10 minutos/5 tentativas |
| Cliente | Até cinco serviços sequenciais, com profissionais diferentes ou qualquer disponível, confirmados em transação única e com idempotência | Fluxo para salão/barbearia; Arena/Automotivo preservam fluxo especializado. Pagamentos e notificações continuam por serviço |
| Cliente | Filtro “Tem horário hoje” com disponibilidade real da unidade e verificação canônica | Horário é uma fotografia da disponibilidade; reserva sempre revalida concorrência |
| Master | Busca de empresas e fundação visual compartilhada com o redesign já realizado | Busca exige superusuário; nenhuma autorização foi substituída por ocultação de links |

O redesign anterior permanece: tokens, Inter local, temas, sidebar vinculada às permissões, mobile/safe areas, landing, diretório e páginas públicas. Evidências e métricas anteriores estão em RELATORIO_20261012.md; estas métricas não certificam as novas telas nem produção.

## O que já existia e deve ser aperfeiçoado

| Função no repositório | Evidência principal | Próxima melhoria |
|---|---|---|
| Multiunidade e permissões | tenants, accounts/permissions.py, billing/entitlements.py | Franqueadora com consolidação, royalties e visões por grupo |
| Políticas de agenda, intervalos, folgas e conflitos | scheduling/availability.py, core/unit_settings.py | Explicar regras no onboarding e detalhar motivos de indisponibilidade |
| Comandas e pagamentos divididos | barber/models.py, barber/services.py | Jornada de caixa por cargo com autorização granular e conciliação por terminal |
| Comissão por produto e por serviço/profissional | finance/services.py, barber/services.py | Metas e faixas com vigência e snapshot auditável |
| Pix antecipado, sinal, webhooks | billing/tenant_payments.py, scheduling/public_api.py | Cobrança única de conjunto e cartão no agendamento, com estornos conciliados |
| Fidelidade, pacotes, mensalistas e uso | engagement | Regras de check-in e compra no portal, inadimplência/recorrência end-to-end |
| WhatsApp/e-mail e avaliações | communications, scheduling/ratings.py | Monitorar entrega, reenvios e opt-out; homologar provedor configurado |
| Ocupação, produtividade, retorno e funil | core/operation_insights.py, core/booking_funnel.py | Coortes/churn, ticket por segmento, consolidação histórica e exportação |
| PWA e proteção do cache | manifest/service worker existentes | Instalação física iOS/Android, Web Push com consentimento e ciclo de atualização |

## Matriz de lacunas após esta entrega

A lista enviada pelo usuário é um benchmark de produto. Não se presume que todos esses requisitos estejam disponíveis no AppBarber. A comparação externa usa documentação oficial, sem acesso a uma conta completa do concorrente.

| Módulo | Lacuna ou cobertura parcial | Prioridade | Valor de negócio |
|---|---|---|---|
| Gestor | DRE contábil estruturada: CMV, tributos, plano de contas, centros de custo, competência vs caixa | Alta | Margem e rentabilidade confiáveis |
| Gestor | Comissão por metas/faixas, vigência e desconto de insumos | Alta | Reduz cálculo manual e disputas de remuneração |
| Gestor | Cartão antecipado e cobrança única de múltiplos serviços | Alta | Conversão, sinal e conciliação mais simples |
| Gestor | Vouchers operacionais, vale-presente com saldo e cupons de atendimento | Média | Aquisição e receita antecipada; cupons SaaS existentes não equivalem a vale-presente |
| Gestor | Franqueadora: royalties e consolidação entre empresas | Média | Escala; multiunidade atual não equivale a franquias |
| Recepção | Permissão granular para caixa financeiro por cargo, sem liberar todo financeiro | Alta | Operação segura e delegável |
| Recepção | Homologação de impressora térmica/ESC-POS, terminal e fluxo fiscal | Média | Rapidez e compatibilidade de balcão |
| Recepção | Fila por chegada como operação completa, distinta da lista de espera por vagas | Média | Atendimento walk-in previsível |
| Profissional | Web Push instantâneo e sincronização com sinalização de entrega | Alta | Reduz atrasos e perda de novas reservas |
| Profissional | Edição/retificação e política de retenção das fotos técnicas | Média | Controle e governança da ficha |
| Cliente | Web Push/SMS com fornecedor, consentimento e monitoramento | Alta | Cobertura de lembretes fora do e-mail/WhatsApp |
| Cliente | Conta unificada entre empresas com identidade verificada e consentimentos | Média | Reutilização dos dados sem quebrar isolamento |
| Cliente | Compra/renovação de assinatura e check-in pelo cliente | Alta | Retenção e recorrência com menos recepção |
| Plataforma | Testes físicos PWA, integrações reais e performance de produção | Alta | Evidência de qualidade, além dos testes de código |

## Roadmap técnico

1. **Essencial:** validar esta versão em homologação e o fluxo completo cliente → profissional → financeiro. Definir permissão de caixa por ação; fila por chegada; monitoramento de notificações; testes físicos PWA. Cada item deve ter teste de isolamento e jornada por perfil.
2. **Financeiro e retenção:** DRE estruturada, comissões por faixas/vigência, vale-presente/saldo, cartão e pagamento único de conjunto; compra e consumo de mensalistas pelo portal. Usar ledger auditável, snapshots, idempotência e testes de estorno/concorrência.
3. **Escala e BI:** consolidação de grupos/franquias, coortes de retenção, churn e margem, Web Push monitorado, otimização de disponibilidade em grandes diretórios e métricas de produção. Medir antes de chamar de superior.

## Validação e migrations

Testes locais direcionados: 81 descobertos, 78 aprovados, 3 de concorrência PostgreSQL ignorados no SQLite. Estes três exigem o CI com PostgreSQL. Todos os 20 testes Node passaram. Lint F401/F821/F822/F823, Django check, migrations sem drift e collectstatic devem ser novamente conferidos no head final.

Migrations aditivas: finance 0009 (tipo de estoque, caixa/consumos/fichas) e scheduling 0020–0022 (desafios de acesso, fichas privadas, grupos de reservas). Nenhuma remoção de empresa, cliente ou movimentação. Não executar reversão de schema em produção: retornando à imagem anterior, manter as tabelas e registros novos; reconciliar consumos/reservas já realizados. Backup verificado e armazenamento persistente continuam requisitos da operação.

## Publicação em um redeploy

- Usar a versão final do PR #26 baseada em django-replatform; não misturar versões dos containers web/worker/beat.
- Pipeline final completo deve aprovar PostgreSQL, Redis, migrations, secrets, dependências, Docker e restore drill.
- Preservar variáveis, chaves de criptografia, PostgreSQL/Redis e volumes existentes. SMTP precisa funcionar para o portal do cliente. Nenhuma chave nova de pagamento/WhatsApp é introduzida.
- Garantir que `/media/private/` seja encaminhado ao Django, sem servidor/proxy externo expondo diretamente essa pasta. A aplicação bloqueia URLs públicas e oferece endpoint autenticado para fotos.
- Confirmar backup operacional e versão anterior disponíveis; iniciar pelo ambiente de homologação. O bootstrap já automatiza preparação de banco e estáticos.
- Após redeploy: health check, landing, login, seleção de unidade, reserva simples e múltipla, agenda, conclusão com insumos, comissão/caixa e tentativa de acesso indevido. Confirmar entrega SMTP/WhatsApp conforme configuração real.
- Não há evidência de deploy ou backup da produção nesta sessão. A publicação depende do ambiente Coolify ao qual não foi disponibilizado acesso.

## Referências externas

- https://appbarber.com.br/funcionalidades/ — comunicação, agenda, site, estoque/comandas e recursos gerais.
- https://atualizacoes.appbarber.com.br/ — evolução oficial de agenda/assinaturas/feedback.
- https://blog.appbarber.com.br/2026/04/10/appbarber-clube-assinaturas-barbearia/ — clube e recorrência.

O código pode ganhar vantagens em descoberta pública, experiência web, composição modular e segmentos especializados. Isso é uma oportunidade de diferenciação, não uma prova de superioridade sobre o concorrente.
