"""First-party sales guidance: live public plans, bounded FAQ and progressive intake."""
import re
from django.core.validators import validate_email
from django.core.exceptions import ValidationError


def plans_data():
    from billing.models import Plan
    return [{'id':p.pk,'name':p.name,'description':p.description,'monthly_price':str(p.monthly_price),'trial_days':p.trial_days,'trial_without_card':p.trial_without_card,'is_custom':p.is_custom,
             'modules':list(p.module_links.filter(enabled=True,module__active=True).values_list('module__name',flat=True))}
            for p in Plan.objects.filter(active=True,public_visible=True).order_by('sort_order','pk')[:20]]


def plans_text():
    rows=plans_data()
    if not rows:return 'Nossa equipe vai confirmar os planos disponíveis e preparar uma proposta para você.'
    lines=[]
    for p in rows:
        price='Sob proposta' if p['is_custom'] else 'R$ '+p['monthly_price'].replace('.',',')+'/mês'
        trial=f" Teste de {p['trial_days']} dias"+(' sem cartão.' if p['trial_without_card'] else '.') if p['trial_days'] and not p['is_custom'] else ''
        modules=' Inclui: '+', '.join(p['modules'][:6])+'.' if p['modules'] else ''
        lines.append(f"• {p['name']} — {price}. {p['description'][:120]}{trial}{modules}")
    return '\n'.join(lines)+'\nValores acima são mensais regulares. Promoções, adicionais e outros ciclos são confirmados na contratação.'


FAQ=[
    (('plano','preco','valor','custa','mensalidade','teste','gratis','gratuito'),None),
    (('unidade','filial','profissionais','funcionario','equipe'), 'Você pode trabalhar com várias unidades, cada uma com agenda, endereço e configurações próprias. Cada unidade adicional inclui mais 3 profissionais; extras dependem dos módulos contratados. Nossa equipe confirma os limites e valores do plano escolhido.'),
    (('arena','quadra','esporte'), 'Para arenas, o ApPlanner organiza quadras, horários e reservas. Essa operação precisa de um plano com o módulo Arena; posso apresentar as opções disponíveis.'),
    (('pix','cartao','pagamento','cobranca'), 'A assinatura permite Pix ou cartão conforme a cobrança disponível. A empresa pode configurar pagamentos de agendamentos conforme seu plano e cadastro bancário. A liberação depende da confirmação do pagamento; não consigo confirmar um pagamento apenas pela mensagem.'),
    (('whatsapp','lembrete','mensagem','notificacao'), 'O WhatsApp da empresa pode enviar avisos habilitados e convites de retorno conforme o módulo, a conexão e as permissões. O profissional tem limites para contatar clientes já atendidos. Podemos confirmar os recursos incluídos no seu plano.'),
    (('agendar','agendamento','agenda','cliente','link','site'), 'Seus clientes acessam a página pública da empresa, escolhem unidade, serviço, profissional e horário disponível. Cada unidade recebe seus próprios agendamentos. Você acompanha tudo pelo painel da operação.'),
    (('cep','endereco','localizacao','explorar'), 'O CEP ajuda a completar o endereço da unidade. Com coordenadas válidas e permissão de localização do dispositivo, o Explorar mostra unidades próximas em até 30 km, com distância. Se a localização for negada, é possível informar uma localização manualmente.'),
    (('financeiro','comissao','produto','estoque','lucro'), 'A operação reúne agenda e recursos financeiros, incluindo vendas, produtos, estoque e comissões conforme os módulos. O resultado considera pagamentos aprovados e despesas registradas; nossa equipe ajuda a conferir a configuração.'),
    (('api','integracao','seguranca','dados','privacidade'), 'Há documentação e tokens pessoais de API com escopos e validade. O acesso depende do perfil e das permissões. Posso encaminhar sua dúvida técnica à equipe sem solicitar senhas ou credenciais aqui.'),
    (('cancelar','remarcar','reagendar'), 'O cliente pode usar os links disponíveis para remarcar ou cancelar, respeitando as regras da empresa. Na contratação, confira também os termos e a política de cancelamento.'),
    (('applanner','funciona','recursos'), 'O ApPlanner ajuda a organizar agendamentos, clientes, equipe e a operação do seu estabelecimento. Há recursos para barbearias/salões, arenas e automotivo, conforme o plano e os módulos. Conte qual é seu segmento e o que você precisa resolver; nossa equipe ajuda a escolher a configuração.'),
]


def answer_question(text):
    from .master_runtime import normalized
    question=normalized(text)
    for words,answer in FAQ:
        if any(re.search(r'\b'+re.escape(w)+r'\w*',question) for w in words):return answer or plans_text()
    return 'Quero te orientar com informação correta. Não encontrei uma resposta segura para essa pergunta; vou registrar sua dúvida para nossa equipe. Posso explicar planos, agenda, unidades, pagamentos, WhatsApp, financeiro e API.'


FIELDS=[
    ('nome','Para começarmos, como você gostaria de ser chamado?'),
    ('empresa','Prazer, {{nome}}! Qual é o nome do seu estabelecimento?'),
    ('segmento','Em qual segmento a {{empresa}} atua? Por exemplo: barbearia/salão, arena ou automotivo.'),
    ('email','Qual e-mail podemos usar para enviar a orientação ou proposta?'),
    ('unidades','Quantas unidades você pretende utilizar?'),
    ('profissionais','Quantos profissionais vão atender? Se for arena, informe 0.'),
    ('plano_interesse','Qual plano chamou sua atenção? Se ainda não decidiu, pode responder “preciso de ajuda”.'),
    ('necessidade','O que você mais precisa resolver com o sistema? Pode contar em poucas palavras.'),
]


def sales_turn(variables,incoming,first=False):
    from .master_runtime import normalized,expand
    variables=dict(variables)
    field=variables.get('_sales_field','')
    question=normalized(incoming)
    if not first and (question.endswith('?') or question.startswith(('como ','quanto ','o sistema ','voces ','tem como ','qual plano','tem ','posso ','pode ','quero saber','gostaria de saber'))):
        variables['ultima_duvida']=incoming[:1000]
        prompt=next((p for k,p in FIELDS if k==field),'')
        return variables,[answer_question(incoming),expand(prompt,variables)],False
    if not first and field:
        value=incoming.strip()
        valid=bool(value) and len(value)<=160 if field in {'nome','empresa','segmento'} else bool(value) and len(value)<=1000
        if field=='email':
            try:validate_email(value)
            except ValidationError:valid=False
            valid=valid and len(value)<=254
        if field in {'unidades','profissionais'}:valid=value.isdecimal() and len(value)<=4 and (1 if field=='unidades' else 0)<=int(value)<=999
        if field=='telefone':valid=bool(re.fullmatch(r'\d{10,15}',re.sub(r'\D','',value)))
        if not valid:
            prompt='Informe um e-mail válido, por favor.' if field=='email' else 'Informe a quantidade em números, por favor.' if field in {'unidades','profissionais'} else 'Pode conferir esse dado e enviar novamente?'
            return variables,[prompt],False
        variables[field]=re.sub(r'\D','',value) if field=='telefone' else value
    if not re.fullmatch(r'\d{10,15}',variables.get('contact_phone','')) and not variables.get('telefone'):
        variables['_sales_field']='telefone'
        return variables,['Qual seu WhatsApp, com país e DDD? Vou usar esse número apenas para este atendimento.'],False
    for key,prompt in FIELDS:
        if not variables.get(key):
            variables['_sales_field']=key
            notice=['Sou o assistente virtual do ApPlanner 😊 Vou coletar alguns dados para nossa equipe continuar daqui, sem você precisar repetir tudo. Usaremos essas informações para atender sua solicitação, sem inscrição automática em campanhas.'] if first else []
            return variables,notice+[expand(prompt,variables)],False
    variables.pop('_sales_field',None)
    return variables,['Obrigado, {{nome}}! Já organizei os dados da {{empresa}} e sua necessidade. Vou encaminhar tudo para nossa equipe continuar o atendimento por aqui. Não precisa repetir as informações.'],True


def commercial_graph():
    def n(key,kind,label,x,y,config,outputs):return {'id':key,'type':kind,'label':label,'x':x,'y':y,'config':config,'outputs':outputs}
    return {'version':2,'start':'start','nodes':[
        n('start','start','Boas-vindas',600,40,{'text':'Olá! Que bom ter você por aqui 😊 Sou o assistente virtual do ApPlanner. Posso ajudar a conhecer o sistema e escolher uma solução para seu negócio.'},{'next':'menu'}),
        n('menu','menu','Como podemos ajudar?',600,260,{'text':'O que você gostaria de fazer agora?','options':[{'id':'planos','label':'Conhecer planos e valores','keywords':['planos','preço','precos','valores']},{'id':'duvidas','label':'Tirar uma dúvida sobre o sistema','keywords':['dúvida','duvida','sistema']},{'id':'equipe','label':'Receber orientação da equipe','keywords':['contratar','proposta','ajuda']}]},{'planos':'planos','duvidas':'pergunta','equipe':'cadastro','invalid':'resposta_livre'}),
        n('planos','message','Planos atuais',150,550,{'text':'Estas são as opções cadastradas hoje:\n{{public_plans}}'},{'next':'cadastro'}),
        n('pergunta','input','Sua dúvida',600,550,{'text':'Pode me contar sua dúvida com suas palavras.','variable':'pergunta','validation':'text'},{'next':'resposta'}),
        n('resposta','knowledge','Orientação sobre o sistema',600,800,{'variable':'pergunta'},{'next':'seguir'}),
        n('resposta_livre','knowledge','Dúvida livre',1050,550,{'variable':'_message'},{'next':'seguir'}),
        n('seguir','menu','Próximo passo',1050,850,{'text':'Como você prefere continuar?','options':[{'id':'mais','label':'Tenho outra dúvida','keywords':['dúvida','outra','mais']},{'id':'dados','label':'Quero uma orientação ou proposta','keywords':['proposta','contratar','equipe']},{'id':'fim','label':'Por enquanto é só, obrigado','keywords':['obrigado','sair']}]},{'mais':'pergunta','dados':'cadastro','fim':'fim','invalid':'resposta_livre'}),
        n('cadastro','commercial','Cadastro automático do lead',150,1050,{}, {'next':'humano'}),
        n('humano','handoff','Equipe ApPlanner',150,1350,{'text':'Nossa equipe recebeu sua solicitação e continuará por aqui assim que estiver disponível. Enquanto isso, pode deixar uma observação nesta conversa.'},{}),
        n('fim','finish','Até logo',1050,1200,{'text':'Foi um prazer ajudar! Quando precisar, pode chamar por aqui 😊'},{}),
    ]}
