# WhatsApp: retorno, cobrança e atendimento Master

## Inteligência de retorno
Em Operação → Inteligência de retorno, a gestão pode enviar o convite manualmente ou abrir **Configurar convites automáticos pelo WhatsApp**. O automático começa desligado; padrão: até 30 convites em 24 horas e sete dias entre convites automáticos ao mesmo cliente. A rotina existente de inteligência verifica os retornos a cada 12 horas. Exige módulos de inteligência e WhatsApp quando houver assinatura e respeita bloqueio financeiro, empresa arquivada/excluída, autorização de relacionamento do cliente e ausência de agendamento futuro. O envio usa o WhatsApp conectado da própria empresa. O link inclui a unidade do último atendimento concluído.

O profissional pode convidar somente clientes com pelo menos um atendimento concluído com ele. Até 20 convites por profissional em 24 horas e um convite ao mesmo cliente por empresa em 24 horas. O texto é fixo e inclui o link público do profissional. Limite protegido por bloqueio de registro no PostgreSQL. Falha de envio libera a reserva do limite. Atendimento humano existente não é reiniciado pelo convite.

## Avisos de assinatura
Os avisos já existentes mantêm popup, notificação interna e e-mail. Acrescentado WhatsApp para o telefone cadastrado da empresa, enviado exclusivamente pelo número pareado do Master e registrado na sua caixa de entrada. Renovação: três dias, um dia, vencimento e um aviso após vencimento. Teste: dois dias, vencimento e um após vencimento. Um aviso por assinatura/ciclo/etapa; antes do envio, a fila revalida o prazo para descartar avisos antigos depois de renovação.

Requer Celery worker/beat em operação e número do Master conectado. A fila expõe falhas e pode ser reenviada pelo centro de notificações após corrigir a conexão. Um envio marcado como enviado ainda depende do recibo do WhatsApp para comprovar entrega/leitura.

## Master
WhatsApp Master: lista, filtros reais (todas/não lidas/humanas/automáticas), conversa e dados/ações do contato em três colunas, adaptadas ao celular e ao tema atual. Mensagens recebidas tornam-se lidas no painel quando abertas; isto não simula recibo de leitura do destinatário para mensagens enviadas.

Fluxo do Master: canvas com blocos de mensagens/opções, transferência humana e finalização, conexões por próxima etapa, arraste, zoom e posições persistidas. Salvar aplica o fluxo validado no servidor. A etapa inicial chama-se `inicio`. Palavras configuradas disparam a resposta e a transição. Uma etapa tem uma transição e pode reconhecer várias palavras; para fluxos complexos, use etapas sucessivas. A transferência pausa a automação até Retomar fluxo. Finalizar encerra o ciclo; novo contato começa pela saudação. Editor em texto permanece disponível para compatibilidade. Não executa JavaScript fornecido pelo operador nem replica blocos de IA/API de plataformas externas.

## Cobrança mínima
Cobranças e reajustes enviados ao provedor devem ter pelo menos R$ 0,50, valor finito e duas casas decimais. A validação ocorre antes de criar a transação. Valores menores não são aumentados automaticamente nem liberam o plano. A gestão deve revisar contrato/promoção/desconto ou usar o fluxo existente de isenção.

## Publicação
Executar `python manage.py migrate --noinput` no redeploy, como nas outras atualizações: migration `engagement.0009_returnmessagingsettings`. Sem alterações nas variáveis de ambiente existentes. Conectar o WhatsApp da empresa e o Master; ativar os convites automáticos somente após revisar consentimentos e limites.

## Construtor avançado do chatbot Master

O editor visual em `/master/whatsapp/fluxo/` oferece blocos arrastáveis, conexões por saída, zoom, desfazer/refazer, importação/exportação de JSON e um modelo comercial. Menus possuem até dez opções com caminhos independentes. Os blocos disponíveis são mensagem, menu, entrada validada, condição, variável, API, IA, espera, transferência humana e finalização.

Use `{{nome}}` e `{{resposta.campo}}` para interpolar variáveis. Entradas podem validar texto, e-mail, telefone ou número. O simulador executa o mesmo motor, com respostas fictícias de API/IA, sem enviar WhatsApp ou realizar chamadas externas. Exportações não incluem as credenciais configuradas.

APIs devem ser cadastradas no painel Configurar, com HTTPS público, GET/POST e token Bearer opcional. DNS privado, redirecionamentos e respostas acima de 64 KB são recusados. A IA usa chave e modelo OpenAI definidos pelo operador; fica desativada até a configuração. Não há execução de JavaScript arbitrário. As variáveis da conversa e as credenciais ficam criptografadas no banco.

As mensagens são persistidas em uma fila com chave idempotente, entrega ordenada e até cinco tentativas. Falhas podem ser retomadas na conversa. O gateway preserva recibos no volume de sessão. Esperas são retomadas pelo Celery Beat a cada minuto, portanto o tempo é aproximado. Alterar o fluxo durante uma espera exige retomada humana; mensagens pendentes de um fluxo desativado são canceladas ao tentar entregá-las.

Os fluxos antigos continuam no motor legado até serem editados e salvos no novo editor. Na publicação, aplique `python manage.py migrate` e atualize os serviços web, worker, beat e gateway Master. Homologue a conexão WhatsApp e as integrações com suas credenciais antes de ativar atendimento real.

## Modelo comercial com captação automática

Veja `DOCUMENTACAO_USUARIOS_API.md`, seção Chatbot comercial Master e leads. Os novos blocos `knowledge` e `commercial` oferecem orientações nativas e cadastro progressivo, sem custos de IA. A migração 0013 instala o modelo na configuração existente; o sinalizador de ativação e as credenciais são preservados. Os leads são vinculados em `MasterWhatsAppConversation.sales_lead`, sem consentimento de marketing automático. Perguntas e respostas inválidas não avançam o cadastro indevidamente. Os dados do lead ficam disponíveis para a equipe e na API com escopo comercial.
