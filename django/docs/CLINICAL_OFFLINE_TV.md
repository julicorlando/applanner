# Operação clínica offline e sala de espera

## Acesso e navegação

Fisioterapia e Odontologia mantêm os oito itens do menu existente. O botão no cabeçalho permite ocultar/mostrar o menu no computador e abrir uma gaveta no celular. A preferência de recolhimento no computador é persistida sem dados pessoais. O atalho de ferramentas e Configurações oferecem operação offline; o atalho de TV aparece quando o módulo está liberado.

## Operação offline

Abra `/offline/clinica/` conectado, com login válido. A ativação é explícita, por dispositivo, e exige senha local com pelo menos 12 caracteres. Somente a página pública vazia e seus arquivos entram no cache do Service Worker. A cópia autorizada e a fila ficam em IndexedDB como um único envelope AES-256-GCM autenticado, com chave não extraível derivada por PBKDF2-SHA256 (310.000 iterações, salt aleatório). A chave e a senha não são persistidas. Uma trava Web Locks permite apenas uma aba com o cofre aberto. Bloqueio após cinco minutos de inatividade ou um minuto em segundo plano remove os dados visíveis e a chave da memória.

A cópia tem validade de sete dias, até 1.000 pacientes, 500 atendimentos de ontem aos próximos sete dias e 100 registros clínicos autorizados recentes. As limitações e truncamentos são exibidos. Autorizações revogadas no servidor não podem ser conhecidas enquanto o dispositivo está sem rede; cada acesso ao servidor e cada operação revalidam o vínculo. A clínica deve autorizar o dispositivo; criptografia do cofre não substitui proteção do equipamento, controle de acesso ou prevenção de XSS.

Operações disponíveis:

- Consultar agenda, pacientes e histórico clínico autorizado já preparado.
- Cadastrar paciente avulso com nome completo; telefone/e-mail/nascimento opcionais e validados. Contatos existentes exigem revisão; não há fusão automática de pacientes.
- Agendar paciente existente ou recém-cadastrado; a disponibilidade real é revalidada ao sincronizar. A reserva local não bloqueia a agenda de outros dispositivos.
- Registrar chegada com controle de versão do atendimento.
- Registrar evolução com data clínica, confirmação de autoria e vinculação opcional ao atendimento. A sincronização cria novo registro criptografado com identificação profissional; não sobrescreve versões antigas. Avaliações estruturadas e suas assinaturas finais continuam no editor online.
- Registrar recebimento integral em dinheiro, reutilizando o encerramento/financeiro existente e as proteções contra duplicidade. Pix, cartão, estornos e cobranças online exigem conexão e confirmação do provedor; não há aprovação financeira offline.

A sincronização exige sessão online e CSRF. UUID, escopo de conta/clínica e hash do conteúdo tornam repetição idempotente. Recibos contêm somente IDs, sem conteúdo clínico. Conflitos ficam na fila criptografada, não são sobrescritos; o usuário pode revisar ou descartar conscientemente. Falha de rede após confirmação pode ser repetida com o mesmo UUID. Uma conta diferente não envia a fila de outra conta.

Não encerre o navegador sem confirmar que a fila foi salva. Navegadores podem remover armazenamento local; solicitação de armazenamento persistente não é garantia. O backup exportado é criptografado e depende da mesma senha. Perder a senha impede recuperar lançamentos locais não sincronizados; os dados confirmados permanecem no servidor. A aplicação não salva anexos ou arquivos clínicos completos offline nesta versão.

## Chamar na TV

Catálogo `waiting-room-tv`, desativado por padrão em todos os estabelecimentos até liberação por plano ou Master. Reutiliza os módulos e faturamento existentes; não cria assinatura paralela. A migration cadastra apenas o item comercial; o Master define preço e condições de venda.

Responsável/gestor configura título, ativação, voz, nomes completos (abreviados por padrão), expiração de 1 a 120 minutos e até 10 mídias. Imagens PNG/JPEG são reprocessadas sem metadados; vídeos MP4 têm extensão, tamanho e estrutura do contêiner validados (até 20 MB; codec deve ser compatível com a TV). Arquivos são criptografados antes de salvar e servidos por rota autorizada pelo token, com MIME fixo e `nosniff`; arquivos HTML/SVG não são aceitos.

Recepção pode chamar pacientes, mas não configurar o painel nem ler prontuários. Profissional só chama atendimentos próprios; o Master não recebe acesso clínico. Cada chamada registra usuário/atendimento/sala, expira na visualização e usa chave idempotente. Não são enviados diagnóstico, telefone, e-mail ou prontuário à TV.

O link curto `/tv/<token>/` redireciona ao endereço personalizado `/tv/<clinica>/<token>/`. Esse endereço é uma credencial de exibição: mantenha-o reservado. Revogação do link ou do módulo invalida tela, feed e mídia antigos. O rodapé mostra apenas o link público de agendamento da clínica, quando disponível; não divulga o token de acesso à TV. O painel atualiza a cada cinco segundos, limpa nomes após um minuto sem atualização e alterna imagens/vídeos. Áudio/tela cheia exigem clique em “Iniciar TV e habilitar áudio”, conforme o navegador. A lista de chamadas mostra a atual e até cinco anteriores não expiradas.

## Implantação e rollback

Migrations aditivas `0015_offline_waiting_room` e `0016_waiting_room_catalog`. Nenhum dado clínico anterior é modificado. Faça backup restaurável do PostgreSQL antes de publicar. Colete estáticos e valide HTTPS, migrações, web/worker/beat/Redis e `/healthz/`. O Service Worker precisa atualizar antes da primeira preparação offline.

Rollback: voltar ao commit anterior sem reverter tabelas nem apagar registros; desativar o módulo de TV pelo Master. Cofres de dispositivos já preparados permanecem criptografados e não devem ser apagados automaticamente com lançamentos pendentes. Validar compatibilidade antes de reativar a sincronização. Não foi realizada certificação jurídica/LGPD; a política de dispositivos, nomes na sala de espera e retenção deve ser validada pela clínica.
