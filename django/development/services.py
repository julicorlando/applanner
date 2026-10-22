import base64
import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlsplit
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from core.audit import append_audit
from core.crypto import encrypt_json, encrypt_text
from .models import Client, Charge, Delivery, Invitation


def public_url(route, *args):
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    if not base.startswith("https://") or not urlsplit(base).netloc:
        raise ValidationError(
            "Configure PUBLIC_BASE_URL com o domínio HTTPS da plataforma antes de cadastrar clientes."
        )
    return base + reverse(route, args=args)


def audit(request, action, row):
    append_audit(
        user=request.user,
        request=request,
        action="development." + action,
        entity_type=row._meta.label,
        entity_id=row.pk,
        after={"status": getattr(row, "status", None)},
    )


@transaction.atomic
def invite(client):
    client = Client.objects.select_for_update().select_related("user").get(pk=client.pk)
    if not client.active or not client.user.is_active or client.user.deleted_at:
        raise ValidationError("Ative o cliente para enviar o convite.")
    if client.user.has_usable_password():
        raise ValidationError(
            "O cliente já definiu sua senha. Ele pode usar Esqueci minha senha no login."
        )
    if client.invitations.filter(
        used_at__isnull=True, created_at__gt=timezone.now() - timedelta(minutes=1)
    ).exists():
        raise ValidationError(
            "Um convite acabou de ser criado. Aguarde um minuto para reenviar."
        )
    raw = secrets.token_urlsafe(32)
    url = public_url("development-activate", raw)
    client.invitations.filter(used_at__isnull=True).update(used_at=timezone.now())
    client.deliveries.filter(
        invitation__isnull=False, status__in=["pending", "failed"]
    ).update(status="cancelled", payload_encrypted="")
    token = Invitation.objects.create(
        client=client,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=timezone.now() + timedelta(hours=24),
    )
    text = f"Olá, {client.name}! Seu acesso aos pagamentos de desenvolvimento está pronto. Crie sua senha em até 24 horas: {url}\nDepois, entre pelo login do ApPlanner."
    payload = encrypt_json(
        {"text": text, "subject": "Crie sua senha · pagamentos de desenvolvimento"}
    )
    for channel in ("email", "whatsapp"):
        Delivery.objects.create(
            client=client,
            invitation=token,
            channel=channel,
            key=f"dev-invite-{token.pk}-{channel}",
            payload_encrypted=payload,
        )
    return token


@transaction.atomic
def save_client(form, request):
    client = form.save(commit=False)
    creating = not client.pk
    if creating:
        client.user = get_user_model().objects.create_user(
            email=form.cleaned_data["email"],
            password=None,
            role="development-client",
            first_name=client.name[:150],
        )
    else:
        # Serialize changes with invitation and delivery operations.
        Client.objects.select_for_update().get(pk=client.pk)
        previous_phone = Client.objects.values_list("phone", flat=True).get(
            pk=client.pk
        )
        if previous_phone != client.phone:
            client.deliveries.filter(status__in=["pending", "failed"]).update(
                status="cancelled", payload_encrypted=""
            )
    client.save()
    audit(request, "client-created" if creating else "client-updated", client)
    if creating:
        invite(client)
    elif not client.active:
        client.deliveries.filter(status__in=["pending", "failed"]).update(
            status="cancelled", payload_encrypted=""
        )
    return client


@transaction.atomic
def save_charge(form, client, request):
    client = Client.objects.select_for_update().get(pk=client.pk)
    charge = form.save(commit=False)
    if not charge.pk:
        previous = Charge.objects.filter(
            creation_key=form.cleaned_data["creation_key"]
        ).first()
        if previous:
            if previous.client_id != client.pk:
                raise ValidationError(
                    "Confirmação de cobrança inválida. Reabra o formulário."
                )
            return previous
        charge.creation_key = form.cleaned_data["creation_key"]
    if charge.pk:
        old = Charge.objects.select_for_update().get(pk=charge.pk, client=client)
        if old.status != "open":
            raise ValidationError("Cobranças pagas/canceladas não podem ser alteradas.")
        charge.revision = old.revision + 1
        Delivery.objects.filter(charge=charge, status__in=["pending", "failed"]).update(
            status="cancelled", payload_encrypted=""
        )
    charge.client = client
    source = form.cleaned_data.get("boleto_pdf")
    if source:
        charge.boleto_encrypted = encrypt_text(base64.b64encode(source.read()).decode())
    charge.save()
    audit(request, "charge-saved", charge)
    return charge


@transaction.atomic
def settle(charge_id, status, note, request):
    # Same order as the sender: client before charge.
    client_id = Charge.objects.values_list("client_id", flat=True).get(pk=charge_id)
    Client.objects.select_for_update().get(pk=client_id)
    row = Charge.objects.select_for_update().get(pk=charge_id)
    if row.status != "open" or status not in {"paid", "cancelled"}:
        raise ValidationError("Esta cobrança não está em aberto.")
    row.status = status
    row.paid_at = timezone.now() if status == "paid" else None
    row.settlement_note = note
    row.save(update_fields=["status", "paid_at", "settlement_note", "updated_at"])
    Delivery.objects.filter(charge=row, status__in=["pending", "failed"]).update(
        status="cancelled", payload_encrypted=""
    )
    audit(request, "charge-" + status, row)
    return row


def reminder_stage(due_date, today):
    days = (due_date - today).days
    if days in {10, 5, 0}:
        return f"before{days}"
    if days <= -2 and days % 2 == 0:
        return f"overdue{-days}"
    return None


@transaction.atomic
def queue_reminder(charge_id, today):
    client_id = Charge.objects.values_list("client_id", flat=True).get(pk=charge_id)
    client = Client.objects.select_for_update().select_related("user").get(pk=client_id)
    charge = Charge.objects.select_for_update().get(pk=charge_id)
    stage = reminder_stage(charge.due_date, today)
    if (
        not stage
        or charge.status != "open"
        or not client.active
        or not client.reminders_enabled
        or not client.user.is_active
        or client.user.deleted_at
    ):
        return None
    from .forms import validate_template

    validate_template(client.message_template)
    url = public_url("development-charge", charge.pk)
    text = client.message_template.format(
        nome=client.name,
        descricao=charge.description,
        valor=f"{charge.amount:.2f}".replace(".", ","),
        vencimento=charge.due_date.strftime("%d/%m/%Y"),
        link=url,
    )
    row, _ = Delivery.objects.get_or_create(
        key=f"dev-charge-{charge.pk}-r{charge.revision}-{stage}",
        defaults={
            "client": client,
            "charge": charge,
            "charge_revision": charge.revision,
            "scheduled_date": today,
            "channel": "whatsapp",
            "payload_encrypted": encrypt_json({"text": text}),
        },
    )
    return row
