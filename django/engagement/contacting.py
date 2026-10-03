from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from billing.entitlements import active_subscription,module_enabled
from communications.models import (
    TenantWhatsAppConnection,WhatsAppConversation,WhatsAppMessage,
)
from communications.tenant_whatsapp import gateway,whatsapp_number
from .models import CustomerContactThrottle


CONTACT_WINDOW=timedelta(hours=24)


def contact_blocked(tenant,customer,*,now=None):
    now=now or timezone.now()
    row=CustomerContactThrottle.objects.filter(tenant=tenant,customer=customer).first()
    return bool(row and row.last_contact_at>now-CONTACT_WINDOW)


@transaction.atomic
def reserve_contact_window(tenant,customer,user,reason):
    now=timezone.now()
    row,_=CustomerContactThrottle.objects.get_or_create(
        tenant=tenant,customer=customer,
        defaults={
            "last_contact_at":now-CONTACT_WINDOW-timedelta(minutes=1),
            "reason":"",
        },
    )
    row=CustomerContactThrottle.objects.select_for_update().get(pk=row.pk)
    if row.last_contact_at>now-CONTACT_WINDOW:
        return None
    # Reserve the window before external delivery to prevent concurrent panels
    # from sending twice. If delivery fails, release it below.
    previous=row.last_contact_at
    row.last_contact_at=now
    row.reason=reason[:40]
    row.sent_by=user
    row.save(update_fields=["last_contact_at","reason","sent_by","updated_at"])
    return row,previous


def release_contact_window(reservation):
    if not reservation:
        return
    row,previous=reservation
    CustomerContactThrottle.objects.filter(pk=row.pk,last_contact_at=row.last_contact_at).update(
        last_contact_at=previous,reason="",sent_by=None,updated_at=timezone.now()
    )


def _booking_url(tenant,professional=None):
    base=settings.PUBLIC_BASE_URL.rstrip("/")
    slug=tenant.public_slug or tenant.slug
    if professional and professional.public_slug:
        return f"{base}/p/{slug}/profissional/{professional.public_slug}/#agendar"
    return f"{base}/p/{slug}/#agendar"


def send_return_invitation(*,tenant,customer,user,professional=None):
    number=whatsapp_number(customer.phone)
    if not 10<=len(number)<=15:
        raise ValueError("O cliente não possui telefone válido para WhatsApp.")
    if active_subscription(tenant) and not module_enabled(tenant,"whatsapp"):
        raise ValueError("O módulo WhatsApp não está liberado.")
    if not TenantWhatsAppConnection.objects.filter(tenant=tenant,enabled=True).exists():
        raise ValueError("Conecte o WhatsApp da empresa antes de enviar.")

    reservation=reserve_contact_window(tenant,customer,user,"return_invite")
    if not reservation:
        raise ValueError("Este cliente já recebeu uma mensagem nas últimas 24 horas.")

    first=(customer.name or "cliente").split()[0]
    link=_booking_url(tenant,professional)
    body=(
        f"Olá, {first}! Já faz um tempo desde seu último atendimento em {tenant.name}. "
        f"Quer agendar novamente? Escolha um horário por aqui: {link}"
    )
    try:
        sent=gateway(tenant,"POST","send",{"to":number,"text":body})
    except Exception:
        release_contact_window(reservation)
        raise

    conversation,_=WhatsAppConversation.objects.get_or_create(
        tenant=tenant,wa_id=number,
        defaults={
            "customer":customer,"contact_name":customer.name,
            "last_message_at":timezone.now(),
        },
    )
    conversation.customer=customer
    conversation.status=WhatsAppConversation.Status.BOT
    conversation.last_message_at=timezone.now()
    conversation.save(update_fields=["customer","status","last_message_at","updated_at"])
    WhatsAppMessage.objects.create(
        conversation=conversation,tenant=tenant,provider_message_id=sent["id"],
        direction=WhatsAppMessage.Direction.OUT,
        sender_type=WhatsAppMessage.SenderType.USER,user=user,
        message_type="text",body=body,status=WhatsAppMessage.Status.SENT,
        sent_at=timezone.now(),
    )
    return conversation
