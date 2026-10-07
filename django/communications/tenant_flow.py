"""Company chatbot knowledge and intake; no platform commercial leads or secrets."""
from django.conf import settings
from django.db.models import Q
from django.urls import reverse
from django.core.exceptions import ValidationError
from billing.access import current_subscription,subscription_allows_access
from billing.entitlements import active_subscription,module_enabled
from tenants.models import Unit,UnitBusinessHours,Tenant
from scheduling.models import Service,Professional
from .models import MasterWhatsAppFlow
from .master_graph import validate_graph
from .master_runtime import normalized


def available(tenant):
    if tenant.status not in {Tenant.Status.TRIAL,Tenant.Status.ACTIVE} or tenant.archived_at or tenant.deleted_at:return False
    subscription=current_subscription(tenant)
    if subscription and not subscription_allows_access(subscription):return False
    return not active_subscription(tenant) or module_enabled(tenant,'whatsapp')


def company_facts(tenant):
    units=list(Unit.objects.filter(tenant=tenant,active=True).order_by('-is_primary','name')[:20])
    services=Service.objects.filter(tenant=tenant,active=True).filter(Q(unit__isnull=True)|Q(unit__tenant=tenant,unit__active=True)).select_related('unit').order_by('name')[:40]
    catalog='\n'.join(f'{s.name}: R$ '+format(s.price,'.2f').replace('.',',')+f' · {s.duration_minutes} min'+(f' · {s.unit.name}' if s.unit_id else '') for s in services)
    from arena.models import Court
    courts=Court.objects.filter(tenant=tenant,active=True).filter(Q(unit__isnull=True)|Q(unit__tenant=tenant,unit__active=True)).select_related('unit').order_by('name')[:40]
    court_catalog='\n'.join(c.name+(f' · {c.unit.name}' if c.unit_id else '')+f' · reserva mínima {c.minimum_minutes} min; valores e disponibilidade na agenda' for c in courts)
    if court_catalog:catalog=(catalog+'\nQuadras:\n'+court_catalog).strip()
    addresses='\n'.join(f'{u.name}: '+', '.join(v for v in [u.address,u.address_number,u.district,u.city,u.state] if v) for u in units)
    hours='\n'.join(f'{h.unit.name} · {h.get_weekday_display()}: '+('fechado' if h.closed else f'{h.opens_at:%H:%M} às {h.closes_at:%H:%M}' if h.opens_at and h.closes_at else 'confirme com a equipe') for h in UnitBusinessHours.objects.filter(tenant=tenant,unit__in=units,active=True).select_related('unit').order_by('unit_id','weekday'))
    professionals=Professional.objects.filter(tenant=tenant,active=True).filter(Q(unit__isnull=True)|Q(unit__tenant=tenant,unit__active=True)).select_related('unit').order_by('name')[:40]
    team=', '.join(p.name+(f' ({p.unit.name})' if p.unit_id else '') for p in professionals)
    url=settings.PUBLIC_BASE_URL.rstrip('/')+reverse('tenant-public',args=[tenant.public_slug or tenant.slug])
    booking=('Para consultar horários, escolher unidade/serviço/profissional e confirmar, acesse '+url+'. O chatbot não reserva nem confirma horários: a confirmação ocorre na agenda pública.') if tenant.public_enabled and tenant.public_booking_enabled else 'A agenda pública ainda não está disponível. Nossa equipe pode ajudar com o agendamento.'
    methods={'pix':'Pix','cash':'Dinheiro','credit_card':'Cartão de crédito','debit_card':'Cartão de débito','card':'Cartão'}
    payments=', '.join(methods.get(str(m),str(m)) for m in (tenant.accepted_payment_methods or []) if isinstance(m,str))
    return {
        'empresa':f'Você está falando com {tenant.name}. '+tenant.description[:600],
        'servicos':catalog or 'Nossa equipe pode informar os serviços e valores disponíveis.',
        'unidades':addresses[:3500] or 'Confirme a localização com nossa equipe.',
        'horarios':hours[:3500] or 'Os horários de funcionamento precisam ser confirmados com a equipe.',
        'profissionais':team or 'Nossa equipe pode confirmar os profissionais disponíveis.',
        'agendamento':booking,
        'pagamentos':('Formas cadastradas: '+payments+'. Não confirmo recebimento de pagamento por mensagem.') if payments else 'Nossa equipe confirma as formas de pagamento. Não confirmo recebimento por mensagem.',
        'contato':' · '.join(v for v in [tenant.phone,tenant.email,tenant.public_instagram] if v) or 'Você pode solicitar atendimento humano nesta conversa.',
    }


def company_variables(tenant):
    facts=company_facts(tenant)
    return {'empresa_nome':tenant.name,'servicos':facts['servicos'],'unidades':facts['unidades'],'agenda_url':facts['agendamento']}


def answer_company(tenant,question):
    facts=company_facts(tenant);text=normalized(question)
    for terms,key in [(('horario','funcionamento','abre','fecha'),'horarios'),(('endereco','unidade','local','onde'),'unidades'),(('preco','valor','servico'),'servicos'),(('profissional','equipe'),'profissionais'),(('pix','cartao','pagar','pagamento'),'pagamentos'),(('agenda','reserva','cancelar','remarcar'),'agendamento'),(('contato','telefone'),'contato')]:
        if any(term in text for term in terms):return facts[key]
    return 'Posso orientar sobre os serviços, unidades e agendamento da '+tenant.name+'. Para essa dúvida, preciso da confirmação da equipe. Você pode escolher atendimento humano.'


def company_ai(tenant,flow,node,variables,incoming):
    if not flow.ai_enabled:return answer_company(tenant,incoming)
    shared=MasterWhatsAppFlow.objects.filter(pk=1).first()
    if not shared or not shared.ai_enabled or not shared.ai_key_encrypted or not shared.ai_model:raise ValueError('A IA central ainda não está configurada.')
    from .master_assistant import grounded_answer
    return grounded_answer(shared,node,{},incoming,facts=company_facts(tenant),scope='informações públicas da empresa '+tenant.name,
        outside_text='Posso te ajudar com os serviços e informações da '+tenant.name+' 😊 Para essa dúvida, nossa equipe precisa confirmar. Escolha atendimento humano no próximo passo.')


def company_intake(tenant,variables,incoming,first=False):
    variables=dict(variables);field=variables.get('_company_field','')
    fields=[('nome','Como você gostaria de ser chamado?'),('unidade_interesse','Qual unidade você prefere?'),('necessidade','Qual serviço ou ajuda você está procurando?')]
    if not first and field:
        text=incoming.strip()
        if text.endswith('?') or normalized(text).startswith(('quanto ','como ','qual preco','quero saber')):
            return variables,[answer_company(tenant,text),dict(fields).get(field,'Pode me informar seu WhatsApp com DDD?')],False
        if field=='telefone':
            from .phone import whatsapp_number
            text=whatsapp_number(text)
            valid=text.startswith('55') and len(text) in {12,13}
        else:valid=2<=len(text)<= (150 if field=='nome' else 160 if field=='unidade_interesse' else 1000)
        if not valid:return variables,['Pode conferir esse dado e enviar novamente?'],False
        variables[field]=text
    phone=variables.get('telefone','') or variables.get('contact_phone','')
    if not phone.startswith('55') or len(phone) not in {12,13}:
        variables['_company_field']='telefone';return variables,['Qual seu WhatsApp com DDD? Usaremos esse contato apenas para atender sua solicitação.'],False
    for key,prompt in fields:
        if not variables.get(key):
            variables['_company_field']=key
            notice=['Vou organizar alguns dados para nossa equipe continuar por aqui, sem você repetir tudo. Não há inscrição automática em campanhas.'] if first else []
            return variables,notice+[prompt],False
    variables.pop('_company_field',None)
    return variables,['Obrigado, {{nome}}! Vou encaminhar sua necessidade e unidade preferida para nossa equipe.'],True


def validate_company_graph(graph):
    graph=validate_graph(graph)
    if any(n['type'] in {'api','legacy'} for n in graph['nodes']):raise ValidationError('Use os blocos de atendimento, lógica, IA e controle do chatbot da empresa. Integrações externas e o motor legado não são importados aqui.')
    for n in graph['nodes']:
        if n['type']=='ai':n['config']['applanner_only']=True
    return graph


def company_graph():
    def n(key,kind,label,x,y,cfg,out):return {'id':key,'type':kind,'label':label,'x':x,'y':y,'config':cfg,'outputs':out}
    return {'version':2,'start':'start','nodes':[
        n('start','start','Boas-vindas',600,40,{'text':'Olá! Seja bem-vindo à {{empresa_nome}} 😊 Sou o assistente virtual da equipe. Quero entender o que você precisa e facilitar seu atendimento.'},{'next':'menu'}),
        n('menu','menu','Como podemos ajudar?',600,260,{'text':'Por onde você gostaria de começar?','options':[{'id':'agenda','label':'Conhecer serviços / agendar','keywords':['agendar','serviços','servicos']},{'id':'duvidas','label':'Tirar uma dúvida','keywords':['duvida','dúvida']},{'id':'equipe','label':'Conversar com a equipe','keywords':['equipe','ajuda']}]},{'agenda':'servicos','duvidas':'pergunta','equipe':'triagem','invalid':'livre'}),
        n('servicos','message','Serviços e agenda',150,550,{'text':'Veja nossos serviços cadastrados:\n{{servicos}}\n\n{{agenda_url}}'},{'next':'triagem'}),
        n('pergunta','input','Sua dúvida',600,550,{'text':'Pode me contar sua dúvida sobre nossos serviços ou atendimento.','variable':'pergunta','validation':'text'},{'next':'ia'}),
        n('ia','ai','Assistente da empresa',600,800,{'prompt':'Oriente somente com informações públicas desta empresa.','variable':'resposta_ia','send_output':True,'applanner_only':True},{'next':'seguir','error':'humano'}),
        n('livre','ai','Dúvida livre',1050,550,{'prompt':'Oriente somente com informações públicas desta empresa.','variable':'resposta_ia','send_output':True,'applanner_only':True},{'next':'seguir','error':'humano'}),
        n('seguir','menu','Próximo passo',1050,850,{'text':'Como você prefere continuar?','options':[{'id':'mais','label':'Tenho outra dúvida','keywords':['mais','duvida']},{'id':'dados','label':'Quero atendimento da equipe','keywords':['equipe','atendimento']},{'id':'fim','label':'Por enquanto é só','keywords':['obrigado','sair']}]},{'mais':'pergunta','dados':'triagem','fim':'fim','invalid':'livre'}),
        n('triagem','input','Entender a necessidade',150,800,{'text':'Qual serviço ou ajuda você procura? Se quiser agendar, conte também sua preferência de dia. Vou levar essa informação à equipe.','variable':'necessidade','validation':'text'},{'next':'dados'}),
        n('dados','commercial','Dados do cliente',150,1050,{}, {'next':'humano'}),
        n('humano','handoff','Atendimento da empresa',150,1400,{'text':'Nossa equipe recebeu sua solicitação e vai continuar por aqui assim que estiver disponível. Seu agendamento só estará confirmado após concluir a reserva na agenda ou receber a confirmação da equipe.'},{}),
        n('fim','finish','Até logo',1050,1200,{'text':'Foi um prazer ajudar 😊 Quando precisar, pode chamar!'},{}),
    ]}
