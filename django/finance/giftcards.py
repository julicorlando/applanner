import hashlib, secrets
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from core.audit import append_audit
from .advanced_services import positive
from .models import GiftCard, GiftCardEntry


def code_hash(code):
    return hashlib.sha256(
        str(code).replace("-", "").replace(" ", "").upper().encode()
    ).hexdigest()


def actor(tenant, user):
    from accounts.permissions import has_capability

    if not user.is_superuser and (
        user.tenant_id != tenant.pk
        or user.role == "professional"
        or not (
            has_capability(user, "finance.manage")
            or has_capability(user, "barber.manage")
        )
    ):
        raise PermissionDenied


@transaction.atomic
def issue(*, tenant, user, amount, method, key, expires=None, unit=None):
    actor(tenant, user)
    if unit and unit.tenant_id != tenant.pk:
        raise PermissionDenied
    if user.role == "reception":
        raise PermissionDenied
    amount = positive(amount).quantize(Decimal(".01"))
    if (
        amount <= 0
        or method not in {"cash", "pix", "card", "transfer"}
        or not key
        or len(key) > 100
    ):
        raise ValidationError("Valor, pagamento ou identificador inválido.")
    if expires and expires < timezone.localdate():
        raise ValidationError("A validade não pode estar no passado.")
    from tenants.models import Tenant

    Tenant.objects.select_for_update().get(pk=tenant.pk)
    prior = GiftCard.objects.filter(tenant=tenant, issue_key=key).first()
    if prior:
        if (
            prior.issued_amount != amount
            or prior.issue_payment_method != method
            or prior.expires_on != expires
            or prior.unit_id != getattr(unit, "pk", None)
        ):
            raise ValidationError("Identificador já usado em outra emissão.")
        return prior, None
    code = secrets.token_hex(12).upper()
    card = GiftCard.objects.create(
        tenant=tenant,
        unit=unit,
        code_hash=code_hash(code),
        last4=code[-4:],
        issued_amount=amount,
        balance=amount,
        issued_by=user,
        issue_key=key,
        issue_payment_method=method,
        expires_on=expires,
    )
    GiftCardEntry.objects.create(
        tenant=tenant,
        card=card,
        kind="issue",
        amount=amount,
        balance_after=amount,
        user=user,
        key=key,
    )
    append_audit(
        tenant=tenant,
        user=user,
        action="GIFT_CARD_ISSUED",
        entity_type="GiftCard",
        entity_id=card.pk,
        after={"amount": amount, "method": method, "last4": card.last4},
    )
    return card, code


@transaction.atomic
def redeem(*, tenant, user, code, command, key, amount):
    actor(tenant, user)
    from barber.models import BarberCommand

    command = BarberCommand.objects.select_for_update().get(
        pk=command.pk, tenant=tenant
    )
    amount = positive(amount).quantize(Decimal(".01"))
    if amount <= 0 or not key or len(key) > 100:
        raise ValidationError("Valor ou identificador inválido.")
    card = (
        GiftCard.objects.select_for_update()
        .filter(tenant=tenant, code_hash=code_hash(code))
        .first()
    )
    if not card:
        raise ValidationError("Vale-presente não encontrado.")
    prior = GiftCardEntry.objects.filter(tenant=tenant, key=key).first()
    if prior:
        if (
            prior.card_id != card.pk
            or prior.amount != amount
            or prior.command_id != command.pk
            or prior.kind != "redeem"
        ):
            raise ValidationError("Identificador já usado em outra operação.")
        return prior
    if (
        not card.active
        or (card.expires_on and card.expires_on < timezone.localdate())
        or card.balance < amount
    ):
        raise ValidationError(
            "Vale-presente vencido, desativado ou com saldo insuficiente."
        )
    if command.status != "open":
        raise ValidationError("A comanda precisa estar aberta.")
    from barber.models import BarberCommandPayment
    from django.db.models import Sum

    paid = command.payments.filter(voided_at__isnull=True).aggregate(v=Sum("amount"))[
        "v"
    ] or Decimal(0)
    if amount > max(command.total_amount - paid, Decimal(0)):
        raise ValidationError("O uso do vale supera o saldo a pagar da comanda.")
    payment = BarberCommandPayment.objects.create(
        command=command,
        tenant=tenant,
        user=user,
        method="gift_card",
        amount=amount,
        received_at=timezone.now(),
    )
    card.balance -= amount
    card.save(update_fields=["balance", "updated_at"])
    entry = GiftCardEntry.objects.create(
        tenant=tenant,
        card=card,
        command=command,
        payment=payment,
        kind="redeem",
        amount=amount,
        balance_after=card.balance,
        user=user,
        key=key,
    )
    append_audit(
        tenant=tenant,
        user=user,
        action="GIFT_CARD_REDEEMED",
        entity_type="GiftCardEntry",
        entity_id=entry.pk,
        after={"amount": amount, "command": command.pk, "balance": card.balance},
    )
    return entry


@transaction.atomic
def reverse(*, tenant, user, entry_id, key):
    actor(tenant, user)
    if user.role == "reception":
        raise PermissionDenied
    entry = GiftCardEntry.objects.select_related("command").get(
        pk=entry_id, tenant=tenant, kind="redeem"
    )
    from barber.models import BarberCommand

    command = BarberCommand.objects.select_for_update().get(
        pk=entry.command_id, tenant=tenant
    )
    card = GiftCard.objects.select_for_update().get(pk=entry.card_id, tenant=tenant)
    prior = GiftCardEntry.objects.filter(reversed_entry=entry).first()
    if prior:
        return prior
    if command.status != "open":
        raise ValidationError(
            "Reabra ou estorne a comanda pelo processo autorizado antes de devolver o saldo."
        )
    if not key or len(key) > 100:
        raise ValidationError("Identificador inválido.")
    card.balance += entry.amount
    card.save(update_fields=["balance", "updated_at"])
    if entry.payment_id:
        payment = entry.payment
        payment.voided_at = timezone.now()
        payment.save(update_fields=["voided_at"])
    row = GiftCardEntry.objects.create(
        tenant=tenant,
        card=card,
        command=command,
        kind="reversal",
        amount=entry.amount,
        balance_after=card.balance,
        user=user,
        key=key,
        reversed_entry=entry,
    )
    append_audit(
        tenant=tenant,
        user=user,
        action="GIFT_CARD_REVERSED",
        entity_type="GiftCardEntry",
        entity_id=row.pk,
        after={"original": entry.pk, "amount": entry.amount},
    )
    return row
