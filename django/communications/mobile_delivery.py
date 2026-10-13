import base64, hashlib, json, re
from urllib.parse import urlsplit
from datetime import timedelta
from zoneinfo import ZoneInfo
import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac
from celery import shared_task
from core.crypto import decrypt_json, encrypt_text, decrypt_text
from .models import Notification
from .mobile_models import (
    DeliveryProviderSettings,
    TenantDeliverySettings,
    CustomerDeliveryConsent,
    PushSubscription,
    PushDelivery,
    SMSDispatch,
)
from .phone import whatsapp_number


TRUSTED_PUSH_HOSTS = {
    "fcm.googleapis.com",
    "updates.push.services.mozilla.com",
    "web.push.apple.com",
}


def validate_subscription(data):
    try:
        endpoint = data["endpoint"]
        url = urlsplit(endpoint)
        if (
            len(endpoint) > 4096
            or url.scheme != "https"
            or url.username
            or url.password
            or url.fragment
            or url.port not in (None, 443)
            or not (
                url.hostname in TRUSTED_PUSH_HOSTS
                or (url.hostname or "").endswith(".notify.windows.com")
            )
        ):
            raise ValueError
        keys = data["keys"]
        for key, size in [("auth", 16), ("p256dh", 65)]:
            raw = str(keys[key])
            if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}={0,2}", raw):
                raise ValueError
            decoded = base64.urlsafe_b64decode(raw + "=" * ((4 - len(raw) % 4) % 4))
            if len(decoded) != size:
                raise ValueError
        if (
            base64.urlsafe_b64decode(
                str(keys["p256dh"]) + "=" * ((4 - len(str(keys["p256dh"])) % 4) % 4)
            )[0]
            != 4
        ):
            raise ValueError
        from cryptography.hazmat.primitives.asymmetric import ec

        ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(),
            base64.urlsafe_b64decode(
                str(keys["p256dh"]) + "=" * ((4 - len(str(keys["p256dh"])) % 4) % 4)
            ),
        )
        return {
            "endpoint": endpoint,
            "keys": {"auth": keys["auth"], "p256dh": keys["p256dh"]},
        }
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValidationError(
            "Inscrição de notificações inválida ou provedor não permitido."
        ) from None


def phone_digest(customer):
    return salted_hmac(
        "customer-sms-consent",
        f"{customer.tenant_id}:{customer.pk}:{whatsapp_number(customer.phone)}",
        algorithm="sha256",
    ).hexdigest()


def initialize_vapid(config):
    if config.vapid_private_encrypted:
        return
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    key = ec.generate_private_key(ec.SECP256R1())
    config.vapid_private_encrypted = encrypt_text(
        base64.urlsafe_b64encode(
            key.private_bytes(
                serialization.Encoding.DER,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        .decode()
        .rstrip("=")
    )
    config.vapid_public_key = (
        base64.urlsafe_b64encode(
            key.public_key().public_bytes(
                serialization.Encoding.X962,
                serialization.PublicFormat.UncompressedPoint,
            )
        )
        .decode()
        .rstrip("=")
    )


def queue_push(subscription, key, payload):
    digest = hashlib.sha256(key.encode()).hexdigest()
    row, created = PushDelivery.objects.get_or_create(
        subscription=subscription, key=digest, defaults={"payload": payload}
    )
    if created:
        transaction.on_commit(lambda: send_push.delay(row.pk))
    return row


class NoRedirectSession(requests.Session):
    def post(self, url, *args, **kwargs):
        parsed = urlsplit(url)
        if not (
            parsed.hostname in TRUSTED_PUSH_HOSTS
            or (parsed.hostname or "").endswith(".notify.windows.com")
        ):
            raise ValidationError("Destino Push não permitido.")
        kwargs["allow_redirects"] = False
        return super().post(url, *args, **kwargs)


@shared_task
def send_push(pk):
    with transaction.atomic():
        row = (
            PushDelivery.objects.select_for_update()
            .select_related("subscription")
            .filter(pk=pk)
            .first()
        )
        if not row or row.status != "queued":
            return
        config = DeliveryProviderSettings.objects.filter(
            pk=1, push_enabled=True
        ).first()
        if (
            not config
            or not config.vapid_private_encrypted
            or not row.subscription.active
            or row.created_at < timezone.now() - timedelta(days=1)
        ):
            row.status = "expired"
            row.save(update_fields=["status", "updated_at"])
            return
        row.attempts += 1
        try:
            from pywebpush import webpush

            info = validate_subscription(
                decrypt_json(row.subscription.payload_encrypted)
            )
            response = webpush(
                subscription_info=info,
                data=json.dumps(row.payload),
                vapid_private_key=decrypt_text(config.vapid_private_encrypted),
                vapid_claims={"sub": "mailto:" + config.contact_email},
                ttl=3600,
                timeout=10,
                requests_session=NoRedirectSession(),
            )
            if not 200 <= response.status_code < 300:
                raise ValueError
        except Exception as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            if code in (404, 410):
                row.subscription.active = False
                row.subscription.save(update_fields=["active", "updated_at"])
                row.status = "expired"
            elif row.attempts >= 3:
                row.status = "failed"
            # Queue sweep retries eligible failures, without surfacing endpoint or payload in logs.
        else:
            row.status = "sent"
            row.sent_at = timezone.now()
        row.save(update_fields=["status", "attempts", "sent_at", "updated_at"])


@shared_task
def process_push_queue():
    ids = list(
        PushDelivery.objects.filter(status="queued", attempts__lt=3)
        .order_by("created_at")
        .values_list("pk", flat=True)[:100]
    )
    for pk in ids:
        send_push.delay(pk)
    return len(ids)


def customer_sms_allowed(customer):
    config = DeliveryProviderSettings.objects.filter(pk=1, sms_enabled=True).first()
    local = TenantDeliverySettings.objects.filter(
        tenant=customer.tenant, sms_enabled=True, sms_monthly_limit__gt=0
    ).first()
    consent = CustomerDeliveryConsent.objects.filter(
        tenant=customer.tenant,
        customer=customer,
        sms_consent_at__isnull=False,
        phone_digest=phone_digest(customer),
    ).first()
    return config and local and consent


@transaction.atomic
def queue_sms(appointment, event):
    customer = appointment.customer
    if not customer_sms_allowed(customer):
        return None
    local = TenantDeliverySettings.objects.select_for_update().get(
        tenant=appointment.tenant
    )
    day = timezone.now().astimezone(
        ZoneInfo(appointment.tenant.timezone or "America/Recife")
    )
    first = day.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if (
        SMSDispatch.objects.filter(
            tenant=appointment.tenant, created_at__gte=first
        ).count()
        >= local.sms_monthly_limit
    ):
        return None
    key = hashlib.sha256(
        f"{appointment.pk}:{event}:{appointment.starts_at.isoformat()}".encode()
    ).hexdigest()
    dispatch, created = SMSDispatch.objects.get_or_create(
        tenant=appointment.tenant, key=key
    )
    if not created:
        return None
    url = (
        settings.PUBLIC_BASE_URL.rstrip("/")
        + f"/p/{appointment.tenant.public_slug or appointment.tenant.slug}/cliente/"
    )
    notice = Notification.objects.create(
        tenant=appointment.tenant,
        customer=customer,
        channel="sms",
        template_key="booking_sms",
        destination="+" + whatsapp_number(customer.phone),
        payload={
            "text": f"ApPlanner: sua reserva foi atualizada. Consulte seus horarios: {url}",
            "appointment_id": appointment.pk,
        },
    )
    dispatch.notification = notice
    dispatch.save(update_fields=["notification", "updated_at"])
    from .tasks import send_notification

    transaction.on_commit(lambda: send_notification.delay(notice.pk))
    return notice


def send_sms(notification):
    dispatch = (
        SMSDispatch.objects.select_for_update()
        .filter(notification=notification)
        .first()
    )
    if (
        not dispatch
        or not notification.customer_id
        or not customer_sms_allowed(notification.customer)
    ):
        notification.status = "skipped"
        return ""
    if dispatch.state != "queued":
        notification.status = "failed"
        return ""
    config = DeliveryProviderSettings.objects.get(pk=1)
    if (
        not re.fullmatch(r"AC[a-fA-F0-9]{32}", config.twilio_account_sid)
        or not re.fullmatch(r"\+[1-9]\d{9,14}", config.sms_from)
        or not re.fullmatch(r"\+[1-9]\d{9,14}", notification.destination)
    ):
        notification.status = "failed"
        dispatch.state = "failed"
        dispatch.save(update_fields=["state", "updated_at"])
        return ""
    # An uncertain SMS response is never automatically submitted again (avoids duplicated charges).
    dispatch.state = "sending"
    dispatch.save(update_fields=["state", "updated_at"])
    try:
        response = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{config.twilio_account_sid}/Messages.json",
            auth=(
                config.twilio_account_sid,
                decrypt_text(config.twilio_token_encrypted),
            ),
            data={
                "To": notification.destination,
                "From": config.sms_from,
                "Body": str(notification.payload.get("text", ""))[:1000],
            },
            timeout=15,
            allow_redirects=False,
        )
        if not 200 <= response.status_code < 300:
            raise ValueError
        sid = response.json().get("sid", "")
        if not re.fullmatch(r"SM[a-fA-F0-9]{32}", sid):
            raise ValueError
    except Exception:
        dispatch.state = "unknown"
        notification.status = "failed"
        notification.error_message = "Resposta do SMS indeterminada. Confira o provedor antes de qualquer reenvio."
        dispatch.save(update_fields=["state", "updated_at"])
        return ""
    dispatch.state = "accepted"
    dispatch.save(update_fields=["state", "updated_at"])
    return sid


@transaction.atomic
def appointment_event(appointment):
    event = f"appointment:{appointment.pk}:{appointment.status}:{appointment.professional_id}:{appointment.starts_at.isoformat()}"
    key = hashlib.sha256(event.encode()).hexdigest()
    qs = PushSubscription.objects.filter(active=True, tenant=appointment.tenant)
    from django.db.models import Q

    match = Q(customer=appointment.customer)
    if appointment.professional_id and appointment.professional.user_id:
        match |= Q(user_id=appointment.professional.user_id)
    for sub in qs.filter(match):
        url = (
            "/app/profissional/"
            if sub.user_id
            else f"/p/{appointment.tenant.public_slug or appointment.tenant.slug}/cliente/"
        )
        queue_push(
            sub,
            key,
            {
                "title": "ApPlanner",
                "body": "Sua agenda foi atualizada. Abra o aplicativo para conferir.",
                "url": url,
                "tag": key,
            },
        )
    if appointment.status in {"confirmed", "cancelled"}:
        queue_sms(appointment, appointment.status)


@shared_task
def reconcile_sms_delivery():
    config = DeliveryProviderSettings.objects.filter(pk=1, sms_enabled=True).first()
    if not config:
        return 0
    rows = SMSDispatch.objects.filter(
        state="accepted",
        notification__delivered_at__isnull=True,
        created_at__gte=timezone.now() - timedelta(days=7),
    ).select_related("notification")[:100]
    count = 0
    for row in rows:
        sid = row.notification.provider_reference
        if not re.fullmatch(r"SM[a-fA-F0-9]{32}", sid):
            continue
        try:
            response = requests.get(
                f"https://api.twilio.com/2010-04-01/Accounts/{config.twilio_account_sid}/Messages/{sid}.json",
                auth=(
                    config.twilio_account_sid,
                    decrypt_text(config.twilio_token_encrypted),
                ),
                timeout=10,
                allow_redirects=False,
            )
            if response.status_code != 200:
                continue
            data = response.json()
            if data.get("sid") != sid:
                continue
            if data.get("status") == "delivered":
                Notification.objects.filter(pk=row.notification_id).update(
                    delivered_at=timezone.now()
                )
                row.state = "delivered"
            elif data.get("status") in {"failed", "undelivered"}:
                Notification.objects.filter(pk=row.notification_id).update(
                    status="failed",
                    error_message="O provedor informou falha na entrega do SMS.",
                )
                row.state = "failed"
            else:
                continue
            row.save(update_fields=["state", "updated_at"])
            count += 1
        except Exception:
            continue
    return count
