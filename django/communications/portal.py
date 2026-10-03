from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone

from accounts.permissions import require_any_capability
from billing.segment_access import require_feature
from tenants.models import Tenant
from .models import UserNotification,WhatsAppConversation,WhatsAppMessage
from .whatsapp import WhatsAppProviderError,send_text
from .tenant_whatsapp import send_prepared_message
from scheduling.models import Appointment


def _tenant(request):
    if request.user.tenant_id:
        if request.resolver_match.url_name in {"communications-inbox","communications-conversation","communications-conversation-action"}:
            require_feature(request.user.tenant,"whatsapp")
        return request.user.tenant
    if request.user.is_superuser:
        tid=request.session.get("portal_tenant_id")
        if tid:
            return Tenant.objects.filter(pk=tid).first()
    raise PermissionDenied("Selecione uma empresa.")


@login_required
def inbox(request):
    require_any_capability(request.user,"communications.manage")
    tenant=_tenant(request)
    rows=(
        WhatsAppConversation.objects.filter(tenant=tenant)
        .select_related("customer","assigned_to")
        .order_by("-last_message_at")[:300]
    )
    return render(request,"communications/inbox.html",{"tenant":tenant,"rows":rows})


@login_required
def conversation(request,pk):
    require_any_capability(request.user,"communications.manage")
    tenant=_tenant(request)
    row=get_object_or_404(
        WhatsAppConversation.objects.select_related("customer","assigned_to"),
        pk=pk,tenant=tenant,
    )
    thread=row.messages.select_related("user").order_by("id")[:1000]
    return render(request,"communications/conversation.html",{
        "tenant":tenant,"conversation":row,"thread":thread,
        "appointment":row.appointment,
        "can_message":bool(row.appointment_id and row.appointment.status in {
            Appointment.Status.PENDING,Appointment.Status.CONFIRMED,Appointment.Status.WAITING,Appointment.Status.IN_PROGRESS,
        }),
        "cancel_requested":row.appointment_id and row.context.get("cancel_requested_appointment_id")==row.appointment_id,
    })


@login_required
def conversation_action(request,pk):
    require_any_capability(request.user,"communications.manage")
    if request.method!="POST":
        raise PermissionDenied
    tenant=_tenant(request)
    row=get_object_or_404(WhatsAppConversation.objects.select_related("appointment","customer"),pk=pk,tenant=tenant)
    action=request.POST.get("action","")
    if action=="cancel_appointment":
        with transaction.atomic():
            row=WhatsAppConversation.objects.select_for_update().get(pk=row.pk,tenant=tenant)
            appointment=Appointment.objects.select_for_update().filter(pk=row.appointment_id,tenant=tenant).first()
            if not appointment or row.context.get("cancel_requested_appointment_id")!=appointment.pk or appointment.status not in {
                Appointment.Status.PENDING,Appointment.Status.CONFIRMED,Appointment.Status.WAITING,
            }:
                messages.error(request,"Este horário não pode mais ser liberado.")
            else:
                appointment.status=Appointment.Status.CANCELLED
                appointment.save(update_fields=["status","updated_at"])
                row.status=WhatsAppConversation.Status.CLOSED
                row.context={key:value for key,value in row.context.items() if key!="cancel_requested_appointment_id"}
                row.save(update_fields=["status","context","updated_at"])
                messages.success(request,"Agendamento cancelado e horário liberado. Atendimento WhatsApp encerrado.")
        return redirect("communications-conversation",pk=row.pk)
    if row.appointment_id and action in {"reply","bot","human"}:
        messages.error(request,"Esta conversa de agendamento aceita apenas mensagens prontas; após o encerramento não há novos envios.")
        return redirect("communications-conversation",pk=row.pk)
    if action=="prepared":
        appointment=row.appointment
        if not appointment or row.context.get("cancel_requested_appointment_id")==appointment.pk:
            messages.error(request,"Este atendimento não aceita novas mensagens.")
        else:
            try:
                send_prepared_message(appointment,request.POST.get("kind",""),request.user)
                messages.success(request,"Mensagem pronta enviada.")
            except (ValueError,KeyError) as exc:
                messages.error(request,str(exc))
        return redirect("communications-conversation",pk=row.pk)
    if action=="reply":
        body=(request.POST.get("body") or "").strip()
        if not body:
            messages.error(request,"Digite uma mensagem.")
        else:
            try:
                provider_id=send_text(row.wa_id,body)
                WhatsAppMessage.objects.create(
                    conversation=row,tenant=tenant,provider_message_id=provider_id or None,
                    direction=WhatsAppMessage.Direction.OUT,
                    sender_type=WhatsAppMessage.SenderType.USER,user=request.user,
                    message_type="text",body=body,status=WhatsAppMessage.Status.SENT,
                    sent_at=timezone.now(),
                )
                row.status=WhatsAppConversation.Status.HUMAN
                row.assigned_to=request.user
                row.last_message_at=timezone.now()
                row.save(update_fields=["status","assigned_to","last_message_at","updated_at"])
                messages.success(request,"Mensagem enviada.")
            except WhatsAppProviderError as exc:
                messages.error(request,str(exc))
    elif action in {"bot","human","close"}:
        if action=="bot":
            row.status=WhatsAppConversation.Status.BOT
            row.assigned_to=None
        elif action=="human":
            row.status=WhatsAppConversation.Status.HUMAN
            row.assigned_to=request.user
        else:
            row.status=WhatsAppConversation.Status.CLOSED
        row.save(update_fields=["status","assigned_to","updated_at"])
        messages.success(request,"Conversa atualizada.")
    else:
        messages.error(request,"Ação inválida.")
    return redirect("communications-conversation",pk=row.pk)


@login_required
def notifications(request):
    require_any_capability(request.user,"communications.manage","support.manage","agenda.manage")
    tenant=_tenant(request)
    qs=UserNotification.objects.filter(user=request.user)
    qs=qs.filter(tenant__in=[tenant,None])
    if request.method=="POST":
        qs.filter(read_at__isnull=True).update(read_at=timezone.now())
        messages.success(request,"Notificações marcadas como lidas.")
        return redirect("communications-notifications")
    return render(request,"communications/notifications.html",{
        "tenant":tenant,"rows":qs.order_by("-created_at")[:300],
    })
