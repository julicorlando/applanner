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

## Chatbot comercial Master e leads

O modelo comercial do construtor (`/master/whatsapp/fluxo/`) apresenta os planos ativos e públicos do banco, incluindo preço mensal regular, dias de teste e módulos. Valores de promoções, extras e outros ciclos são confirmados no checkout ou pela equipe. A base de dúvidas cobre agenda, unidades, equipe, arena, pagamentos, WhatsApp, financeiro, localização e API. Perguntas fora da base são encaminhadas para confirmação humana; o assistente se identifica como virtual.

O bloco **Cadastro automático de lead** coleta nome, empresa, segmento, e-mail, número de unidades e profissionais, plano de interesse e necessidade. O WhatsApp é aproveitado quando disponível; contatos com JID LID informam telefone. A partir do nome e telefone válidos, um lead é salvo e atualizado a cada resposta, com vínculo à conversa. Dúvidas durante a coleta não apagam o campo pendente. A transferência humana recebe o histórico e o resumo no Comercial. O cliente pode solicitar um atendente diretamente, sem cadastro obrigatório. Não é registrado consentimento automático de marketing.

A API v1 continua somente leitura, com Bearer pessoal, limite de 60 requisições/minuto e listas paginadas em 50 registros:

| GET | Escopo | Resultado |
| --- | --- | --- |
| `/api/v1/leads/` e `/api/v1/leads/ID/` | `commercial.read` | Nome, telefone, e-mail, segmento, origem, notas, status, consentimento, bloqueio de contato, próximo contato e datas. Comercial vê somente leads atribuídos; Master vê todos. |
| `/api/v1/planos-publicos/` | `commercial.read` | Planos ativos/públicos, preços mensais regulares, descrição, teste e módulos; planos personalizados são sinalizados com `is_custom`. |
| `/api/v1/chatbot-master/` | `master.read` e usuário Master | Ativação, data de alteração, quantidade de blocos, leads vinculados e conversas com transferência humana. Não retorna chaves, variáveis nem conteúdo de mensagens. |

O simulador não cria leads e não envia mensagens. O fluxo real requer gateway Master conectado, automação habilitada e Celery worker/beat disponíveis. A migração instala o modelo na configuração existente, preservando ativação e credenciais; fluxos novos recebem o modelo ao abrir o construtor. O botão **Modelo comercial pronto** permite restaurar o modelo no rascunho antes de salvar.

### Aplicar OpenAI

1. Crie uma chave em `https://platform.openai.com/api-keys` e configure o faturamento/créditos da API, separados do ChatGPT Plus.
2. Em **Configurar**, informe `gpt-4.1-mini` (ou outro modelo compatível com Chat Completions disponível no seu projeto), cole a chave e marque **Habilitar chamadas de IA**. Salve. A chave é criptografada e não volta a aparecer.
3. Adicione um bloco **Agente IA** depois da entrada da pergunta. Defina a variável de saída (`resposta_ia`) e marque envio da resposta.
4. Nas instruções, use: `Você é o assistente virtual do ApPlanner. Responda em português com acolhimento e objetividade. Use somente as informações fornecidas. Planos atuais: {{public_plans}}. Não invente preços, recursos, confirmação de pagamentos ou prazos. Se não souber, diga que a equipe vai confirmar. Não solicite senhas nem dados de cartão.`
5. Conecte **Sucesso** ao próximo menu/cadastro e **Falha** ao atendimento humano. O simulador usa resposta fictícia; a homologação real usa a API e pode gerar cobrança. O fluxo comercial nativo funciona sem chave de IA.

### Assistente IA com triagem (Master)

O arquivo `communications/master-assistant-flow.json` pode ser importado no construtor. A recepção identifica novos interessados ou clientes atuais, pergunta segmento e necessidade, apresenta os planos públicos cadastrados e oferece dúvidas, proposta ou atendimento humano. A coleta comercial só começa após a triagem e a escolha de orientação/proposta; os dados recebidos são salvos progressivamente em um único lead. Pedidos explícitos de atendimento humano interrompem a automação.

Nos blocos de IA, marque **Restringir à base oficial do ApPlanner**. Nesse modo, o modelo classifica a pergunta escolhendo até dois fatos aprovados; o servidor compõe a resposta exclusivamente com esses fatos e os planos ativos. Respostas livres geradas pelo modelo não são exibidas. Assuntos fora da base recebem orientação para procurar a equipe; erro de IA segue a saída de erro/atendimento humano. Apenas a mensagem atual e a base pública são enviados ao provedor, sem o cadastro do lead ou o histórico completo. O simulador não chama a API de IA. A chave permanece cifrada, e o modelo e a habilitação continuam configuráveis.

### Exclusão de leads (Master)

Na ficha do lead, **Gestão Master → Excluir lead** abre uma confirmação antes da remoção definitiva do cadastro, notas e histórico comercial. A ação exige Master, sessão autenticada, POST e CSRF; o comercial não possui essa permissão. Empresas, pagamentos, propostas e mensagens de WhatsApp são preservados. Conversas vinculadas passam para atendimento humano, com contexto da coleta limpo e envios pendentes cancelados, evitando a recriação automática pelo cadastro em andamento. A exclusão fica registrada na auditoria, sem copiar dados pessoais do lead. A API de leads continua de leitura, sem endpoint de exclusão.

## Chatbot visual por empresa

Na conexão WhatsApp, abra **Configurar chatbot**, use o modelo de atendimento,
ajuste mensagens e caminhos, simule e salve. A aba Configurar permite ativar o
bot e usar a IA central do Master sem copiar ou revelar a chave. É necessário
ter WhatsApp conectado e acesso ao módulo. A equipe vê a necessidade e a unidade
na conversa, pode assumir o atendimento e responder pelo número da própria empresa.

- `GET/POST /app/comunicacao/chatbot/`: gestão autenticada, formulário com CSRF;
  `graph_json` é o grafo v2, `enabled` ativa o bot e `ai_enabled` usa a IA central.
- `POST /app/comunicacao/chatbot/simular/`: JSON (`graph`, `state`, `context`,
  `waiting`, `incoming`, `resume`) com CSRF; retorna estado, contexto, mensagens,
  espera, caminho e encaminhamento. Nenhum envio real ou consumo de IA.
- A empresa é determinada pelo usuário; o Master usa a empresa selecionada na
  sessão. Não se aceita trocar empresa com `tenant_id` enviado no formulário.
- Blocos API externos e legados são rejeitados. A IA consulta exclusivamente
  informações públicas da empresa e não confirma reservas nem pagamentos.

Veja `WHATSAPP_RETURN.md` para publicação, fila, recuperação e conexão do gateway.
