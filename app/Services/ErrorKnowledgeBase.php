<?php
namespace App\Services;

final class ErrorKnowledgeBase
{
    public static function all(): array
    {
        return [
            self::e('HTTP 400','Aplicação','Requisição inválida','Dados enviados em formato inesperado, URL ou payload malformado.','Conferir os campos enviados, limpar cache do navegador e repetir. Se ocorrer em integração, validar o JSON.'),
            self::e('HTTP 401','Acesso','Não autenticado','Sessão encerrada, credencial ausente ou token de integração inválido/expirado.','Entrar novamente. Em APIs, renovar e salvar a credencial correta.'),
            self::e('HTTP 403','Acesso','Acesso negado','Perfil sem permissão, empresa inativa ou módulo não incluído no plano.','Conferir perfil, vínculo com a empresa, situação da assinatura e módulos liberados.'),
            self::e('HTTP 404','Aplicação','Página ou registro não encontrado','Rota inexistente, .htaccess não aplicado, registro excluído ou URL incorreta.','Confirmar a URL e o registro. Se várias rotas falharem, conferir mod_rewrite e .htaccess.'),
            self::e('HTTP 419','Segurança','Sessão expirada/CSRF','Formulário ficou aberto por muito tempo, sessão mudou ou token CSRF não foi enviado.','Atualizar a página, entrar novamente e reenviar o formulário uma única vez.'),
            self::e('HTTP 422','Validação','Dados não aceitos','Campo obrigatório ausente, formato inválido ou regra de negócio não atendida.','Ler a mensagem exibida, corrigir os campos e verificar situação do plano/assinatura.'),
            self::e('HTTP 429','Segurança','Muitas tentativas','Limite de login, cadastro ou chamadas à API excedido.','Aguardar o período indicado, evitar cliques repetidos e verificar automações em loop.'),
            self::e('HTTP 500','Servidor','Erro interno','Exceção PHP, coluna/tabela ausente, tipo incompatível, permissão de pasta ou falha inesperada.','Pesquisar o ERR-ID nesta tela; conferir app.log e error_log; validar migrations e sintaxe PHP.'),
            self::e('HTTP 502','Integração','Falha no provedor externo','Mercado Pago ou outro serviço recusou/indisponibilizou a operação.','Ler o código após HTTP 502, conferir credenciais e consultar a seção da integração nesta base.'),
            self::e('HTTP 503','Disponibilidade','Serviço não configurado','Gateway desativado, integração ainda não homologada ou recurso temporariamente indisponível.','Ativar e testar a integração no Master; conferir Saúde do sistema.'),

            self::e('MP 400','Mercado Pago','Requisição recusada','Payload, valor, e-mail, frequência ou outro campo fora do padrão da API.','Ler a mensagem técnica. Valores devem ser positivos e ter no máximo duas casas decimais.'),
            self::e('MP 401','Mercado Pago','Access Token inválido','Token incorreto, revogado, incompleto ou pertencente a outra aplicação.','Gerar/copiar novamente o Access Token e executar o teste no Master.'),
            self::e('MP 402 processing_error','Mercado Pago','Transação Pix não processada','Conta recebedora sem chave Pix ativa, Pix indisponível na conta ou falha de processamento do provedor.','Cadastrar uma chave Pix na mesma conta do Access Token, aguardar a ativação e gerar uma nova cobrança.'),
            self::e('MP 403','Mercado Pago','Operação não autorizada','Aplicação/conta sem permissão, ambiente divergente ou restrição cadastral.','Confirmar titularidade, ambiente e situação da conta; se persistir, acionar o Mercado Pago com o ID PAY/ORD.'),
            self::e('MP 404','Mercado Pago','Pagamento/ordem não encontrado','Referência incorreta ou credencial de outra conta/ambiente.','Conferir provider_reference, ambiente e Access Token usado na criação.'),
            self::e('MP 409','Mercado Pago','Conflito ou idempotência','A mesma chave foi reutilizada com dados diferentes ou a operação já está em processamento.','Não repetir o envio; consultar a cobrança existente e usar nova tentativa somente após confirmar a situação.'),
            self::e('MP 429','Mercado Pago','Limite de requisições','Chamadas em excesso à API.','Respeitar Retry-After, reduzir repetição e verificar cron/webhook em loop.'),
            self::e('MP 500/502/503','Mercado Pago','Indisponibilidade no provedor','Instabilidade temporária na API.','Aguardar e tentar novamente com segurança; não criar cobranças repetidas sem consultar a anterior.'),
            self::e('Invalid transaction amount','Mercado Pago','Valor com casas decimais inválidas','Float serializado com precisão excessiva ou preço cadastrado incorretamente.','Manter preços com duas casas decimais e usar a versão atual do MercadoPagoProvider.'),
            self::e('Webhook inválido','Mercado Pago','Assinatura da notificação não confere','Segredo incorreto, URL diferente, cabeçalhos ausentes ou relógio do servidor fora de sincronia.','Copiar o segredo da integração, conferir URL HTTPS, evento Orders/Payments e horário do servidor.'),

            self::e('SMTP conexão recusada','E-mail','Não conectou ao servidor','Host/porta errados, firewall ou serviço SMTP indisponível.','Testar host e porta; para cPanel normalmente usar mail.dominio, porta 465 e SSL.'),
            self::e('SMTP 535','E-mail','Falha de autenticação','Usuário ou senha incorretos; autenticação SMTP não habilitada.','Usar o endereço de e-mail completo como usuário e salvar novamente a senha da conta.'),
            self::e('SMTP 550/553','E-mail','Remetente ou destinatário rejeitado','From diferente da conta autenticada, endereço inválido ou política antispam.','Usar como remetente a própria conta autenticada; validar destinatário, SPF e DKIM.'),
            self::e('SMTP TLS falhou','E-mail','Falha na criptografia','Segurança/porta incompatíveis ou certificado inválido.','Usar SSL/465 ou TLS/587 conforme o provedor; não misturar porta e segurança.'),
            self::e('Marketing job failed','E-mail','Disparo falhou após tentativas','SMTP recusou, configuração mudou ou destinatário é inválido.','Abrir o job/log, corrigir SMTP ou contato e reenfileirar apenas após corrigir a causa.'),

            self::e('SQLSTATE 42S02','Banco de dados','Tabela inexistente','Migration não executada ou banco configurado é antigo/incorreto.','Executar as migrations da versão instalada e confirmar DB_DATABASE.'),
            self::e('SQLSTATE 42S22','Banco de dados','Coluna inexistente','Código atualizado sem a migration correspondente.','Executar migrations; não criar coluna manualmente sem conferir o arquivo SQL oficial.'),
            self::e('SQLSTATE 23000','Banco de dados','Duplicidade ou vínculo inválido','E-mail/slug já existe ou chave estrangeira aponta para registro inexistente.','Localizar o registro duplicado e corrigir o cadastro; não apagar vínculos sem backup.'),
            self::e('SQLSTATE 01000 / 1265','Banco de dados','Valor truncado','Valor enviado não existe no ENUM ou é maior/incompatível com a coluna.','Comparar status/perfil enviado com a estrutura da coluna e aplicar a migration corretiva.'),
            self::e('SQLSTATE HY000 / 1045','Banco de dados','Acesso negado ao MySQL','Usuário, senha, host ou permissões do banco incorretos.','Revisar config/database.php e privilégios do usuário no cPanel.'),
            self::e('SQLSTATE HY000 / 2002','Banco de dados','Servidor MySQL indisponível','Host/socket incorreto ou MySQL fora do ar.','No cPanel normalmente usar localhost; confirmar serviço e dados de conexão.'),
            self::e('Deadlock / 1213','Banco de dados','Conflito entre transações','Duas operações atualizaram os mesmos registros simultaneamente.','Repetir uma vez; se recorrente, identificar rotina concorrente/cron e revisar transações.'),

            self::e('Cron sem log','Cron e filas','Cron não executou ou pasta não existe','Comando/caminho PHP incorreto, cron não criado ou storage/logs sem permissão.','Conferir comando absoluto, criar storage/logs e executar manualmente antes de agendar.'),
            self::e('Jobs queued','Cron e filas','Fila acumulada','Cron atrasado, parado ou volume maior que a capacidade.','Executar worker/cron manualmente, conferir cron.log e ajustar frequência sem duplicar agendamentos.'),
            self::e('Jobs failed','Cron e filas','Tarefas esgotaram tentativas','Integração recusou, payload antigo ou configuração ausente.','Corrigir a causa no log e somente depois reenfileirar as tarefas falhas.'),

            self::e('Permission denied','Arquivos','Sem permissão de escrita/leitura','Pastas storage, uploads ou backups pertencem a outro usuário ou têm modo inadequado.','Confirmar proprietário da conta cPanel e permissões seguras; storage precisa ser gravável pelo PHP.'),
            self::e('Upload inválido','Arquivos','Arquivo recusado','Tamanho acima do limite, MIME/extensão não permitidos ou upload interrompido.','Usar formato permitido, reduzir arquivo e conferir upload_max_filesize/post_max_size.'),
            self::e('Backup falhou','Arquivos','Não criou ou concluiu o backup','Sem espaço, permissão, mysqldump indisponível ou timeout.','Conferir espaço e pasta privada, executar backup manual e consultar Central de Erros.'),
            self::e('APP_KEY inválida','Segurança','Não foi possível descriptografar segredos','APP_KEY mudou, está ausente ou não possui o formato esperado.','Restaurar exatamente a APP_KEY anterior. Não gerar outra chave em sistema com dados criptografados.'),
            self::e('Payload adulterado','Segurança','Dado criptografado não confere','APP_KEY diferente da usada ao salvar ou conteúdo alterado/corrompido.','Restaurar APP_KEY e backup corretos; depois salvar novamente a integração afetada.'),
            self::e('Módulo não incluído','Planos e módulos','Recurso bloqueado pelo plano','Módulo inativo ou não vinculado ao plano/assinatura.','No Master, ativar o módulo e vinculá-lo ao plano; confirmar atualização da assinatura.'),
            self::e('ERR-AAAAMMDD-XXXXXX','Aplicação','Identificador interno de erro','Código gerado quando uma exceção não tratada ocorre; não é a causa em si.','Pesquisar o código exato no diagnóstico acima e usar mensagem, arquivo e linha para corrigir.'),
        ];
    }

    private static function e(string $code,string $category,string $title,string $cause,string $solution):array
    {
        return compact('code','category','title','cause','solution');
    }
}
