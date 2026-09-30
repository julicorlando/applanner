"""Tenant-scoped QR gateway, appointment templates and authenticated callbacks."""
import hmac
import json
import logging
import re

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.signing import dumps
from django.db import transaction
from django.http import HttpResponse,JsonResponse
from django.shortcuts import redirect,render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from billing.entitlements import active_subscription,module_enabled
from scheduling.models import Appointment,Customer
from tenants.models import Tenant
from .models import Notification,TenantWhatsAppConnection,WhatsAppConversation,WhatsAppMessage
from .phone import whatsapp_number

logger=logging.getLogger(__name__)


def _management(request):
    if not request.user.is_superuser and (not request.user.tenant_id or request.user.role not in {
        "owner","manager","tenant-admin","barber-manager","arena-manager","auto-manager",
    }):
        raise PermissionDenied("Somente a gestão da empresa pode conectar o WhatsApp.")
    if request.user.is_superuser:
        selected=request.session.get("portal_tenant_id")
        return Tenant.objects.filter(pk=selected).first() if selected else None
    return request.user.tenant


def gateway(tenant,method,path,payload=None):
    token=settings.MASTER_WHATSAPP_GATEWAY_TOKEN
    address=settings.TENANT_WHATSAPP_GATEWAY_URL
    if not token or not address:
        raise ValueError("Configure MASTER_WHATSAPP_GATEWAY_TOKEN para ativar o WhatsApp da empresa.")
    try:
        response=requests.request(method,f"{address.rstrip('/')}/tenant/{tenant.pk}/{path}",
            headers={"Authorization":"Bearer "+token},json=payload,timeout=15)
        data=response.json()
    except (requests.RequestException,ValueError) as exc:
        raise ValueError("O serviço de WhatsApp da empresa está indisponível.") from exc
    if not response.ok:
        if response.status_code==403:
            raise ValueError("O gateway recusou a autenticação (403). Confira o mesmo MASTER_WHATSAPP_GATEWAY_TOKEN nos serviços web e tenant-whatsapp e faça o redeploy.")
        raise ValueError(data.get("error") or "Não foi possível concluir a ação no WhatsApp.")
    return data


@login_required
def tenant_whatsapp_settings(request):
    tenant=_management(request)
    if tenant is None:
        messages.info(request,"Selecione uma empresa no painel antes de configurar o WhatsApp.")
        return redirect("portal-home")
    available=not active_subscription(tenant) or module_enabled(tenant,"whatsapp")
    if request.method=="POST" and request.POST.get("action")=="grant" and request.user.is_superuser:
        from billing.models import Module,TenantModule
        module=Module.objects.filter(slug="whatsapp",active=True).first()
        if not module:
            messages.error(request,"O módulo WhatsApp ainda está inativo no catálogo. Execute seed_modules após o deploy.")
        else:
            TenantModule.objects.update_or_create(tenant=tenant,module=module,defaults={"enabled":True})
            messages.success(request,f"WhatsApp liberado para {tenant.name}. Agora você pode conectar o QR.")
        return redirect("tenant-whatsapp-settings")
    if request.method=="POST" and not available:
        messages.error(request,"O WhatsApp ainda não foi incluído no plano desta empresa. O Master pode liberá-lo aqui.")
        return redirect("tenant-whatsapp-settings")
    connection,_=TenantWhatsAppConnection.objects.get_or_create(tenant=tenant)
    if request.method=="POST":
        action=request.POST.get("action")
        if action in {"connect","disconnect"}:
            try:
                gateway(tenant,"POST",action)
                connection.enabled=action=="connect"
                connection.save(update_fields=["enabled","updated_at"])
                messages.success(request,"Conexão iniciada. Escaneie o QR com o WhatsApp da empresa." if connection.enabled else "WhatsApp da empresa desconectado.")
            except ValueError as exc:
                messages.error(request,str(exc))
        return redirect("tenant-whatsapp-settings")
    try:
        state=gateway(tenant,"GET","status") if connection.enabled and available else {"state":"disconnected"}
    except ValueError as exc:
        state={"state":"error","callbackError":str(exc)}
    return render(request,"communications/tenant_whatsapp_settings.html",{
        "tenant":tenant,"state":state,"connection":connection,"available":available,
    })


def appointment_text(appointment,kind):
    name=appointment.customer.name.split()[0]
    local=timezone.localtime(appointment.starts_at)
    if kind=="confirmation":
        return f"Olá, {name}, recebemos o seu agendamento em {appointment.tenant.name} para {local:%d/%m às %H:%M}. Estamos esperando você!"
    if kind=="reminder":
        link=""
        if appointment.customer_manage_token_encrypted:
            from core.crypto import decrypt_text
            token=decrypt_text(appointment.customer_manage_token_encrypted)
            link=f" Para reagendar ou cancelar: {settings.PUBLIC_BASE_URL.rstrip('/')}{reverse('public-appointment-page',args=[token])}"
        return f"Olá, {name}, lembramos do seu agendamento em {appointment.tenant.name} para {local:%d/%m às %H:%M}.{link} Até breve!"
    if kind=="feedback":
        token=dumps({"appointment":appointment.pk},salt="appointment-rating")
        url=settings.PUBLIC_BASE_URL.rstrip("/")+reverse("public-appointment-rating",args=[token])
        return f"Olá, {name}, obrigado pela visita a {appointment.tenant.name}. Como foi seu atendimento? Dê uma nota de 1 a 5: {url}"
    raise ValueError("Mensagem pronta inválida.")


def queue_appointment_whatsapp(appointment,kind):
    number=whatsapp_number(appointment.customer.phone)
    if (not 10<=len(number)<=15 or (active_subscription(appointment.tenant) and not module_enabled(appointment.tenant,"whatsapp"))
            or not TenantWhatsAppConnection.objects.filter(tenant=appointment.tenant,enabled=True).exists()):
        return None
    notification=Notification.objects.create(tenant=appointment.tenant,customer=appointment.customer,
        channel=Notification.Channel.WHATSAPP,template_key=f"appointment_{kind}",destination=number,
        payload={"appointment_id":appointment.pk,"kind":kind,"text":appointment_text(appointment,kind)})
    if kind=="confirmation":
        def deliver():
            from .tasks import send_notification
            try:
                send_notification.delay(notification.pk)
            except Exception:
                logger.exception("Não foi possível despachar a confirmação WhatsApp %s; a fila periódica tentará novamente.",notification.pk)
        transaction.on_commit(deliver)
    return notification


@transaction.atomic
def send_prepared_message(appointment,kind,user):
    appointment=Appointment.objects.select_for_update().select_related("customer","tenant").get(pk=appointment.pk)
    if appointment.status not in {Appointment.Status.PENDING,Appointment.Status.CONFIRMED,
                                  Appointment.Status.WAITING,Appointment.Status.IN_PROGRESS}:
        raise ValueError("Este atendimento já foi encerrado.")
    number=whatsapp_number(appointment.customer.phone)
    if not 10<=len(number)<=15:
        raise ValueError("O cliente não possui telefone com DDD e código do país.")
    if active_subscription(appointment.tenant) and not module_enabled(appointment.tenant,"whatsapp"):
        raise ValueError("O módulo WhatsApp não está liberado para esta empresa.")
    if not TenantWhatsAppConnection.objects.filter(tenant=appointment.tenant,enabled=True).exists():
        raise ValueError("Conecte o WhatsApp da empresa antes de enviar.")
    body=appointment_text(appointment,kind)
    conversation,_=WhatsAppConversation.objects.get_or_create(tenant=appointment.tenant,wa_id=number,
        defaults={"customer":appointment.customer,"contact_name":appointment.customer.name,
                  "last_message_at":timezone.now()})
    if conversation.context.get("cancel_requested_appointment_id")==appointment.pk:
        raise ValueError("O cliente pediu cancelamento. Resolva o pedido antes de enviar outra mensagem.")
    sent=gateway(appointment.tenant,"POST","send",{"to":number,"text":body})
    conversation.appointment=appointment
    conversation.customer=appointment.customer
    conversation.status=WhatsAppConversation.Status.BOT
    conversation.last_message_at=timezone.now()
    conversation.save(update_fields=["appointment","customer","status","last_message_at","updated_at"])
    WhatsAppMessage.objects.create(conversation=conversation,tenant=appointment.tenant,
        provider_message_id=sent["id"],direction=WhatsAppMessage.Direction.OUT,
        sender_type=WhatsAppMessage.SenderType.USER,user=user,message_type="text",body=body,
        status=WhatsAppMessage.Status.SENT,sent_at=timezone.now())
    return conversation


@transaction.atomic
def send_appointment_notification(notification):
    appointment=Appointment.objects.select_for_update().select_related("customer","tenant").get(
        pk=notification.payload["appointment_id"],tenant=notification.tenant)
    kind=notification.payload["kind"]
    active=appointment.status in {Appointment.Status.CONFIRMED,Appointment.Status.WAITING,Appointment.Status.IN_PROGRESS}
    if kind not in {"confirmation","reminder","feedback"} or (kind=="feedback" and appointment.status!=Appointment.Status.COMPLETED) or (kind!="feedback" and not active):
        notification.status=Notification.Status.SKIPPED
        notification.save(update_fields=["status"])
        return ""
    number=whatsapp_number(appointment.customer.phone)
    if (notification.destination!=number or (active_subscription(appointment.tenant) and not module_enabled(appointment.tenant,"whatsapp"))
            or not TenantWhatsAppConnection.objects.filter(tenant=appointment.tenant,enabled=True).exists()):
        notification.status=Notification.Status.SKIPPED
        notification.save(update_fields=["status"])
        return ""
    body=appointment_text(appointment,kind)
    sent=gateway(appointment.tenant,"POST","send",{"to":number,"text":body})
    conversation,_=WhatsAppConversation.objects.get_or_create(tenant=appointment.tenant,wa_id=number,
        defaults={"customer":appointment.customer,"contact_name":appointment.customer.name,
                  "last_message_at":timezone.now()})
    conversation.customer=appointment.customer
    conversation.appointment=appointment
    conversation.status=WhatsAppConversation.Status.CLOSED if kind=="feedback" else WhatsAppConversation.Status.BOT
    conversation.last_message_at=timezone.now()
    conversation.save(update_fields=["customer","appointment","status","last_message_at","updated_at"])
    WhatsAppMessage.objects.create(conversation=conversation,tenant=appointment.tenant,
        provider_message_id=sent["id"],direction=WhatsAppMessage.Direction.OUT,
        sender_type=WhatsAppMessage.SenderType.SYSTEM,message_type="text",body=body,
        status=WhatsAppMessage.Status.SENT,sent_at=timezone.now())
    return sent["id"]


def mark_inbound_appointment(conversation,body):
    appointment=conversation.appointment
    if not appointment:
        return False
    if appointment.status in {Appointment.Status.CANCELLED,Appointment.Status.COMPLETED,Appointment.Status.NO_SHOW}:
        conversation.status=WhatsAppConversation.Status.CLOSED
    elif re.search(r"\bcancelar\b",body,re.I):
        conversation.context={**conversation.context,"cancel_requested_appointment_id":appointment.pk}
        conversation.status=WhatsAppConversation.Status.WAITING_HUMAN
    conversation.last_message_at=timezone.now()
    conversation.save(update_fields=["status","context","last_message_at","updated_at"])
    return True


@csrf_exempt
@require_POST
def tenant_whatsapp_receive(request):
    expected=settings.MASTER_WHATSAPP_GATEWAY_TOKEN
    if not expected or not hmac.compare_digest(request.headers.get("Authorization",""),"Bearer "+expected):
        return HttpResponse(status=403)
    if len(request.body)>16384:
        return HttpResponse(status=413)
    try:
        data=json.loads(request.body)
        tenant=Tenant.objects.get(pk=int(data["tenant_id"]))
        jid=str(data.get("from") if data.get("event")!="receipt" else data.get("to"))
        if not re.fullmatch(r"[0-9]{10,20}@(s\.whatsapp\.net|lid)",jid):
            raise ValueError
        msg_id=str(data["id"])
        if not 1<=len(msg_id)<=190:
            raise ValueError
    except (json.JSONDecodeError,KeyError,TypeError,ValueError,Tenant.DoesNotExist):
        return JsonResponse({"error":"Evento inválido."},status=400)
    number=jid.split("@")[0]
    if data.get("event")=="receipt":
        status=data.get("status")
        if status not in {"read","delivered"}:
            return JsonResponse({"error":"Recibo inválido."},status=400)
        WhatsAppMessage.objects.filter(tenant=tenant,provider_message_id=msg_id,
            conversation__wa_id=number,direction=WhatsAppMessage.Direction.OUT).exclude(
            status=WhatsAppMessage.Status.READ).update(status=WhatsAppMessage.Status.READ if status=="read" else WhatsAppMessage.Status.DELIVERED)
        return JsonResponse({"ok":True})
    body=str(data.get("text") or "")[:4096]
    customer=next((candidate for candidate in Customer.objects.filter(
        tenant=tenant,phone__endswith=number[-4:]).only("id","phone").iterator()
        if whatsapp_number(candidate.phone)==number),None)
    conversation,_=WhatsAppConversation.objects.get_or_create(tenant=tenant,wa_id=number,
        defaults={"customer":customer,"contact_name":str(data.get("name") or "")[:150],"last_message_at":timezone.now()})
    _,created=WhatsAppMessage.objects.get_or_create(provider_message_id=msg_id,
        defaults={"conversation":conversation,"tenant":tenant,"direction":WhatsAppMessage.Direction.IN,
                  "sender_type":WhatsAppMessage.SenderType.CUSTOMER,"body":body,
                  "status":WhatsAppMessage.Status.RECEIVED})
    if created:
        if not mark_inbound_appointment(conversation,body):
            conversation.last_message_at=timezone.now()
            conversation.save(update_fields=["last_message_at","updated_at"])
    return JsonResponse({"ok":True})
