# Home, Push e importação de clientes — 20/10/2026

## Imagens reais da home
A agenda e a jornada mobile são capturas do código atual, com dados declaradamente fictícios em banco SQLite descartável. Os cinco WebP possuem versões responsivas; as imagens antigas são preservadas. O script scripts/capture_home_previews.py sempre sobrescreve DATABASE_URL para um arquivo temporário, usa fila em memória e bloqueia no navegador qualquer host diferente de localhost. Não fotografa produção nem acessa dados de clientes. O workflow de captura tem somente contents:read e verifica a home em 320/390/768/1440, temas claro/escuro, imagens e erros JavaScript. Sem nova dependência de navegador no runtime.

## Notificações do dispositivo
Reutiliza PushSubscription, PushDelivery, VAPID, o service worker e o Celery existentes. A agenda continua com atualização automática. Agora a gestão/recepção autorizada e o profissional designado recebem novos agendamentos e alterações; Arena notifica a gestão sobre reservas. O clique abre o dia do compromisso. O worker revalida usuário ativo e empresa antes de entregar. Os avisos são genéricos na tela bloqueada, sem nome/telefone do cliente ou valor financeiro.

Master com dispositivo autorizado recebe cadastros de empresas/clientes/usuários, cobranças e pagamentos da plataforma (exclui sandbox e pagamentos de clientes da empresa), vencimentos, fim de teste, cancelamento/suspensão de assinatura, planos/módulos e alterações administrativas auditadas. Atualizações que não geram signals e prazos são reconciliados a cada minuto, com deduplicação persistente por dispositivo e evento. Não significa todo UPDATE SQL arbitrário ou mudanças externas ao ApPlanner.

Configuração operacional: Master → Push e SMS → ativar Web Push, informar e-mail de contato VAPID e salvar. As chaves existentes não são substituídas. Depois, cada usuário abre Notificações neste dispositivo (profissional: Notificações) e autoriza cada aparelho. No iPhone/iPad, abrir pela Tela de Início em versão compatível. Navegador/SO, conexão e políticas de bateria determinam o recebimento. Instalar o PWA sozinho não concede permissão. SMS e WhatsApp existentes permanecem independentes. Não foi feito envio real a dispositivos nesta sessão.

## Importação assistida de clientes
Master → Importar base de clientes. Somente superusuário ativo, fora de impersonação. CSV UTF-8/Windows-1252, delimitadores usuais ou XLSX; máximo 5 MB, 5.000 clientes e 80 colunas. XLSX tem limite descompactado e rejeita fórmulas; não executa macros nem SQL. Modelos de cabeçalho e mapeamento explícito de nome, telefone brasileiro com DDD, e-mail, nascimento e observações.

O envio cria apenas uma prévia criptografada com prazo de 24h. O Master confirma empresa e colunas; confirmação assinada expira em 1h. Dados são revalidados sob lock da empresa. Preserva clientes existentes, históricos e consentimentos; novos clientes têm consentimento de marketing desativado. Não mescla identidades ambíguas. Duplicados no mesmo arquivo são ignorados. Lotes repetidos são idempotentes. Linhas inválidas bloqueiam o lote, salvo autorização explícita para importar as válidas e conferir o relatório de rejeições. Não é importador universal de backups proprietários, históricos de agenda, senhas, prontuários ou financeiro; esses dados exigem migração específica.

A origem é apagada do staging após aplicar; o relatório por linha não contém a base original. O usuário deve guardar sua exportação de origem, especialmente se optar por importar apenas linhas válidas. Não envia campanhas ou mensagens aos clientes importados. Há um único aviso agregado ao Master em importação, evitando um push por linha.

## Deploy e reversão
Uma migration aditiva (scheduling.0024) cria só CustomerImportBatch; não modifica colunas ou registros existentes de clientes/planos/pagamentos. Dependências novas: openpyxl e defusedxml para XLSX. Execute pipeline, backup e redeploy normal preservando volumes, variáveis e a chave de criptografia existente. Não recriar o projeto ou o banco.
Em reversão, retornar o código mantendo a tabela nova e todos os clientes importados; não desfazer migration nem excluir cadastros. VAPID e a chave de criptografia devem ser preservadas. Validar após deploy healthz, página inicial, inscrição de dispositivos e um agendamento controlado. Este PR não comprova deploy nem entrega em dispositivo físico.
