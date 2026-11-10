# ApPlanner 3.0 — execução, homologação e análise funcional

Data: 12/10/2026. Repositório: julicorlando/applanner. Base auditada: django-replatform, commit 9221c7047a5cac1d09bdb65ece84d10b92e6c40e. Branch: feat/applanner-3-premium-20261012. PR: https://github.com/julicorlando/applanner/pull/26.

## A. Resumo executivo e limite da entrega

Foram feitas alterações reais no Django, templates, CSS, JavaScript e recursos estáticos. A entrega acrescenta navegação lateral com busca, identidade azul compartilhada, fonte Inter hospedada pelo próprio aplicativo, melhorias de contraste, formulários e superfícies, além de atualizar a apresentação pública e a descoberta por unidade. Empresa, Master, agenda, profissional, login e telas que estendem o layout comum recebem a mesma fundação visual.

**O escopo completo do prompt mestre não está certificado como concluído.** O PR permanece rascunho. A validação local não substitui homologação com PostgreSQL/Redis, integração bancária/WhatsApp configurada, dispositivos físicos e ambiente de staging. Não houve merge, alteração do banco de produção ou deploy. Não foram inventados indicadores comerciais, depoimentos ou preços de produção.

O PR #22 já estava mesclado. O PR #24 estava aberto: suas quatro alterações visuais foram preservadas na nova branch, sem retroceder o merge posterior do agente de atendimento. O PR #24 continua aberto; sua eventual integração precisa considerar a sobreposição desses quatro arquivos.

## B. Antes e depois

As capturas foram geradas do aplicativo real, em dois checkouts: base 9221c704 e versão modificada. Ambos usaram o mesmo banco descartável e dados explicitamente fictícios, sem clientes ou finanças reais. Há capturas de landing, Explorar, login, página pública, dashboard Empresa, operação, agenda, Master e profissional em desktop 1440×1000 e mobile 390×844. Há capturas adicionais de tema escuro, revisão e confirmação de reserva.

O pacote de evidências acompanha este relatório. A imagem utilizada no hero é uma captura real do painel local, identificada na página como demonstração. Não é uma medição de resultados comerciais.

## C. Modificações técnicas

| Área | Alteração efetiva | Preservação |
|---|---|---|
| Fundação visual | premium.css com aliases da paleta existente, tokens de espaçamento/bordas/elevação, estados acessíveis e Inter variável local | Sem biblioteca frontend nova ou troca de framework |
| Navegação privada | core/workspace.py, workspace_sidebar.html e workspace.js; grupos e links derivam de available_modules | Entitlements e RBAC continuam decididos no backend; assinatura bloqueada recebe apenas pagamento; profissional recebe sua própria área |
| Landing | Hero, CTA, segmentos e seção de gestão; screenshot real, imagens responsivas e fonte pré-carregada | Catálogo real de planos, marca configurável, segmentos e preços não foram substituídos por dados da referência |
| Explorar | Busca normalizada de nome/cidade/CEP por unidade; segmento; avaliações publicadas da empresa; raio 5/10/20/30 km | Geolocalização por ação explícita, limite máximo de 30 km, unidades independentes e ausência de avaliação fictícia |
| Página pública e login | Integração do layout público do PR #24; melhora de contraste e nome acessível do seletor de serviço | IDs, CSRF, comportamento progressivo, Pix, módulos opcionais e reservas Arena mantidos |
| Empresa e Master | Sidebar, superfícies, indicadores, tabelas, estados vazios e financeiro em temas coerentes | Dados existentes e permissões; não foram adicionados gráficos com números simulados |
| Mobile/PWA | Safe areas, alvos de toque, fonte de formulário, contraste e paleta de metadata/ícones; versão do cache atualizada | Cache continua limitado a estáticos públicos fingerprintados; contas, pagamentos e APIs ficam online |

Arquivos principais: django/templates/base.html, home.html, accounts/login.html, tenant_public.html, contenthub/directory.html, workspace_sidebar.html; django/core/workspace.py; django/contenthub/views.py; django/static/css/premium.css e public-experience.css; django/static/js/workspace.js, theme.js e app-worker.js; django/core/web_app.py; django/applanner/settings.py; fontes licenciadas e imagens demonstrativas em django/static.

Não há migrations novas. Os arquivos de infraestrutura, providers, webhooks e protocolos WhatsApp não foram modificados. O conjunto legado de CSS ainda existe; a nova camada centraliza a identidade, mas sua consolidação definitiva requer regressão visual em todos os templates.

## D. Testes e homologação

### Resultados locais

- 76 testes Django relevantes passaram, incluindo os oito novos testes de descoberta/navegação, identidade pública, multiunidade, PWA, agenda, permissões e reservas Arena. Banco local: SQLite. Isso **não comprova concorrência PostgreSQL**.
- 20 testes JavaScript existentes passaram: seleção de horários, requisições antigas, funil, validação em português, instalação e segurança do service worker.
- Django system check: sem erros. Makemigrations --check --dry-run: nenhuma alteração. Collectstatic: aprovado. Pip check: aprovado. Ruff F401/F821/F822/F823: aprovado. Política de artefatos do repositório: aprovada.
- Navegador Chromium: nove telas antes/depois, desktop/mobile, HTTP 200 e nenhum erro de JavaScript capturado.
- Axe: oito áreas nos temas claro e escuro, regras WCAG 2 A/AA, 2.1 AA e 2.2 AA, sem violações automatizadas na rodada final. Existem verificações que exigem análise humana; zero violações não certifica conformidade WCAG.
- Sem rolagem horizontal nas oito áreas verificadas em 320, 390, 768, 1024 e 1440 px.
- E2E no navegador: selecionar serviço → qualquer profissional → data de amanhã → horário real → contato → revisão → confirmação. A confirmação mostrou serviço/profissional corretos e a reserva apareceu na área do profissional.

### Roteiro de aceite

| Fluxo | Evidência disponível | Pendência |
|---|---|---|
| Landing | Navegador desktop/mobile, temas e Lighthouse | Smoke test depois do deploy |
| Iniciar teste grátis | CTA e catálogo mantidos; código existente | Nova contratação completa em staging |
| Onboarding | Roteiro existente recebe estilos compartilhados | Cadastro empresarial completo em staging |
| Unidade, profissional e serviço | Testes relevantes existentes e fixtures isoladas | Criação completa pela UI com diferentes perfis |
| Explorar | Testes novos de busca, CEP, distância, avaliações e ocultação médica; navegador | Localização GPS real e CEP sem coordenadas em dispositivo |
| Página pública | Testes multiunidade e identidade; navegador | Capa/logos reais em diferentes formatos |
| Serviço/profissional/data/horário | E2E com disponibilidade real local | Mais combinações de duração e regras |
| Confirmação e área do profissional | E2E local com uma reserva real no banco descartável | Integrações externas configuradas |
| Agenda da empresa e financeiro | Testes selecionados e capturas com fixtures | Jornada de fechamento/caixa ponta a ponta |
| Alternância de unidade | Testes existentes de isolamento/seleção | Homologação operacional em staging |
| Master e acesso restrito | Capturas, RBAC e testes da navegação | Perfis administrativos delegados em staging |
| Tema claro/escuro | Axe, screenshots e navegador | Telas raras e conteúdos reais |
| PWA | Manifest/ícones/cache/instalação em testes automatizados | Instalação física iOS e Android, teclado e retomada de sessão |
| Concorrência de reserva | Lógica existente preservada | Execução e evidência PostgreSQL/Redis no CI/staging |

## E. Performance medida

Lighthouse mobile, ambiente local de desenvolvimento, dados fictícios e rede/CPU simuladas. Não são métricas de produção nem dados de usuários reais. Variações entre execuções são esperadas.

| Página | Performance antes | Performance depois | Acessibilidade antes/depois | Best Practices | SEO |
|---|---:|---:|---:|---:|---:|
| Landing | 97 | 94 | 91 / 96 | 100 | 100 |
| Explorar | 98 | 97 | 94 / 96 | 100 | 100 |
| Página pública | 97 | 97 | 90 / 100 | 100 | 100 |

Landing após otimização: LCP 2,75 s, CLS 0, TBT 0 ms. Explorar: LCP 2,38 s, CLS 0,034, TBT 0 ms. Página pública: LCP 2,09 s, CLS 0,003, TBT 0 ms. A landing ultrapassa a meta inicial de 2,5 s para LCP; ainda precisa medição em staging com compressão e cache de produção. A imagem foi reduzida de 76 KB para variantes aproximadas de 20/40 KB; foi acrescentado preload da fonte. A primeira medição do redesign foi 92, melhorando para 94 com essas otimizações.

## F. GitHub e CI

PR #26: https://github.com/julicorlando/applanner/pull/26. Base django-replatform. Commit inicial publicado: b8c731ca2ab94ffaca36d666015d8538d044c61c. A árvore desse commit foi comparada com a árvore local e era idêntica.

Os resultados finais de CI e o commit de otimização/documentação devem ser registrados no fechamento do relatório. Evidências locais não devem ser apresentadas como execução do pipeline completo.

## G. Publicação e rollback

Sem deploy. Não foi disponibilizado acesso operacional ao Coolify neste ambiente. Antes de publicar: homologar o PR em staging, verificar os serviços e variáveis pelo fluxo existente sem imprimir segredos, confirmar backup/restore recente, conferir todos os jobs do CI e executar as jornadas ainda pendentes. Não aplicar migrations de produção durante uma mera revisão visual.

A alteração não exige migration nova. Rollback da aplicação pode usar a imagem/commit anterior e seus estáticos; não há esquema novo a reverter. A nova versão do service worker só gerencia cache público de arquivos fingerprintados. Após o deploy, medir novamente domínio, HTTPS, arquivos estáticos, sessões, temas, geolocalização, reserva real autorizada e instalação mobile.

## H. Avaliação provisória por evidências

Notas de julgamento do trabalho observado, não certificações nem promessa de produto concluído.

| Dimensão | Nota / 10 | Fundamentação e limite |
|---|---:|---|
| Identidade visual | 8,2 | Paleta, Inter e fundação comum; ainda há estilos legados |
| UX | 7,8 | Busca no menu e descoberta por unidade; faltam jornadas completas de contratação/PDV |
| Responsividade | 8,5 | Cinco larguras sem overflow nas áreas verificadas; conteúdos reais ainda pendentes |
| PWA | 7,0 | Manifest/cache/ícones testados; instalação física não homologada |
| Agendamento | 8,2 | E2E confirmado e profissional visualizou; concorrência e integrações externas não homologadas nesta rodada local |
| Painel Empresa | 8,0 | Sidebar baseada em permissões e indicadores reais; calendário e comandos de operação requerem revisão aprofundada |
| Painel Master | 8,0 | Identidade e navegação comum; fluxos administrativos extensos não foram todos percorridos |
| Acessibilidade | 8,0 | Zero violações axe na amostra; leitor de tela e teste manual completo pendentes |
| Performance | 8,5 | Pontuações locais 94–97; LCP da landing e métricas de campo pendentes |
| Consistência visual | 8,1 | Layout compartilhado cobre áreas principais; dívida de CSS ainda presente |

## I. Comparação funcional — quatro perfis

### Método

Comparação da lista de benchmark fornecida com modelos, serviços, rotas e interfaces da base atual. “Ausente” significa que não foi encontrada implementação equivalente no fluxo auditado; um enum, campo genérico ou tela oculta não comprova uma capacidade operacional. “Parcial” significa que a base existe e uma parte relevante do requisito falta. Nenhum item foi criado nesta análise funcional.

Foram consultadas fontes oficiais do AppBarber. Sua página de funcionalidades descreve agenda, comanda, estoque, pagamentos online, fidelidade e comissões. A central oficial descreve inclusão de produtos “para uso” na comanda profissional e baixa no estoque. A lista do usuário também contém requisitos mais avançados que não devem ser tratados como capacidades comprovadas do concorrente sem documentação específica.

Fontes oficiais consultadas em 12/10/2026:
- https://appbarber.com.br/funcionalidades/
- https://appbarber-appbeleza.zendesk.com/hc/pt-br/articles/11647210597133-Como-abrir-comandas-Aplicativo
- https://atualizacoes.appbarber.com.br/

### 1. Matriz de capacidades ausentes

| Perfil | Capacidade que precisa ser criada | Prioridade | Valor de negócio | Direção técnica / aceite |
|---|---|---|---|---|
| Gestor | Gestão específica de franquias, royalties e padrões entre empresas | Média | Expandir redes com governança | Organização de rede distinta de tenant; compartilhamento explícito e RBAC; nenhuma franquia acessa dados de outra por padrão |
| Gestor | Comissões escalonadas automaticamente por metas e dedução de insumos | Média | Remuneração previsível e campanhas de produtividade | Regras versionadas por vigência; cálculo com Decimal, snapshots e simulação antes de aplicar |
| Gestor | Vouchers/cartão presente com saldo e cupons do estabelecimento | Média | Antecipar receita e atrair novos clientes | Carteira/ledger por tenant, validade, resgates atômicos e reversão auditada. Coupon de billing é cupom da plataforma, não cupom de salão |
| Gestor | Estoque de uso interno e ficha de consumo por serviço | Alta | Controlar custo e evitar baixa indevida como venda | Tipo de item, unidade de medida, ficha técnica, movimentos de consumo/estorno; impedir comissão sobre consumo interno |
| Gestor | DRE gerencial estruturada e visão de competência | Média | Separar resultado de recebimento | Classificação gerencial, períodos e fontes reconciliáveis; não confundir soma de caixa com DRE |
| Gestor | Churn e coortes de clientes explicitamente definidos | Média | Medir retenção e campanhas | Janela de inatividade, segmentos/coortes e denominador documentado; distinguir churn de empresas do churn de clientes do salão |
| Recepção | Arrastar e soltar com reagendamento seguro | Média | Agilizar remanejamento na grade | Endpoint existente/seguro com conflito 409 e alternativa acessível por formulário; atualização otimista só após confirmação |
| Recepção | Sangria e suprimento próprios da sessão de caixa | Alta | Fechar caixa com rastreabilidade | CashMovement vinculado a CashSession, motivo, autor e aprovação; não lançar transferência de numerário como receita/despesa fictícia |
| Recepção | Impressão térmica de recibo/comanda homologada | Média | Adequar balcão e conferência | Primeiro impressão do navegador 58/80 mm; integração ESC/POS somente com impressoras e ponte homologadas |
| Profissional | Bloqueio/pausa pessoal com autonomia controlada | Alta | Evitar reservas em períodos indisponíveis | Endpoint limitado ao profissional autenticado, unidade correta e política sobre reservas já existentes |
| Profissional | Galeria de antes/depois e ficha técnica por atendimento | Média | Personalizar serviço e facilitar retorno | Anexo privado com consentimento, autorização, limites, retenção e notas por visita; não reutilizar prontuário médico como ficha de salão |
| Profissional | Consumo de insumo de bancada pela própria área | Alta | Registrar materiais no momento do uso | Fluxo de consumo interno, distinto de venda de produto, com vínculo a atendimento e estorno |
| Profissional e cliente | Web Push operacional | Média | Alertar sem depender de tela aberta | PushSubscription por dispositivo, VAPID protegido, opt-in, expiração e revogação; evitar dados sensíveis na notificação |
| Cliente | Reserva única com vários serviços e vários profissionais | Alta | Evitar múltiplas reservas e esforço repetido | AppointmentGroup/itens ou equivalente, cálculo de sequência, locks por recurso em ordem estável e idempotência de grupo |
| Cliente | Portal seguro com histórico e próximos agendamentos | Alta | Autonomia e menor demanda de suporte | Identidade verificada/OTP e isolamento; token de uma reserva não pode abrir histórico completo |
| Cliente | Provider SMS efetivamente operacional | Baixa | Canal alternativo quando necessário | Adapter com entrega/custos/fallback, opt-in e política de repetição. Enum SMS existente não é integração pronta |

### 2. Matriz de capacidades existentes e melhorias

| Perfil / recurso | Estado atual comprovado | O que melhorar | Evidência de código |
|---|---|---|---|
| Gestor — multiunidade | Unidades, escopo operacional, profissionais/serviços por unidade, limites comerciais | Padrões de rede, consolidação e homologação de configurações independentes | tenants/models.py; core/unit_scope.py; billing/entitlements.py |
| Gestor — políticas de agenda | Antecedência mínima, horizonte, intervalo, buffer, cancelamento e reagendamento | Regras por serviço, tolerância de atraso e penalidades transparentes | scheduling/models.py: TenantScheduleSettings; scheduling/availability.py |
| Gestor — permissões | RBAC/capabilities, middleware, escopos e perfil profissional restrito | Editor explicativo, presets por função e auditoria de mudança | accounts/permissions.py; accounts/route_middleware.py; core/portal.py |
| Gestor — financeiro | Lançamentos, categorias, receitas/despesas, caixa e resumo | Projeção reconciliável, competência, DRE e tratamento explícito de transferências | finance/models.py; finance/services.py; finance/portal.py |
| Gestor — comissões | Fixa/% por serviço e profissional, comissão de produto, snapshots e pagamento | Metas não equivalem a motor escalonado; unificar cálculo e projeção da área profissional | barber/models.py; barber/services.py; finance/services.py; core/professional_area.py |
| Gestor — cupons | Coupon da cobrança/contratação SaaS | Criar cupom B2C por tenant, sem reaproveitar regras do plano da plataforma | billing/models.py: Coupon |
| Gestor/cliente — sinal e antecipação | Pix parcial/total, percentual de sinal e pagar na unidade; infraestrutura de pagamentos | Homologar Pix real, expiração/estorno e jornada de cartão no agendamento público; escolhas atuais da UI são Pix | scheduling/public_api.py; scheduling/models.py; billing/payment_services.py |
| Gestor — BI | Ocupação, produtividade, ticket e retorno por profissional; indicadores de plataforma | Definições, séries comparáveis, coortes e exportação por unidade | core/operation_insights.py; core/master_retention.py |
| Gestor — estoque de revenda | Produtos, movimentos, reservas, custo e baixa por venda | Separar consumo interno, unidades de medida, compras e alertas úteis | finance/models.py; finance/services.py; scheduling/settlement.py |
| Recepção — agenda | Grade/listas, filtros, status e atualização automática por polling nas seções existentes | Calendário mais claro; feedback de conflito e sincronização granular; polling não é push | core/portal.py; static/js/live-agenda.js; templates/portal/list.html |
| Recepção — encaixe e fila | Fila de barbearia e lista de espera com fluxos próprios | Prioridade, tempo previsto, chamada visual e distinção entre chegada e espera por vaga | barber/models.py: BarberQueueEntry; engagement/models.py: WaitlistEntry |
| Recepção — status | Aguardando, em atendimento, concluído, cancelado e falta | Ações móveis mais diretas, transições consistentes e desfazer auditado quando permitido | scheduling/models.py; core/operation_insights.py |
| Recepção — comanda/PDV | Comandas com serviços/produtos, caixa abre/fecha, venda e comissões | Unificar balcão, sessão de caixa e integração com atendimento; homologar recepção conforme capacidades reais | barber/portal.py; barber/services.py; finance/portal.py |
| Recepção — pagamento dividido | BarberCommandPayment permite vários meios/valores na mesma comanda | Interface rápida de saldo e integração explícita da conciliação com sessão de caixa; PDV simples tem um meio por venda | barber/models.py; barber/services.py: register_payment; barber/portal.py: PaymentForm |
| Profissional — agenda e comissões | Agenda individual, compromissos, recebidos/pendentes e projeção | Alertas reais, filtros de período e projeção usando todas as regras de comissão | core/professional_area.py |
| Profissional — bloqueios | Gestão possui expedientes, intervalos, folgas e bloqueios | Dar autonomia limitada; profissional atual não pode acessar o CRUD geral /app/agenda | scheduling/models.py; accounts/route_middleware.py |
| Profissional — histórico/notas | Histórico gerencial e campo de preferências existem | Acesso autorizado da própria bancada, notas por visita e galeria; não classificar texto único como ficha técnica completa | core/operation_insights.py: customer_history; scheduling/models.py: Customer.preferences |
| Profissional — produtos | Pode registrar produto vendido ao finalizar atendimento e tratar produtos reservados | Consumíveis não cobrados, múltiplos itens e ligação clara com comanda | core/professional_area.py: SettlementForm; scheduling/settlement.py |
| Cliente — escolha | Serviço único, profissional preferido ou qualquer disponível, data inicial de hoje e resumo | Multisserviço e melhor tratamento de combinações sem disponibilidade | templates/tenant_public.html; static/js/public-booking.js; scheduling/public_api.py |
| Cliente — mensagens | Delivery de e-mail e WhatsApp, confirmação/lembretes/avaliação, retries | Entrega observável, preferências e fallback real. SMS/Push declarados no modelo não possuem provider nesse dispatcher | communications/tasks.py: send_notification; communications/tenant_whatsapp.py |
| Cliente — cancelar/reagendar | Gestão de reserva por token protegido e regras de antecedência | Uma tela clara e segura; GET de link não deve executar cancelamento automaticamente | scheduling/public_api.py; templates/scheduling/public_appointment.html |
| Cliente — fidelidade | Pontos, extrato, recompensa e transações idempotentes | Portal autenticado, saldo e resgate acessíveis ao cliente | engagement/models.py; engagement/services.py |
| Cliente — assinaturas | Pacotes recorrentes, CustomerMembership, cobrança e uso de créditos | Check-in/benefícios e saldo no portal do cliente, prevenção de duplo uso e exceções de renovação | engagement/models.py; engagement/services.py; engagement/portal.py |
| Cliente — satisfação | Avaliação de atendimento/profissional e avaliações públicas | Fechar ciclo com indicadores, moderação e retorno da empresa | scheduling/models.py: AppointmentRating; contenthub/models.py: PublicReview |

### 3. Roadmap técnico acionável

Estimativas orientativas de sequência, não cronograma contratado. Cada sprint precisa ser dimensionada com capacidade da equipe e escopo fechado.

| Fase / sprint | Entrega | Dependência | Aceite |
|---|---|---|---|
| Fase 1 — Essencial, sprint 1 | Homologar e consolidar redesign, regras de agenda e todos os perfis; reduzir CSS redundante gradualmente | CI/staging e dados de teste por segmento | Jornadas públicas/privadas, permissões, 320 px, temas e rollback aprovados |
| Fase 1 — sprint 2 | Portal cliente mínimo + autonomia de bloqueio profissional | Identidade/OTP, autorização e política de conflito | Cliente acessa apenas o próprio histórico; profissional bloqueia apenas a própria agenda |
| Fase 1 — sprint 3 | Sangria/suprimento e operação integrada de recepção | CashSession e ledger de movimentos | Fechamento reproduzível, saldo por meio, autoria e limites corretos |
| Fase 2 — Financeiro/retenção, sprint 4 | Estoque interno e ficha de consumo por serviço | Produtos/unidades de medida e atendimentos | Venda e consumo separados; conclusão debitada uma vez; cancelamento estorna uma vez |
| Fase 2 — sprint 5 | Multisserviço/multiprofissional e reserva de grupo | Contrato de idempotência, locks e política de pagamento | Uma operação atômica; conflito não cria grupo incompleto; duas tentativas simultâneas não duplicam vagas |
| Fase 2 — sprint 6 | Cupons B2C/cartão presente e comissões versionadas por meta | Ledger e fechamento reconciliável | Resgate/estorno auditados, saldo não negativo, cálculo independente reproduzível |
| Fase 2 — sprint 7 | Portal de fidelidade/assinaturas, ficha técnica visual e Web Push | Portal cliente e consentimentos | Saldo correto, check-in idempotente, acesso a anexos restrito e opt-out efetivo |
| Fase 3 — Escala/BI, sprint 8 | DRE gerencial, coortes, retorno e churn definido | Categorias, dados de pagamento e eventos consistentes | Indicador conciliável com suas fontes, período e denominador visíveis |
| Fase 3 — sprint 9 | Redes/franquias e consolidação entre unidades | RBAC organizacional explícito | Nenhum vazamento entre empresas; compartilhamento controlado e auditado |
| Fase 3 — sprint 10 | Observabilidade e otimização de calendário/notificações | Métricas de uso e gargalos medidos | Latência/erros rastreados, fallback, quotas e isolamento em testes de carga |

### Regras transversais de implementação

Toda nova escrita deve validar tenant e unidade no backend, usar transação e idempotência quando aplicável e registrar eventos financeiros reversíveis. Valores devem usar Decimal e snapshots. Recursos públicos não podem listar dados de clientes. A interface deve consumir decisões reais de disponibilidade e acesso. Novos anexos e push exigem autorização e consentimento adequados. Testar concorrência com PostgreSQL verdadeiro; não usar SQLite como prova de lock. Serviços de pagamento e comunicação precisam homologação do adapter ativo e tratamento de callbacks repetidos.

**Prioridade recomendada:** terminar homologação do redesign e consolidar operação de recepção, estoque interno e portal cliente antes de acrescentar gráficos ou anúncios de capacidades novas. Não recriar comanda, pagamento dividido, comissões ou fidelidade como se nada disso existisse: essas bases já estão no ApPlanner.
