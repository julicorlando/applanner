"""Consent-based vacancy offers with a real, expiring agenda hold."""

import hashlib
import secrets
from datetime import timedelta
from zoneinfo import ZoneInfo
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from core.crypto import encrypt_text, decrypt_text
from scheduling.models import Appointment, Professional
from scheduling.availability import AvailabilityService
from engagement.models import WaitlistEntry
from .models import BeautySettings, RecoveryOffer


@transaction.atomic
def expire_offers(tenant=None):
    rows = RecoveryOffer.objects.filter(status="held", expires_at__lte=timezone.now())
    if tenant:
        rows = rows.filter(tenant=tenant)
    for offer in rows.select_for_update().select_related("appointment"):
        if offer.appointment.status == "pending":
            offer.appointment.status = "cancelled"
            offer.appointment.save(update_fields=["status", "updated_at"])
        offer.status = "expired"
        offer.save(update_fields=["status", "updated_at"])


@transaction.atomic
def offer_vacancy(cancelled_id):
    original = Appointment.objects.select_related(
        "tenant", "professional", "service"
    ).get(pk=cancelled_id)
    tenant = original.tenant
    if not BeautySettings.objects.filter(tenant=tenant, recovery_enabled=True).exists():
        return None
    from communications.tenant_flow import available
    from communications.models import TenantWhatsAppConnection

    if not TenantWhatsAppConnection.objects.filter(
        tenant=tenant, enabled=True
    ).exists():
        return None
    if not AvailabilityService().settings(tenant).allow_pay_on_site:
        return None
    if (
        not available(tenant)
        or original.status != "cancelled"
        or not original.professional_id
        or original.starts_at <= timezone.now() + timedelta(minutes=15)
    ):
        return None
    from billing.segment_access import require_feature
    from django.core.exceptions import PermissionDenied

    try:
        require_feature(tenant, "waitlist")
    except PermissionDenied:
        return None
    from tenants.models import Unit

    if original.unit_id:
        Unit.objects.select_for_update().get(pk=original.unit_id, tenant=tenant)
    pro = Professional.objects.select_for_update().get(
        pk=original.professional_id, tenant=tenant, active=True
    )
    expire_offers(tenant)
    existing = (
        RecoveryOffer.objects.filter(cancelled_appointment=original)
        .exclude(status__in=["expired", "cancelled"])
        .first()
    )
    if existing:
        return existing
    # Do not send repeated offers to the same customer for the same cancellation.
    entries = (
        WaitlistEntry.objects.filter(
            tenant=tenant,
            status="waiting",
            appointment__isnull=True,
            service__active=True,
            customer__active=True,
            customer__consent_marketing=True,
        )
        .exclude(
            pk__in=RecoveryOffer.objects.filter(cancelled_appointment=original).values(
                "entry_id"
            )
        )
        .select_related("service", "customer")
    )
    local = original.starts_at.astimezone(ZoneInfo(tenant.timezone or "America/Recife"))
    for entry in entries.order_by("created_at", "pk"):
        if entry.unit_id not in (
            None,
            original.unit_id,
        ) or entry.service.unit_id not in (None, original.unit_id):
            continue
        if (
            entry.professional_id not in (None, pro.pk)
            or entry.preferred_date
            and entry.preferred_date != local.date()
        ):
            continue
        period = (
            "morning"
            if local.hour < 12
            else "afternoon"
            if local.hour < 18
            else "evening"
        )
        if entry.period not in ("any", period):
            continue
        end = original.starts_at + timedelta(minutes=entry.service.duration_minutes)
        engine = AvailabilityService()
        if end > original.ends_at or not engine.professional_offers(
            tenant, pro.pk, entry.service_id
        ):
            continue
        if not engine.is_available(
            tenant, pro, original.starts_at, end, service=entry.service
        ):
            continue
        from engagement.contacting import contact_blocked

        if contact_blocked(tenant, entry.customer):
            continue
        token = secrets.token_urlsafe(32)
        hold = Appointment.objects.create(
            tenant=tenant,
            unit=original.unit,
            customer=entry.customer,
            professional=pro,
            service=entry.service,
            starts_at=original.starts_at,
            ends_at=end,
            service_price_snapshot=entry.service.price,
            status="pending",
            source="whatsapp",
            notes="Reserva temporária de recuperação de agenda; aguarda aceite.",
        )
        offer = RecoveryOffer.objects.create(
            tenant=tenant,
            cancelled_appointment=original,
            appointment=hold,
            entry=entry,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            token_encrypted=encrypt_text(token),
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        return offer
    return None


def deliver_offer(offer_id):
    from communications.tenant_whatsapp import gateway
    from communications.models import (
        TenantWhatsAppConnection,
        WhatsAppConversation,
        WhatsAppMessage,
    )
    from communications.phone import whatsapp_number
    from engagement.contacting import reserve_contact_window, release_contact_window

    with transaction.atomic():
        offer = (
            RecoveryOffer.objects.select_for_update()
            .select_related(
                "tenant",
                "appointment__customer",
                "appointment__service",
                "appointment__professional",
                "entry__customer",
            )
            .get(pk=offer_id)
        )
        if (
            offer.status != "held"
            or offer.sent_at
            or offer.expires_at <= timezone.now()
        ):
            return
        customer = offer.entry.customer
        if (
            not customer.consent_marketing
            or not TenantWhatsAppConnection.objects.filter(
                tenant=offer.tenant, enabled=True
            ).exists()
        ):
            return
        reservation = reserve_contact_window(
            offer.tenant, customer, None, "vacancy_offer"
        )
        if not reservation:
            return
        local = timezone.localtime(
            offer.appointment.starts_at,
            ZoneInfo(offer.tenant.timezone or "America/Recife"),
        )
        url = settings.PUBLIC_BASE_URL.rstrip("/") + reverse(
            "beauty-recovery-accept", args=[decrypt_text(offer.token_encrypted)]
        )
        text = (
            f"Olá, {customer.name.split()[0]}! Surgiu uma vaga em {offer.tenant.name}: "
            f"{offer.appointment.service.name}, {local:%d/%m às %H:%M}, com {offer.appointment.professional.name}. "
            f"Valor: R$ {offer.appointment.service_price_snapshot:.2f}. Reservamos por 10 minutos. "
            f"Confira e confirme se quiser: {url}. Se não desejar receber convites, responda SAIR."
        )
        try:
            sent = gateway(
                offer.tenant,
                "POST",
                "send",
                {
                    "to": whatsapp_number(customer.phone),
                    "text": text,
                    "idempotencyKey": f"beauty-offer-{offer.pk}",
                },
            )
        except Exception:
            release_contact_window(reservation)
            raise
        conversation, _ = WhatsAppConversation.objects.get_or_create(
            tenant=offer.tenant,
            wa_id=whatsapp_number(customer.phone),
            defaults={
                "customer": customer,
                "contact_name": customer.name,
                "last_message_at": timezone.now(),
            },
        )
        WhatsAppMessage.objects.get_or_create(
            provider_message_id=sent["id"],
            defaults={
                "tenant": offer.tenant,
                "conversation": conversation,
                "direction": "out",
                "sender_type": "system",
                "body": text,
                "status": "sent",
                "sent_at": timezone.now(),
            },
        )
        offer.sent_at = timezone.now()
        offer.save(update_fields=["sent_at", "updated_at"])


@transaction.atomic
def accept_offer(token):
    offer = (
        RecoveryOffer.objects.select_for_update()
        .select_related("appointment", "entry")
        .get(token_hash=hashlib.sha256(token.encode()).hexdigest())
    )
    if offer.status == "accepted":
        return offer
    if offer.status != "held" or offer.expires_at <= timezone.now():
        raise ValidationError(
            "Esta reserva expirou. Consulte a agenda para encontrar outra vaga."
        )
    entry = WaitlistEntry.objects.select_for_update().get(
        pk=offer.entry_id, tenant=offer.tenant
    )
    appointment = Appointment.objects.select_for_update().get(
        pk=offer.appointment_id, tenant=offer.tenant
    )
    if (
        appointment.status != "pending"
        or entry.appointment_id
        or entry.status not in ["waiting", "matched"]
    ):
        raise ValidationError("Esta reserva não está mais disponível.")
    from communications.tenant_flow import available

    if (
        not available(offer.tenant)
        or not appointment.service.active
        or not appointment.professional.active
    ):
        raise ValidationError(
            "A empresa precisa confirmar a disponibilidade deste atendimento."
        )
    if not AvailabilityService().is_available(
        offer.tenant,
        appointment.professional,
        appointment.starts_at,
        appointment.ends_at,
        exclude_appointment_id=appointment.pk,
        public_rules=False,
        service=appointment.service,
    ):
        raise ValidationError(
            "A disponibilidade mudou. Nossa equipe precisa confirmar outra vaga."
        )
    appointment.status = "confirmed"
    appointment.customer_confirmed_at = timezone.now()
    appointment.save(update_fields=["status", "customer_confirmed_at", "updated_at"])
    entry.status = "booked"
    entry.appointment = appointment
    entry.save(update_fields=["status", "appointment", "updated_at"])
    offer.status = "accepted"
    offer.save(update_fields=["status", "updated_at"])
    return offer
