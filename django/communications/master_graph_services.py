import logging
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.db.models import Q
from core.crypto import decrypt_json,encrypt_json
from .models import MasterWhatsAppFlow,MasterWhatsAppConversation,MasterWhatsAppMessage,MasterFlowDelivery
from .master_runtime import run_graph

logger=logging.getLogger(__name__)


def dispatch_delivery(pk):
    from .tasks import deliver_master_flow_message
    try:deliver_master_flow_message.delay(pk)
    except Exception:logger.warning('Master flow delivery awaits queue reconciliation: %s',pk)


@transaction.atomic
def advance_graph(conversation_id,message_id=None,resume=False):
    conversation=MasterWhatsAppConversation.objects.select_for_update().get(pk=conversation_id)
    flow=MasterWhatsAppFlow.objects.filter(pk=1,enabled=True).first()
    incoming=MasterWhatsAppMessage.objects.filter(pk=message_id,conversation=conversation,direction='in').first() if message_id else None
    if not flow or not flow.graph or conversation.human_handoff or (message_id and (not incoming or incoming.flow_processed_at)):return
    if resume and (not conversation.flow_wake_at or conversation.flow_wake_at>timezone.now()):return
    revision=flow.updated_at.isoformat()
    if resume and conversation.flow_revision!=revision:
        conversation.flow_wake_at=None;conversation.flow_last_error='O fluxo foi alterado durante a espera. Reinicie o atendimento.'
        conversation.human_handoff=True;conversation.save(update_fields=['flow_wake_at','flow_last_error','human_handoff']);return
    state=conversation.flow_state;waiting=conversation.flow_wait_kind
    context=decrypt_json(conversation.flow_context_encrypted) if conversation.flow_context_encrypted else {}
    if state=='__finished__' or conversation.flow_revision!=revision:
        state=flow.graph['start'];context={};waiting=''
    variables=context.setdefault('variables',{})
    variables['contact_name']=conversation.contact_name;variables['contact_phone']=conversation.wa_id.split('@')[0]
    event_key=f'in-{incoming.pk}' if incoming else f'wake-{conversation.pk}-{int(conversation.flow_wake_at.timestamp())}'
    body=incoming.body if incoming else ''
    if any(term in body.casefold() for term in ('atendimento','humano','atendente')):
        result={'state':state,'context':context,'waiting':'','messages':[flow.handoff],'handoff':True,'wake_seconds':None,'error':''}
    else:result=run_graph(flow.graph,flow,state,context,waiting,body,resume=resume,event_key=event_key)
    # Messages persist before any delivery. Broker outages are recovered by beat.
    for index,text in enumerate(result['messages']):
        delivery,_=MasterFlowDelivery.objects.get_or_create(event_key=f'{event_key}-{index}',defaults={'conversation':conversation,'body':text[:4096]})
        transaction.on_commit(lambda pk=delivery.pk:dispatch_delivery(pk))
    conversation.flow_state=result['state'];conversation.flow_wait_kind=result['waiting']
    conversation.flow_context_encrypted=encrypt_json(result['context']);conversation.flow_revision=revision
    if result['waiting']=='wait' and not result['wake_seconds']:
        pass # Incoming messages during an existing wait do not reset its deadline.
    else:conversation.flow_wake_at=timezone.now()+timedelta(seconds=result['wake_seconds']) if result['wake_seconds'] else None
    conversation.human_handoff=result['handoff'];conversation.flow_last_error=result['error']
    conversation.save(update_fields=['flow_state','flow_wait_kind','flow_context_encrypted','flow_revision','flow_wake_at','human_handoff','flow_last_error'])
    if incoming:incoming.flow_processed_at=timezone.now();incoming.save(update_fields=['flow_processed_at'])


@transaction.atomic
def deliver(pk):
    row=MasterFlowDelivery.objects.select_related('conversation').filter(pk=pk).first()
    if not row:return
    # Same lock order as the runner and manual handoff.
    conversation=MasterWhatsAppConversation.objects.select_for_update().get(pk=row.conversation_id)
    row=MasterFlowDelivery.objects.select_for_update().get(pk=pk)
    if row.status!='queued' or row.next_attempt_at and row.next_attempt_at>timezone.now():return
    flow=MasterWhatsAppFlow.objects.filter(pk=1,enabled=True).first()
    if not flow or not flow.graph or conversation.flow_revision!=flow.updated_at.isoformat():
        row.status='cancelled';row.save(update_fields=['status']);return
    if MasterFlowDelivery.objects.filter(conversation=conversation,pk__lt=row.pk,status__in=['queued','failed']).exists():return
    row.attempts+=1
    try:
        from .master_whatsapp import _gateway,record_outbound_message
        sent=_gateway('POST','/send',{'to':conversation.wa_id,'text':row.body,'idempotencyKey':row.event_key})
        if not MasterWhatsAppMessage.objects.filter(provider_message_id=sent['id']).exists():
            record_outbound_message(conversation=conversation,sent=sent,body=row.body,sent_by=None)
        row.status='sent';row.sent_at=timezone.now();row.last_error=''
        conversation.last_message_at=timezone.now();conversation.save(update_fields=['last_message_at'])
    except Exception as exc:
        row.last_error='Falha de entrega ('+type(exc).__name__+').'
        row.status='failed' if row.attempts>=5 else 'queued'
        row.next_attempt_at=timezone.now()+timedelta(seconds=min(600,30*2**row.attempts))
    row.save(update_fields=['attempts','status','sent_at','last_error','next_attempt_at'])


def reconcile():
    if not MasterWhatsAppFlow.objects.filter(pk=1,enabled=True).exclude(graph={}).exists():return 0
    now=timezone.now()
    for pk in MasterWhatsAppConversation.objects.filter(flow_wake_at__lte=now,human_handoff=False).values_list('pk',flat=True)[:100]:advance_graph(pk,resume=True)
    ids=list(MasterFlowDelivery.objects.filter(status='queued').filter(Q(next_attempt_at__isnull=True)|Q(next_attempt_at__lte=now)).values_list('pk',flat=True)[:100])
    for pk in ids:dispatch_delivery(pk)
    return len(ids)
