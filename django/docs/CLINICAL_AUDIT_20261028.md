# Auditoria clínica — Odontologia e Fisioterapia

Registro histórico da auditoria inicial. A lista abaixo foi parcialmente superada pela implementação e pelas evidências em [CLINICAL_RELEASE_20261029.md](CLINICAL_RELEASE_20261029.md). Não interpretar as pendências históricas como o estado atual.

## Repositório auditado

- PR #40: integrado em django-replatform, commit 7b9f260713a8295a40e9fcb2c3ca011400abaecf. Acrescenta o catálogo de Fisioterapia; não representa homologação clínica.
- PR #41: rascunho, head fd08d9044a3a5beb7fc308659502f3552e03df79. Django CI passou; Security and repository policy falhou por dois imports não utilizados em healthcare/test_dentistry.py, corrigidos nesta alteração.
- main não alterada. A continuação parte da base odontológica do PR #41 e incorpora o catálogo do PR #40.

## Alterações nesta entrega

- Autorização clínica exige conta ativa, papel clínico e profissional ativo vinculado à mesma clínica. Ser Master não concede acesso clínico.
- Escrita e leitura restritas ao profissional responsável; não há autorização automática para colegas nem impersonação de outro profissional.
- Validação conjunta do paciente, tenant, profissional e agendamento.
- Conteúdo clínico permanece cifrado pelo mecanismo Fernet existente; leituras e criações são auditadas.
- Imutabilidade por save/update/bulk_update no ORM público dos registros; retificação cria outro registro com referência ao original e motivo cifrado. A interface de retificação e proteção por trigger do banco ainda estão pendentes.
- Importação legada preserva registros existentes, recusa divergências e mantém a data histórica na criação.
- Arcadas SVG superior/inferior, dentes esquemáticos e raízes, dentições permanente/decídua, FDI, seleção múltipla, faces, cores e legenda. Histórico apresenta os odontogramas registrados. Impressão permite salvar PDF pelo navegador; não é um PDF assinado.
- Limite odontológico verificado também no save ORM, com bloqueio por tenant; bulk_create/update/bulk_update não podem ativar vagas odontológicas. Clínica com módulo Odontologia ativo não contorna a regra alterando apenas a categoria. Foi acrescentada a migration scheduling.0026 com trigger PostgreSQL para bloquear bypass por SQL/_base_manager; testes de bypass e concorrência exigem execução no CI PostgreSQL.
- Recepcionista é uma conta administrativa e não consome um objeto Professional. Não foi criada uma segunda modalidade de cadastro de recepção.
- Vaga adicional: repetição permitida, preço cotado preservado e ativação recusada sem pagamento associado, pago e com valor correspondente, ou isenção expressa atribuída ao Master, com trilha administrativa de ativação e motivo integral preservado. Fluxo de cobrança e webhook dedicado à solicitação ainda NÃO conectado à interface. A guarda de ativação não equivale a um checkout completo.
- Fisioterapia: CREFITO no registro, diagnósticos médico/fisioterapêutico, palpação, avaliação neurológica, prognóstico, exercícios, parâmetros, intercorrências, orientações e alta.
- Mapa corporal existente preservado e ampliado com dor 0–10, condição e notas por região, validação no servidor e correção de lateralidade anterior/posterior. Mapa também disponível na avaliação inicial.
- Links clínicos no menu para profissionais vinculados e módulos habilitados.

## Validação local

- manage.py check: passou.
- makemigrations --check --dry-run: sem alterações pendentes, incluindo healthcare.0004 e .0005.
- collectstatic: passou.
- Ruff F401/F821/F822/F823: passou.
- Política de artefatos: passou.
- JavaScript: 29 testes passaram, incluindo cinco testes DOM dos mapas com jsdom.
- Suíte clínica/comercial/catálogos atual: 50 testes executados, 47 passaram e 3 testes específicos de PostgreSQL ignorados localmente.
- Regressão completa em SQLite: 919 testes, 4 falhas, 3 erros, 13 ignorados. Três falhas de concorrência dependem de PostgreSQL; três erros dependem de Redis. Uma expectativa antiga de acesso Master irrestrito foi corrigida para exigir 403. Não contabilizar a regressão completa como aprovada; exigir CI em PostgreSQL/Redis.
- CI do commit bd7e7728249c87621c359476ba409eda0cd9096a: Django e segurança aprovados; 919 testes PostgreSQL/Redis passaram (3 ignorados), 29 testes JavaScript passaram e 3 testes de restauração em PostgreSQL descartável passaram. As alterações posteriores de proteção de vagas e auditoria financeira exigem o CI do HEAD do PR.
- As migrations healthcare.0004/.0005 foram exercitadas em bancos descartáveis local e do CI. Nenhuma migration aplicada no Coolify nesta execução. Healthcare.0001–0005 estão registradas no banco descartável dos testes; scheduling.0026 é no-op em SQLite.

## Coolify observado, sem alterações

- Projeto ApPlannerV2; único ambiente visível: production.
- Aplicação 8omu5fasbdtdycjfs8bmzvlw; domínio https://applanner.com.br; origem django-replatform, diretório /django, Compose /docker-compose.yml.
- Estado apresentado: Running (no healthcheck). Não equivale a confirmação individual de web/worker/beat/db/redis.
- Backups de storage na tela: 0 agendamentos, 0 execuções. Isso não exclui backups externos; recuperação não demonstrada.
- Nenhum redeploy, alteração de variáveis/volumes, migration ou mudança de produção realizado.
- Consulta pública de produção /healthz/: HTTP 200, database=true e cache=true. Isso não valida o código desta branch nem os processos Celery.
- Homologação isolada ainda não identificada/criada; nenhuma URL de homologação validada.

## Pendências impeditivas para aceite integral

1. Criar/validar ambiente de homologação com banco, Redis, volumes e segredos isolados; backup e ensaio de restauração; healthcheck e rollback comprovados.
2. Concluir cobrança do adicional: quantidade por solicitação, proporcionalidade, checkout, webhook, reconciliação automática, estorno, inadimplência e interface de isenção. Não usar pagamento real de produção para testes.
3. Identificação profissional CRO/UF e CREFITO em cadastro validado e snapshot por atendimento; vínculo clínico compartilhado com concessão/revogação explícita.
4. Periodontograma, orçamento/aprovação e planejamento estruturado por dente; materiais, anestesia e demais campos odontológicos separados (a base ainda usa quatro textos clínicos amplos).
5. Anexos clínicos privados, radiografias, consentimentos/assinaturas e exportações auditadas; retenção e restauração validadas.
6. UI de retificação, trilha administrativa completa, proteção de integridade dos prontuários no PostgreSQL e validação dos testes concorrentes.
7. Comparação visual retrospectiva do mapa corporal, indicadores por paciente, relatórios e integração validada de pacotes/sessões/financeiro.
8. Testes E2E no navegador real em homologação, responsividade, agendamento, recepção, prontuário, extras e pagamento sandbox.
9. Não declarar certificação, assinatura ICP-Brasil ou conformidade LGPD/CFO/COFFITO por esta entrega.

## Referências profissionais consultadas

- Manual do Prontuário do Paciente em Odontologia, CFO: https://prescricao.cfo.org.br/
- Resolução CFO 91/2009: https://transparencia.cfo.org.br/ato-normativo/?id=1360
- Resolução CFO 278/2025 (teleodontologia, quando aplicável): https://transparencia.cfo.org.br/ato-normativo/?id=4626
- Resolução COFFITO 414/2012, prontuários: https://www.coffito.gov.br/nsite/?page_id=34301&paged=13

Revisão das fontes não substitui validação jurídica, regulatória ou certificação técnica. Assinatura digital, integridade, cópia ao paciente e retenção exigem análise específica antes de produção.
