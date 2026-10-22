"""Separate outbox: never uses tenant subscriptions or changes platform billing."""

from datetime import timedelta
from zoneinfo import ZoneInfo
from celery import shared_task
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from core.crypto import decrypt_json, decrypt_text
from communications.master_whatsapp import _gateway, record_outbound_message
from communications.models import MasterWhatsAppConversation, MasterWhatsAppMessage
from .models import Client, Charge, Delivery
from .services import queue_reminder


@shared_task
def process_development_billing():
    now = timezone.now()
    local = now.astimezone(ZoneInfo("America/Recife"))
    # Abandoned SMTP sends cannot safely be repeated automatically.
    interrupted = Delivery.objects.filter(
        status="sending", updated_at__lt=now - timedelta(minutes=10)
    )
    interrupted.filter(channel="email").update(
        status="uncertain", error_code="worker_interrupted"
    )
    interrupted.filter(channel="whatsapp").update(
        status="failed", error_code="worker_interrupted", next_attempt_at=now
    )
    if 9 <= local.hour < 18:
        for pk in (
            Charge.objects.filter(
                status="open", client__active=True, client__reminders_enabled=True
            )
            .values_list("pk", flat=True)
            .iterator(chunk_size=200)
        ):
            queue_reminder(pk, local.date())
    ids = list(
        Delivery.objects.filter(
            status__in=["pending", "failed"], attempts__lt=5, next_attempt_at__lte=now
        )
        .order_by("pk")
        .values_list("pk", flat=True)[:100]
    )
    for pk in ids:
        deliver(pk)
    Delivery.objects.filter(
        invitation__expires_at__lte=now, status__in=["pending", "failed"]
    ).update(status="cancelled", payload_encrypted="")
    return len(ids)


def deliver(pk):
    # Commit the claim before network I/O. A killed worker leaves a visible
    # sending row instead of rolling back to pending and repeating SMTP.
    with transaction.atomic():
        row = Delivery.objects.select_for_update().get(pk=pk)
        if (
            row.status not in {"pending", "failed"}
            or row.next_attempt_at > timezone.now()
            or row.attempts >= 5
        ):
            return
        row.attempts += 1
        row.status = "sending"
        row.save(update_fields=["attempts", "status", "updated_at"])
    try:
        _deliver_claimed(pk)
    except Exception:
        # No exception text, recipient, password link or bank credential in logs.
        row = Delivery.objects.get(pk=pk)
        row.status = "uncertain" if row.channel == "email" else "failed"
        row.error_code = (
            "check_smtp_delivery" if row.channel == "email" else "check_master_whatsapp"
        )
        row.next_attempt_at = timezone.now() + timedelta(
            minutes=min(60, 5 * row.attempts)
        )
        row.save(
            update_fields=["status", "error_code", "next_attempt_at", "updated_at"]
        )


@transaction.atomic
def _deliver_claimed(pk):
    client_id = Delivery.objects.values_list("client_id", flat=True).get(pk=pk)
    client = Client.objects.select_for_update().select_related("user").get(pk=client_id)
    row = Delivery.objects.select_for_update().get(pk=pk)
    if row.status != "sending":
        return
    now = timezone.now()
    charge = (
        Charge.objects.select_for_update().get(pk=row.charge_id)
        if row.charge_id
        else None
    )
    local = now.astimezone(ZoneInfo("America/Recife"))
    stale = (
        not client.active or not client.user.is_active or bool(client.user.deleted_at)
    )
    if row.invitation_id:
        from .models import Invitation

        invitation = Invitation.objects.get(pk=row.invitation_id)
        stale = (
            stale
            or bool(invitation.used_at)
            or invitation.expires_at <= now
            or client.user.has_usable_password()
        )
    if charge:
        stale = (
            stale
            or charge.status != "open"
            or not client.reminders_enabled
            or row.charge_revision != charge.revision
            or row.scheduled_date != local.date()
        )
    if stale:
        row.status, row.payload_encrypted = "cancelled", ""
        row.save(update_fields=["status", "payload_encrypted", "updated_at"])
        return
    if charge and not 9 <= local.hour < 18:
        row.status = "pending"
        row.save(update_fields=["status", "updated_at"])
        return
    data = decrypt_json(row.payload_encrypted)
    if row.channel == "email":
        if (
            send_mail(
                data["subject"],
                data["text"],
                None,
                [client.user.email],
                fail_silently=False,
            )
            != 1
        ):
            raise RuntimeError("email_not_sent")
    else:
        conversation, _ = MasterWhatsAppConversation.objects.get_or_create(
            wa_id=client.phone + "@s.whatsapp.net",
            defaults={"contact_name": client.name[:150], "last_message_at": now},
        )
        payload = {
            "to": conversation.wa_id,
            "text": data["text"],
            "idempotencyKey": row.key,
        }
        if charge and charge.boleto_encrypted:
            payload["file"] = {
                "base64": decrypt_text(charge.boleto_encrypted),
                "mime": "application/pdf",
                "name": f"boleto-{charge.pk}.pdf",
            }
        sent = _gateway("POST", "/send", payload)
        if not MasterWhatsAppMessage.objects.filter(
            provider_message_id=sent["id"]
        ).exists():
            record_outbound_message(
                conversation=conversation, sent=sent, body=data["text"], sent_by=None
            )
        conversation.last_message_at = now
        conversation.save(update_fields=["last_message_at", "updated_at"])
    row.status, row.sent_at, row.error_code, row.payload_encrypted = "sent", now, "", ""
    row.save(
        update_fields=[
            "status",
            "sent_at",
            "error_code",
            "payload_encrypted",
            "next_attempt_at",
            "updated_at",
        ]
    )
