# Documentos e cópias clínicas

Cada profissional cadastra sua própria assinatura em `/app/clinica/assinatura/`. O arquivo é validado como PNG/JPEG, normalizado e criptografado no banco. Modelos compartilhados ou pessoais ficam em `/app/clinica/documentos/modelos/`. A recepção pode preparar seus próprios rascunhos; somente o profissional identificado revisa e confirma a emissão. O PDF conserva a assinatura e a identificação profissional daquele momento. Imagem de assinatura não equivale a assinatura digital certificada. Documentos emitidos são imutáveis também no PostgreSQL; correções exigem nova emissão.

Pacientes de outros profissionais não aparecem nas listas clínicas, pesquisa ou sincronização offline. A recepção mantém a visão administrativa da empresa, sem leitura clínica. Cobranças podem ser atribuídas ao profissional; o relatório individual é somente leitura.

## Google Drive por empresa

No Master, abrir a empresa e **Backup clínico no Google Drive**. Configurar um cliente OAuth Google do tipo aplicação Web e registrar exatamente o endereço de retorno mostrado na tela. Habilitar a Drive API no projeto Google. Salvar Client ID e Client Secret sem ativar inicialmente. Conectar a conta Google da empresa, conferir pasta e confirmar autorização de exportação antes de ativar. Não são usados arquivos de credenciais no repositório nem tokens em HTML. O escopo Drive `drive.file` limita o aplicativo aos arquivos criados/autorizados para ele. Uma pasta criada pelo aplicativo é a opção recomendada; uma pasta arbitrária pode não estar acessível nesse escopo.

O Beat verifica a fila a cada hora e agenda a rotina diária no fuso e horário da clínica. `healthcare/tasks.py` registra as tarefas no worker. Conferir `seed_periodic_tasks` após publicar. É possível executar uma verificação manual no Master. Cada paciente possui um ID de arquivo estável: alterações atualizam o mesmo PDF, sem criar cópias adicionais. Em dias sem alteração, o checksum MD5 e a pasta do arquivo remoto são conferidos. SHA-256 é usado para integridade local. Falhas são registradas com código técnico e alertam o Master sem revelar conteúdo clínico. A configuração não permite ao Master baixar os PDFs dos pacientes pelo aplicativo.

O PDF inclui histórico, retificações, rascunhos identificados e documentos originais incorporados como anexos. O limite é 64 MB por paciente: excedê-lo falha com alerta, preservando a cópia remota anterior. Alterar a conta/pasta cria uma nova geração; cópias anteriores não são apagadas. Excluir um arquivo externamente permite recriá-lo; mover ou colocar na lixeira exige revisão da configuração. A empresa responde pela autorização e pelo acesso à conta de destino. A cópia clínica não substitui backup restaurável do PostgreSQL, volumes e chave de criptografia.

A funcionalidade só envia dados após configuração e autorização reais. Os testes simulados do protocolo não comprovam uma conexão real com o Google. Confirmar o primeiro envio, atualização e checksum no histórico da empresa antes de considerar o destino operacional.

## Publicação e reversão

Aplicar migrations aditivas e executar os testes PostgreSQL. Antes de produção, criar backup do PostgreSQL e verificar restauração em banco isolado. Em falha crítica, voltar à imagem/commit anterior, preservando as tabelas e dados novos; não reverter migrations clínicas destrutivamente. Validar web, worker, beat, banco, Redis, healthz e permissões. Não emitir documentos ou mensagens para pacientes reais durante homologação.
