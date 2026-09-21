<?php
namespace App\Services;

use App\Core\Database;

final class LegalDocumentService
{
    public static function ensureDefaults(): void
    {
        $pdo=Database::connection();
        $count=(int)$pdo->query('SELECT COUNT(*) FROM legal_documents')->fetchColumn();
        if($count>0)return;
        $docs=[
            ['terms','1.0','Termos de Uso',self::defaultTerms()],
            ['privacy','1.0','Política de Privacidade',self::defaultPrivacy()],
        ];
        $q=$pdo->prepare("INSERT INTO legal_documents(type,version,title,content,status,published_at,created_at,updated_at)VALUES(:type,:version,:title,:content,'published',NOW(),NOW(),NOW())");
        foreach($docs as [$type,$version,$title,$content])$q->execute(compact('type','version','title','content'));
    }

    public static function current(string $type): ?array
    {
        self::ensureDefaults();
        $q=Database::connection()->prepare("SELECT * FROM legal_documents WHERE type=:type AND status='published' ORDER BY published_at DESC,id DESC LIMIT 1");
        $q->execute(['type'=>$type]);$row=$q->fetch();return $row?:null;
    }

    public static function published(): array
    {
        return ['terms'=>self::current('terms'),'privacy'=>self::current('privacy')];
    }

    public static function acceptCurrent(int $userId, ?int $tenantId): void
    {
        $pdo=Database::connection();
        foreach(self::published() as $doc){if(!$doc)continue;$q=$pdo->prepare("INSERT IGNORE INTO legal_acceptances(document_id,tenant_id,user_id,ip_address,user_agent,accepted_at)VALUES(:document,:tenant,:user,:ip,:ua,NOW())");$q->execute(['document'=>$doc['id'],'tenant'=>$tenantId,'user'=>$userId,'ip'=>$_SERVER['REMOTE_ADDR']??null,'ua'=>substr((string)($_SERVER['HTTP_USER_AGENT']??''),0,500)]);}
    }

    public static function pendingForUser(int $userId): array
    {
        $pdo=Database::connection();$pending=[];
        foreach(self::published() as $type=>$doc){if(!$doc)continue;$q=$pdo->prepare('SELECT 1 FROM legal_acceptances WHERE user_id=:u AND document_id=:d');$q->execute(['u'=>$userId,'d'=>$doc['id']]);if(!$q->fetchColumn())$pending[$type]=$doc;}
        return $pending;
    }

    public static function rendered(array $doc): string
    {
        $app=require __DIR__.'/../../config/app.php';
        $vars=[
            '{{APP_NAME}}'=>$app['name']??'Plataforma de Agendamento',
            '{{LEGAL_NAME}}'=>PlatformSetting::get('legal.legal_name',$app['name']??'Administradora da plataforma'),
            '{{DOCUMENT}}'=>PlatformSetting::get('legal.document','não informado'),
            '{{SUPPORT_EMAIL}}'=>PlatformSetting::get('legal.support_email',PlatformSetting::get('platform.system_email','canal de suporte disponível no painel')),
            '{{PRIVACY_EMAIL}}'=>PlatformSetting::get('legal.privacy_email',PlatformSetting::get('legal.support_email',PlatformSetting::get('platform.system_email','canal de privacidade disponível no painel'))),
            '{{ADDRESS}}'=>PlatformSetting::get('legal.address','endereço da administradora informado no painel'),
            '{{FORO}}'=>PlatformSetting::get('legal.foro','foro da sede da administradora, observada a legislação aplicável'),
        ];
        return strtr((string)$doc['content'],$vars);
    }

    private static function defaultTerms(): string
    {
        return <<<'TXT'
TERMOS DE USO — {{APP_NAME}}

1. IDENTIFICAÇÃO E ACEITE
Estes Termos regulam o acesso e uso da plataforma {{APP_NAME}}, operada por {{LEGAL_NAME}}, documento {{DOCUMENT}}, doravante denominada “Plataforma”. Ao criar uma conta, contratar um plano ou continuar utilizando os serviços após a publicação de uma nova versão que exija aceite, o usuário declara que leu e concorda com estes Termos.

2. OBJETO
A Plataforma disponibiliza recursos de gestão de agenda, clientes, profissionais, serviços, produtos, vendas, relatórios, automações, inteligência de retorno, suporte e outros módulos contratados. Recursos disponíveis variam conforme o plano, módulos adicionais e segmento do estabelecimento.

3. CONTA E RESPONSABILIDADE DO CONTRATANTE
O contratante deve fornecer dados verdadeiros, manter credenciais em segurança, definir corretamente as permissões de sua equipe e comunicar imediatamente acessos suspeitos. Cada profissional deve utilizar acesso individual. O contratante é responsável pelos dados, serviços, preços, conteúdos e informações inseridos por sua equipe e por garantir que possui base legal e autorização para tratar dados de seus clientes.

4. PÁGINA PÚBLICA E AGENDAMENTOS
Cada estabelecimento poderá possuir link público para consulta de serviços, profissionais e horários disponíveis. O contratante é responsável por manter agenda, disponibilidade, preços e informações comerciais atualizados. A Plataforma aplica controles para reduzir conflitos de horários, mas alterações externas, falhas de integração ou indisponibilidade de infraestrutura podem exigir conferência operacional pelo estabelecimento.

5. TESTE GRÁTIS, PLANOS E MÓDULOS
Quando disponibilizado, o teste grátis possui duração informada no momento do cadastro. Ao término, a continuidade dos recursos contratados poderá depender da regularização da assinatura. Planos e módulos possuem limites, funcionalidades e preços apresentados na área de assinatura. Módulos adicionais solicitados separadamente podem gerar cobrança recorrente própria após aprovação e contratação.

6. COBRANÇAS E PAGAMENTOS
Cobranças da assinatura da Plataforma podem ser processadas por provedores de pagamento integrados. Dados completos de cartão e código de segurança não são armazenados pela Plataforma quando o fluxo é tokenizado pelo provedor. Valores, periodicidade, vencimentos, descontos e status ficam disponíveis na área de assinatura. Em caso de inadimplência, a conta poderá entrar em modo restrito, preservando dados conforme a política aplicável.

7. CANCELAMENTO
O contratante pode solicitar cancelamento conforme as condições exibidas no plano e na área de assinatura. O cancelamento não elimina automaticamente obrigações financeiras já vencidas. Dados poderão permanecer armazenados durante período necessário para cumprimento de obrigações legais, segurança, auditoria, defesa de direitos e política de retenção.

8. USO ACEITÁVEL
É proibido utilizar a Plataforma para prática ilícita, fraude, spam, envio abusivo de mensagens, tentativa de acesso a dados de terceiros, exploração de vulnerabilidades, engenharia reversa indevida, disseminação de malware, violação de direitos ou qualquer atividade que comprometa a segurança ou disponibilidade do serviço.

9. COMUNICAÇÕES E AUTOMAÇÕES
O contratante deve respeitar consentimentos, preferências e direitos dos titulares ao utilizar comunicações comerciais. Mensagens operacionais relacionadas a agendamento e atendimento devem ser diferenciadas de campanhas de marketing. O contratante permanece responsável pelo conteúdo e pela legitimidade das comunicações enviadas a seus clientes.

10. DADOS CLÍNICOS E MÓDULOS DE SAÚDE
Quando módulos de prontuário estiverem habilitados, seu uso exige controles adicionais de acesso e responsabilidade profissional. O contratante deve observar a legislação, normas profissionais e regras aplicáveis ao tratamento de dados pessoais sensíveis. Recursos de inteligência comercial não devem ser utilizados para inferir necessidade médica com base em diagnóstico, medicação, anamnese ou prontuário.

11. DISPONIBILIDADE, MANUTENÇÃO E SUPORTE
A Plataforma busca manter disponibilidade adequada, mas poderá realizar manutenção programada, atualizações e intervenções emergenciais. Incidentes decorrentes de provedores externos, internet, hospedagem, gateways, e-mail, WhatsApp ou serviços de terceiros podem afetar temporariamente funcionalidades. O suporte é prestado pelos canais disponibilizados no painel.

12. ACESSO ASSISTIDO DE SUPORTE
Quando o contratante autorizar, a equipe da Plataforma poderá iniciar acesso assistido temporário para investigar chamado específico. O acesso é auditado, identificado visualmente e deve ser encerrado após o atendimento. A autorização de suporte não concede acesso irrestrito a informações clínicas ou segredos protegidos.

13. PROPRIEDADE INTELECTUAL
O software, identidade, código, documentação, interfaces e demais ativos da Plataforma permanecem protegidos pela legislação aplicável. O contratante mantém a titularidade e responsabilidade sobre seus próprios dados, marcas, conteúdos e materiais inseridos.

14. SEGURANÇA
A Plataforma utiliza controles técnicos e administrativos de segurança, incluindo autenticação, segregação entre empresas, registros de auditoria, criptografia de segredos e proteção de sessões. Nenhum sistema conectado à internet é absolutamente imune a incidentes, razão pela qual usuários também devem adotar boas práticas e manter seus dispositivos seguros.

15. LIMITAÇÃO E RESPONSABILIDADES
Cada parte responde por seus atos e obrigações na forma da legislação aplicável. A Plataforma não garante resultados comerciais específicos, quantidade de clientes, faturamento ou ausência absoluta de indisponibilidades. Estimativas de retorno, receita potencial e previsões são indicadores de apoio à decisão e não garantias de resultado.

16. ALTERAÇÕES DESTES TERMOS
Os Termos podem ser atualizados para refletir mudanças legais, técnicas ou comerciais. Alterações relevantes poderão exigir novo aceite. A versão e a data de publicação permanecem disponíveis nesta página.

17. LEGISLAÇÃO E FORO
Aplica-se a legislação brasileira, inclusive as normas de proteção de dados e do consumidor quando cabíveis. Fica indicado {{FORO}}, sem prejuízo de foro obrigatório previsto em lei.

18. CONTATO
Dúvidas contratuais e de suporte: {{SUPPORT_EMAIL}}.
TXT;
    }

    private static function defaultPrivacy(): string
    {
        return <<<'TXT'
POLÍTICA DE PRIVACIDADE — {{APP_NAME}}

1. OBJETIVO
Esta Política explica como {{LEGAL_NAME}}, documento {{DOCUMENT}}, trata dados pessoais relacionados ao uso da plataforma {{APP_NAME}}. O tratamento pode variar conforme o usuário seja administrador da plataforma, estabelecimento contratante, profissional, usuário interno ou cliente final de um estabelecimento.

2. PAPÉIS NO TRATAMENTO DE DADOS
Para dados necessários à criação da conta, faturamento, segurança, suporte e administração do SaaS, a administradora da Plataforma atua conforme o papel jurídico aplicável. Para dados de clientes inseridos e utilizados pelo estabelecimento em sua operação, o estabelecimento normalmente define as finalidades e instruções de tratamento, cabendo à Plataforma atuar tecnicamente conforme o serviço contratado e os instrumentos aplicáveis.

3. DADOS QUE PODEM SER TRATADOS
Podem ser tratados dados cadastrais, nome, e-mail, telefone, empresa, registros de acesso, IP, navegador, informações de assinatura e pagamento tokenizado, histórico de suporte, configurações, registros de agenda, serviços, produtos, vendas e demais informações inseridas no sistema. Em módulos de saúde podem existir dados pessoais sensíveis, cujo acesso deve observar controles específicos.

4. DADOS DE PAGAMENTO
A Plataforma pode armazenar identificadores, status, bandeira e últimos dígitos quando fornecidos pelo provedor, mas não deve armazenar código de segurança ou número completo do cartão quando o processamento for realizado por tokenização do gateway.

5. FINALIDADES
Os dados podem ser utilizados para criar e autenticar contas; operar agenda e funcionalidades contratadas; processar assinaturas; prestar suporte; proteger a segurança da Plataforma; gerar registros de auditoria; enviar comunicações operacionais; cumprir obrigações legais; prevenir fraude; melhorar a experiência e produzir métricas de uso com minimização de dados.

6. BASES LEGAIS
O tratamento utiliza as bases legais aplicáveis ao contexto, incluindo execução de contrato e procedimentos preliminares, cumprimento de obrigação legal ou regulatória, exercício regular de direitos, legítimo interesse quando cabível e consentimento quando exigido. Dados sensíveis são tratados apenas nas hipóteses legalmente permitidas e de acordo com as finalidades do módulo utilizado.

7. MARKETING E PREFERÊNCIAS
Campanhas promocionais devem respeitar consentimentos e preferências registradas. O titular pode solicitar interrupção das comunicações de marketing pelos mecanismos disponibilizados. Comunicações estritamente operacionais, como confirmação de agendamento, segurança e cobrança, podem seguir regras distintas conforme sua finalidade e base legal.

8. COMPARTILHAMENTO E OPERADORES
Dados podem ser processados por fornecedores necessários à operação, como hospedagem, e-mail, mensageria, gateway de pagamento e infraestrutura, observando necessidade, segurança e contratos aplicáveis. A Plataforma não vende dados pessoais a anunciantes.

9. SEGURANÇA
São adotadas medidas como controle de acesso, isolamento entre empresas, criptografia de segredos, proteção de sessões, registros de auditoria, backups e validações de entrada. Incidentes são tratados conforme procedimentos internos e requisitos legais aplicáveis.

10. RETENÇÃO
Dados são mantidos pelo período necessário para prestar os serviços, cumprir obrigações legais e regulatórias, prevenir fraude, resguardar direitos, manter auditoria e aplicar políticas de retenção. Prazos podem variar conforme a natureza da informação e o segmento do estabelecimento.

11. DIREITOS DOS TITULARES
O titular poderá exercer os direitos previstos na Lei Geral de Proteção de Dados, conforme aplicáveis, incluindo confirmação de tratamento, acesso, correção, informações sobre compartilhamento, portabilidade quando regulamentada e aplicável, oposição, revogação de consentimento e solicitações relacionadas à eliminação ou anonimização, observadas hipóteses legais de conservação.

12. DADOS DE CLIENTES DOS ESTABELECIMENTOS
Pedidos relacionados a dados operacionais de clientes podem precisar ser direcionados inicialmente ao estabelecimento responsável pelo relacionamento. A Plataforma poderá apoiar o estabelecimento no atendimento ao titular quando tecnicamente necessário.

13. DADOS CLÍNICOS
Informações de prontuário, diagnóstico, medicação, anamnese e demais dados de saúde não devem ser utilizadas pelo motor comercial de marketing ou pela inteligência de retorno para inferências médicas. O acesso a módulos clínicos é restrito conforme perfil, vínculo e permissões.

14. COOKIES, SESSÃO E REGISTROS TÉCNICOS
A Plataforma utiliza cookies e identificadores estritamente necessários para autenticação, segurança, preferências e funcionamento. Registros técnicos podem incluir IP, data, navegador, tentativas de login, eventos de segurança e ações auditáveis.

15. TRANSFERÊNCIAS E INFRAESTRUTURA
Quando fornecedores ou infraestrutura tratarem dados em outras localidades, serão observados os mecanismos legais e contratuais aplicáveis à transferência e proteção das informações.

16. MENORES DE IDADE
Quando um estabelecimento atender menores, cabe ao responsável pelo estabelecimento observar as regras específicas aplicáveis e obter autorizações necessárias conforme a natureza do serviço e legislação vigente.

17. ALTERAÇÕES
Esta Política pode ser atualizada. Mudanças relevantes podem ser comunicadas no painel e, quando necessário, será solicitado novo aceite. A versão vigente permanece publicada nesta página.

18. CANAL DE PRIVACIDADE
Solicitações relacionadas à privacidade podem ser encaminhadas para {{PRIVACY_EMAIL}}. Endereço da administradora: {{ADDRESS}}.
TXT;
    }
}
