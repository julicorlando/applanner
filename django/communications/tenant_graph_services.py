"""Durable tenant-only runner and replies over each company's existing connection."""
import logging
from datetime import timedelta
from functools import partial
from django.db import transaction
from django.db.models import Q,F
from django.utils import timezone
from core.crypto import decrypt_json,encrypt_json
from .models import ChatbotFlow,WhatsAppConversation,WhatsAppMessage,TenantFlowDelivery,TenantWhatsAppConnection
from .master_runtime import run_graph,normalized
from .tenant_flow import available,company_variables,company_ai,company_intake,answer_company,validate_company_graph

logger=logging.getLogger(__name__)
HUMAN={'humano','atendente','atendimento','atendimento humano','falar com um atendente','quero falar com um atendente','quero falar com atendente','quero atendimento humano'}


def enqueue(message_id):
    from .tasks import process_tenant_chatbot
    try:process_tenant_chatbot.delay(message_id)
    except Exception:logger.warning('Tenant chatbot awaits queue reconciliation: %s',message_id)


def dispatch(delivery_id):
    from .tasks import deliver_tenant_flow_message
    try:deliver_tenant_flow_message.delay(delivery_id)
    except Exception:logger.warning('Tenant flow reply awaits queue reconciliation: %s',delivery_id)


@transaction.atomic
def advance(conversation_id,message_id=None,resume=False):
    conversation=WhatsAppConversation.objects.select_for_update(of=("self",)).select_related('tenant','appointment').get(pk=conversation_id)
    flow=ChatbotFlow.objects.filter(tenant=conversation.tenant,enabled=True).first()
    incoming=WhatsAppMessage.objects.filter(pk=message_id,conversation=conversation,tenant=conversation.tenant,direction='in').first() if message_id else None
    if not flow or conversation.status!=WhatsAppConversation.Status.BOT or conversation.appointment_id or (message_id and (not incoming or incoming.flow_processed_at)):return
    if not available(conversation.tenant) or incoming and (not incoming.body.strip() or incoming.created_at<flow.updated_at):
        if incoming:incoming.flow_processed_at=timezone.now();incoming.save(update_fields=['flow_processed_at'])
        return
    if resume and (not conversation.flow_wake_at or conversation.flow_wake_at>timezone.now()):return
    if incoming and WhatsAppMessage.objects.filter(conversation=conversation,tenant=conversation.tenant,direction='in',pk__lt=incoming.pk,flow_processed_at__isnull=True,created_at__gte=flow.updated_at).exists():return
    body=incoming.body[:2000] if incoming else ''
    revision=flow.updated_at.isoformat()
    event=f'tenant-in-{incoming.pk}' if incoming else f'tenant-wake-{conversation.pk}-{int(conversation.flow_wake_at.timestamp())}'
    context=decrypt_json(conversation.flow_context_encrypted) if conversation.flow_context_encrypted else {'variables':{}}
    state,waiting=conversation.bot_state,conversation.flow_wait_kind
    if resume and conversation.flow_revision!=revision:
        conversation.flow_wake_at=None;conversation.status=WhatsAppConversation.Status.WAITING_HUMAN
        conversation.flow_last_error='O fluxo foi alterado durante a espera. Reinicie o atendimento.'
        conversation.save(update_fields=['flow_wake_at','status','flow_last_error','updated_at']);return
    if state=='__finished__' or conversation.flow_revision!=revision:
        context={'variables':{}};state=flow.graph.get('start','welcome');waiting=''
    variables=context.setdefault('variables',{});variables.update(company_variables(conversation.tenant))
    variables['contact_name']=conversation.contact_name
    jid=conversation.context.get('_chatbot_jid','')
    phone=conversation.wa_id if not jid.endswith('@lid') and conversation.wa_id.startswith('55') and len(conversation.wa_id) in {12,13} else ''
    variables['contact_phone']=phone
    if normalized(body).strip(' .!?') in HUMAN:
        result={'state':'__finished__','context':context,'waiting':'','messages':[flow.handoff],'handoff':True,'wake_seconds':None,'error':''}
    elif flow.graph:
        try:
            graph=validate_company_graph(flow.graph)
            result=run_graph(graph,flow,state,context,waiting,body,resume=resume,event_key=event,
                knowledge_handler=partial(answer_company,conversation.tenant),ai_handler=partial(company_ai,conversation.tenant),intake_handler=partial(company_intake,conversation.tenant))
        except Exception as exc:
            result={'state':'__finished__','context':context,'waiting':'','messages':[flow.handoff],'handoff':True,'wake_seconds':None,'error':'Falha do fluxo ('+type(exc).__name__+').'}
    else:
        from .chatbot import next_reply
        first=not conversation.messages.filter(direction='in',pk__lt=incoming.pk).exists() if incoming else False
        reply,status=next_reply(flow,conversation,body,first_message=first)
        result={'state':'welcome','context':context,'waiting':'','messages':[reply] if reply else [],'handoff':status==WhatsAppConversation.Status.WAITING_HUMAN,'wake_seconds':None,'error':''}
    # Preserve existing customer identity, preferences and marketing consent.
    data=result['context']['variables'];phone=data.get('telefone') or data.get('contact_phone','')
    if data.get('nome') and phone and not conversation.customer_id:
        from scheduling.customer_identity import resolve_customer
        from django.core.exceptions import ValidationError
        try:
            customer,_=resolve_customer(conversation.tenant,data['nome'],phone)
            conversation.customer=customer
        except ValidationError:
            result['handoff']=True;result['error']='Confira os dados do cliente antes de vincular o cadastro.'
    if result['handoff']:
        TenantFlowDelivery.objects.filter(conversation=conversation,status__in=['queued','failed']).update(status='cancelled')
    transport=incoming.chatbot_transport if incoming and incoming.chatbot_transport else conversation.context.get('_chatbot_transport','qr')
    for index,text in enumerate(result['messages']):
        row,_=TenantFlowDelivery.objects.get_or_create(event_key=f'{event}-{index}',defaults={'conversation':conversation,'transport':transport,'body':text[:4096]})
        transaction.on_commit(lambda pk=row.pk:dispatch(pk))
    conversation.bot_state=result['state'];conversation.flow_wait_kind=result['waiting']
    conversation.flow_context_encrypted=encrypt_json(result['context']);conversation.flow_revision=revision
    if result['waiting']!='wait' or result['wake_seconds']:
        conversation.flow_wake_at=timezone.now()+timedelta(seconds=result['wake_seconds']) if result['wake_seconds'] else None
    conversation.status=WhatsAppConversation.Status.WAITING_HUMAN if result['handoff'] else WhatsAppConversation.Status.BOT
    conversation.flow_last_error=result['error'];conversation.last_message_at=timezone.now()
    conversation.save(update_fields=['customer','bot_state','flow_wait_kind','flow_context_encrypted','flow_revision','flow_wake_at','status','flow_last_error','last_message_at','updated_at'])
    if incoming:incoming.flow_processed_at=timezone.now();incoming.save(update_fields=['flow_processed_at'])


def _record(row,provider_id):
    if not provider_id:raise ValueError('Envio não confirmado.')
    message,_=WhatsAppMessage.objects.get_or_create(provider_message_id=provider_id,defaults={'conversation':row.conversation,'tenant':row.conversation.tenant,
        'direction':'out','sender_type':'bot','message_type':'text','body':row.body,'status':'sent','sent_at':timezone.now()})
    if message.conversation_id!=row.conversation_id or message.tenant_id!=row.conversation.tenant_id or message.body!=row.body:raise ValueError('Identificador de envio divergente.')
    row.status='sent';row.sent_at=timezone.now();row.last_error=''


def deliver(pk):
    cloud=None
    with transaction.atomic():
        row=TenantFlowDelivery.objects.select_related('conversation__tenant').filter(pk=pk).first()
        if not row:return
        conversation=WhatsAppConversation.objects.select_for_update(of=("self",)).select_related('tenant').get(pk=row.conversation_id)
        row=TenantFlowDelivery.objects.select_for_update().get(pk=pk);row.conversation=conversation
        if row.status!='queued' or row.next_attempt_at and row.next_attempt_at>timezone.now():return
        flow=ChatbotFlow.objects.filter(tenant=conversation.tenant,enabled=True).first()
        if not flow or not available(conversation.tenant) or conversation.appointment_id or conversation.status in {'human','closed'} or conversation.flow_revision!=flow.updated_at.isoformat():
            row.status='cancelled';row.save(update_fields=['status']);return
        if TenantFlowDelivery.objects.filter(conversation=conversation,pk__lt=row.pk,status__in=['queued','sending','failed']).exists():return
        row.attempts+=1
        if row.transport=='cloud':
            # Cloud API has no equivalent idempotent send key. Persist the attempt
            # before calling it; ambiguous failures are handed to an operator.
            from django.conf import settings
            if conversation.tenant.metadata.get('whatsapp_phone_number_id')!=settings.WHATSAPP_PHONE_NUMBER_ID:
                row.status='cancelled';row.save(update_fields=['status']);return
            row.status='sending';row.next_attempt_at=timezone.now();row.save(update_fields=['status','attempts','next_attempt_at']);cloud=(conversation.wa_id,row.body)
        else:
            try:
                if not TenantWhatsAppConnection.objects.filter(tenant=conversation.tenant,enabled=True).exists():raise ValueError('WhatsApp desconectado.')
                from .tenant_whatsapp import gateway
                sent=gateway(conversation.tenant,'POST','send',{'to':conversation.context.get('_chatbot_jid') or conversation.wa_id,'text':row.body,'idempotencyKey':row.event_key})
                _record(row,sent['id'])
            except Exception as exc:
                row.last_error='Falha de entrega ('+type(exc).__name__+').'
                row.status='failed' if row.attempts>=5 else 'queued'
                row.next_attempt_at=timezone.now()+timedelta(seconds=min(600,30*2**row.attempts))
                conversation.flow_last_error='Não foi possível entregar uma resposta automática. Confira a conexão do WhatsApp.'
                conversation.save(update_fields=['flow_last_error','updated_at'])
            row.save(update_fields=['status','attempts','last_error','next_attempt_at','sent_at'])
    if cloud:
        from .whatsapp import send_text
        try:provider=send_text(*cloud)
        except Exception:provider=''
        with transaction.atomic():
            row=TenantFlowDelivery.objects.select_for_update(of=("self",)).select_related('conversation__tenant').get(pk=pk)
            if provider:_record(row,provider)
            else:
                row.status='failed';row.last_error='Entrega Cloud API não confirmada. Confira a conversa antes de reenviar.'
                WhatsAppConversation.objects.filter(pk=row.conversation_id).update(flow_last_error=row.last_error)
            row.save(update_fields=['status','last_error','sent_at'])


def reconcile():
    now=timezone.now()
    for pk in WhatsAppConversation.objects.filter(flow_wake_at__lte=now,status='bot',tenant__chatbot_flow__enabled=True).values_list('pk',flat=True)[:100]:advance(pk,resume=True)
    pending=WhatsAppMessage.objects.filter(direction='in',flow_processed_at__isnull=True,created_at__gte=now-timedelta(hours=2),tenant__chatbot_flow__enabled=True,conversation__status='bot',conversation__appointment__isnull=True).filter(created_at__gte=F('tenant__chatbot_flow__updated_at')).order_by('pk')
    for pk in pending.values_list('pk',flat=True)[:100]:enqueue(pk)
    for pk in TenantFlowDelivery.objects.filter(status='queued').filter(Q(next_attempt_at__isnull=True)|Q(next_attempt_at__lte=now)).values_list('pk',flat=True)[:100]:dispatch(pk)
    # A worker may stop after a Cloud API attempt. Never blindly resend it.
    TenantFlowDelivery.objects.filter(status='sending',next_attempt_at__lt=now-timedelta(minutes=10)).update(status='failed',last_error='Entrega incerta. Confira a conversa antes de reenviar.')
