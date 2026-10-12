from decimal import Decimal, InvalidOperation

from core.audit import append_audit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .models import (
    CashMovement,
    CashSession,
    FinancialTransaction,
    MaterialConsumption,
    Product,
    ProductStockMovement,
)


def positive(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0:
            raise ValueError
        return amount
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("Informe um valor positivo válido.") from None


def cash_balance(session):
    end = timezone.now()
    rows = FinancialTransaction.objects.filter(
        tenant=session.tenant,
        unit=session.unit,
        status="paid",
        paid_at__gte=session.opened_at,
        paid_at__lte=end,
        payment_method__in=["cash", "dinheiro"],
    ).exclude(source_type="barber_command")
    income = rows.filter(type="income").aggregate(v=Sum("amount"))["v"] or Decimal(0)
    # A paid online deposit is not cash. Only the remainder settled in cash enters the drawer.
    from billing.models import TenantPaymentTransaction

    mixed = FinancialTransaction.objects.filter(
        tenant=session.tenant,
        unit=session.unit,
        status="paid",
        type="income",
        paid_at__gte=session.opened_at,
        paid_at__lte=end,
        payment_method__in=["pix+cash", "pix+dinheiro"],
    ).exclude(source_type="barber_command")
    for row in mixed:
        online = TenantPaymentTransaction.objects.filter(
            tenant=session.tenant,
            reference_type="appointment",
            reference_id=row.appointment_id,
            status="paid",
        ).aggregate(v=Sum("gross_amount"))["v"] or Decimal(0)
        income += max(row.amount - online, Decimal(0))

    expense = rows.filter(type="expense").aggregate(v=Sum("amount"))["v"] or Decimal(0)
    from barber.models import BarberCommandPayment

    payments = BarberCommandPayment.objects.filter(
        tenant=session.tenant,
        command__status="closed",
        received_at__gte=session.opened_at,
        received_at__lte=end,
        method__in=["cash", "dinheiro"],
    )
    if session.unit_id:
        payments = payments.filter(
            Q(command__appointment__unit=session.unit)
            | Q(
                command__appointment__isnull=True,
                command__professional__unit=session.unit,
            )
        )
    else:
        payments = payments.filter(
            command__appointment__unit__isnull=True,
            command__professional__unit__isnull=True,
        )
    command_cash = payments.aggregate(v=Sum("amount"))["v"] or Decimal(0)
    supply = session.movements.filter(type="supply").aggregate(v=Sum("amount"))[
        "v"
    ] or Decimal(0)
    withdrawal = session.movements.filter(type="withdrawal").aggregate(v=Sum("amount"))[
        "v"
    ] or Decimal(0)
    return (
        session.opening_amount + income + command_cash - expense + supply - withdrawal
    ).quantize(Decimal(".01"))


@transaction.atomic
def move_cash(*, session, user, kind, amount, reason, key):
    session = CashSession.objects.select_for_update().get(pk=session.pk)
    if not user.is_superuser and (
        user.tenant_id != session.tenant_id
        or user.role in {"professional", "reception"}
    ):
        raise PermissionDenied
    if (
        not key
        or len(key) > 100
        or not str(reason).strip()
        or len(str(reason).strip()) > 300
        or kind not in CashMovement.Type.values
    ):
        raise ValidationError("Informe o tipo, motivo e identificador do movimento.")
    amount = positive(amount).quantize(Decimal(".01"))
    if amount <= 0:
        raise ValidationError("Valor mínimo: R$ 0,01.")
    existing = CashMovement.objects.filter(
        tenant=session.tenant, idempotency_key=key
    ).first()
    if existing:
        if (
            existing.session_id != session.pk
            or existing.type != kind
            or existing.amount != amount
            or existing.reason != reason.strip()
        ):
            raise ValidationError("Identificador já usado em outro movimento.")
        return existing
    if session.status != "open":
        raise ValidationError("O caixa está fechado.")
    if kind == "withdrawal" and amount > cash_balance(session):
        raise ValidationError("A sangria excede o saldo disponível em dinheiro.")
    row = CashMovement.objects.create(
        tenant=session.tenant,
        session=session,
        user=user,
        type=kind,
        amount=amount,
        reason=reason.strip()[:300],
        idempotency_key=key,
    )
    append_audit(
        tenant=session.tenant,
        user=user,
        action="CASH_MOVEMENT",
        entity_type="CashMovement",
        entity_id=row.pk,
        after={"type": kind, "amount": amount, "session": session.pk},
    )
    return row


@transaction.atomic
def consume_material(
    *, tenant, product_id, quantity, user, key, appointment=None, note=""
):
    if not key or len(key) > 100:
        raise ValidationError("Identificador do consumo inválido.")
    quantity = positive(quantity)
    if quantity != quantity.quantize(Decimal(".001")):
        raise ValidationError("Use até três casas decimais na quantidade.")
    if user.role == "professional" and appointment is None:
        raise PermissionDenied
    if not user.is_superuser and user.tenant_id != tenant.pk:
        raise PermissionDenied
    if appointment and appointment.tenant_id != tenant.pk:
        raise ValidationError("Insumo ou atendimento pertence a outra unidade/empresa.")
    if (
        appointment
        and user.role == "professional"
        and (
            not appointment.professional_id
            or appointment.professional.user_id != user.pk
        )
    ):
        raise PermissionDenied
    try:
        product = Product.objects.select_for_update().get(
            pk=product_id, tenant=tenant, active=True, kind="internal"
        )
    except Product.DoesNotExist:
        raise ValidationError(
            "Insumo indisponível. Revise a ficha de consumo."
        ) from None
    if appointment and product.unit_id not in (None, appointment.unit_id):
        raise ValidationError("Insumo pertence a outra unidade.")
    existing = MaterialConsumption.objects.filter(
        tenant=tenant, idempotency_key=key
    ).first()
    if existing:
        if (
            existing.product_id != product.pk
            or existing.quantity != quantity
            or existing.appointment_id != getattr(appointment, "pk", None)
        ):
            raise ValidationError("Identificador já usado em outro consumo.")
        return existing
    if product.stock < quantity:
        raise ValidationError(f"Estoque insuficiente de {product.name}.")
    product.stock -= quantity
    product.save(update_fields=["stock", "updated_at"])
    row = MaterialConsumption.objects.create(
        tenant=tenant,
        appointment=appointment,
        product=product,
        quantity=quantity,
        cost_snapshot=(quantity * product.cost_price).quantize(Decimal(".01")),
        user=user,
        idempotency_key=key,
        note=note[:300],
    )
    ProductStockMovement.objects.create(
        tenant=tenant,
        product=product,
        type="adjustment",
        quantity=-quantity,
        balance_after=product.stock,
        user=user,
        reason=f"Consumo interno #{row.pk}: {note}"[:500],
    )
    append_audit(
        tenant=tenant,
        user=user,
        action="MATERIAL_CONSUMED",
        entity_type="MaterialConsumption",
        entity_id=row.pk,
        after={
            "product": product.pk,
            "quantity": quantity,
            "appointment": getattr(appointment, "pk", None),
        },
    )
    return row


def consume_recipe(appointment, user):
    for material in (
        appointment.service.materials.filter(tenant=appointment.tenant, active=True)
        .filter(Q(product__unit=appointment.unit) | Q(product__unit__isnull=True))
        .order_by("product_id")
    ):
        consume_material(
            tenant=appointment.tenant,
            product_id=material.product_id,
            quantity=material.quantity,
            user=user,
            key=f"appointment:{appointment.pk}:material:{material.pk}",
            appointment=appointment,
            note="Ficha de consumo do serviço",
        )
