# ApPlanner: documentação de usuários e integrações

Esta documentação descreve a interface Django da branch `django-replatform`. O portal personalizado em **Segurança → Documentação & API** (`/account/documentacao-api/`) exibe somente áreas permitidas ao usuário autenticado. O Master vê o catálogo completo. A documentação de API lista apenas operações efetivamente disponíveis em `/api/v1/`.

## Acesso, permissões e primeiro uso

1. Entre em `/account/login/`, configure a autenticação de dois fatores em **Segurança** e conclua a troca de senha temporária, quando exigida.
2. A empresa conclui o cadastro inicial de identificação, marca, unidade, profissionais, serviços, horários, cobrança e página pública em `/inicio/`.
3. O responsável atribui funções à equipe. Os módulos do plano e o segmento da empresa restringem as telas mesmo quando o papel possui permissão estrutural.
4. O profissional tem área própria em `/app/profissional/`: agendamentos vinculados à sua conta, conclusão do atendimento e ganhos. Não recebe acesso amplo aos clientes ou ao financeiro da empresa.
5. A recepção e a gestão usam `/app/` para a agenda, clientes, equipe, serviços e demais módulos autorizados. A empresa pode publicar a página `/p/<slug>/` e o link de cada profissional.

## Módulos da empresa

| Área | Operação principal | Requisito de acesso |
| --- | --- | --- |
| Agenda | Clientes, profissionais, serviços, unidades, expedientes, intervalos, folgas, agendamentos e configuração | `agenda.manage` |
| Financeiro | Lançamentos, produtos, PDV, caixa e comissões | `finance.manage` e módulo do plano |
| Barbearia | Fila, comandas, metas e remuneração | `barber.manage` e segmento correspondente |
| Arena | Quadras, reservas, jogos, mensalistas, turmas e torneios | `arena.manage` e segmento correspondente |
| Auto | Veículos, boxes, OS, inspeção, materiais e orçamentos | `auto.manage` e segmento correspondente |
| Relacionamento | Pacotes, mensalidades, fidelidade, indicações, inteligência de retorno e lista de espera | `engagement.manage` e módulo aplicável |
| Saúde | Prontuário com acesso auditado e consentimentos | `healthcare.manage` e segmento correspondente |
| Comunicação | Notificações, campanhas, conversas e WhatsApp da empresa | `communications.manage` e módulo aplicável |
| Suporte | Chamados e acompanhamento | `support.manage` |

### Jornada de agendamento

Configure unidade, serviços, profissionais, expedientes e folgas. Publique a página da empresa, compartilhe `/p/<slug>/` e permita agendamento público. O cliente escolhe uma disponibilidade; a agenda protege conflitos. A equipe acompanha confirmação, atendimento, ausência ou cancelamento. Na conclusão, o profissional registra pagamento e produtos, quando disponíveis, para alimentar venda, estoque e comissão. A avaliação 1 a 5 e a lista de espera são fluxos separados. Consulte o histórico e a conciliação antes de encerrar o caixa.

### Relacionamento, comunicação e cobranças

Pacotes e mensalidades controlam compra e uso de créditos. A fidelidade registra resgates e indicações. Campanhas exigem consentimento; descadastro deve continuar disponível. WhatsApp por QR requer o módulo liberado, o gateway interno e uma sessão persistida. O plano e as cobranças da empresa são consultados em **Meu plano e pagamento**; Pix e cartão dependem do Mercado Pago configurado e de confirmação pelo webhook. Revise notificações, impostos e dados pessoais conforme as políticas legais aplicáveis.

## Master

`/master/` concentra empresas, catálogo de planos e módulos, assinaturas e pagamentos da plataforma, equipe comercial, leads, propostas, campanhas, WhatsApp, chatbot, financeiro, suporte, chamados, backups, homologação, crons, integrações, identidade visual, página inicial, blog e modelos de e-mail/SMTP. A página **Documentação & API** lista individualmente os recursos cadastrados no Master e links para cada tela operacional. A assistência a uma empresa deve usar seleção explícita e auditoria; tokens não são emitidos por uma sessão de acesso assistido.

## Tokens pessoais

Abra `/account/documentacao-api/`, informe nome, selecione os escopos disponíveis e validade de 7, 30 ou 90 dias. Copie o segredo na tela de criação, pois só o hash SHA-256 fica no banco. Cada pessoa gerencia e revoga somente seus tokens. Após revogação, expiração, desativação da conta, mudança da versão de sessão ou perda de acesso, a chamada é recusada. Um token da empresa permanece vinculado à empresa da emissão.

Use HTTPS e o cabeçalho `Authorization: Bearer ap_...`. Guarde o token no servidor ou em gerenciador de segredos; nunca em páginas públicas, URL, código versionado ou captura de tela. O limite é 60 chamadas/minuto por token, 50 registros/página (`?pagina=2`). Respostas são JSON. A API de integração v1 é **somente consulta**; não exponha operações de escrita ou endpoints internos de pagamento/WhatsApp a estes tokens.

| Escopo | Recursos GET |
| --- | --- |
| `agenda.read` | `/api/v1/clientes/`, `profissionais/`, `servicos/`, `agendamentos/`, `unidades/` |
| `finance.read` | `/api/v1/produtos/`, `lancamentos/`, `vendas/` |
| `barber.read` | `/api/v1/fila/` |
| `arena.read` | `/api/v1/reservas/` |
| `auto.read` | `/api/v1/veiculos/` |
| `professional.read` | `/api/v1/meus-agendamentos/`, restrito ao profissional vinculado |
| `support.read` | `/api/v1/chamados/`, limitados à empresa |
| `commercial.read` | `/api/v1/leads/`, `/api/v1/propostas/`, limitados ao usuário comercial responsável |
| `master.read` | `/api/v1/visao-master/`, contagens da plataforma |

Para buscar um registro use `/api/v1/clientes/<id>/` e os demais recursos da tabela. Cada resposta inclui apenas os campos documentados na página do usuário. O Master pode selecionar os escopos da empresa, mas deve informar `?empresa=<id>` em cada consulta de dados do tenant; leads e propostas comerciais são globais e não usam esse parâmetro, que é ignorado para usuários de empresa. O Master possui visão de todos os módulos na documentação, mas a API não exporta segredos, prontuários, conteúdos de conversas nem toda a base de dados da plataforma.

Exemplo:

```bash
curl -H 'Authorization: Bearer ap_SEU_TOKEN' 'https://applanner.axionwebdigital.com.br/api/v1/agendamentos/?pagina=1'
```

Erros: `400` parâmetro inválido, `401` credencial inválida ou expirada, `403` escopo/permissão insuficiente, `404` registro ausente, `405` método não permitido, `429` limite excedido. A concessão do escopo não substitui a permissão atual do usuário, o segmento ou a separação entre empresas.

## Limites desta versão

Os fluxos de escrita, pagamentos, WhatsApp, prontuários e ações administrativas continuam no portal e nas integrações próprias; a API pessoal v1 não os executa. Amplie endpoints apenas com contratos e testes específicos de permissão, auditoria, idempotência e isolamento antes de anunciar API de escrita. A implantação requer migration `accounts.0006_personal_api_token` e deploy do `web`; a validade depende do banco e da cache compartilhada.
