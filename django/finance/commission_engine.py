from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from .models import (
    CommissionPolicy,
    CommissionSnapshot,
    ProfessionalCommission,
    MaterialConsumption,
)


@transaction.atomic
def calculate(
    *,
    tenant,
    professional,
    gross,
    service=None,
    product=None,
    materials=0,
    earned_on=None,
):
    day = (
        earned_on
        or timezone.now()
        .astimezone(ZoneInfo(tenant.timezone or "America/Recife"))
        .date()
    )
    # All policies for this professional share a lock order, even when product/service differ.
    list(
        CommissionPolicy.objects.select_for_update()
        .filter(tenant=tenant, professional=professional)
        .order_by("pk")
    )
    policies = CommissionPolicy.objects.filter(
        tenant=tenant, professional=professional, active=True, starts_on__lte=day
    )
    from django.db.models import Q

    policies = policies.filter(Q(ends_on__isnull=True) | Q(ends_on__gte=day))
    if service:
        policies = policies.filter(product__isnull=True).filter(
            Q(service=service) | Q(service__isnull=True)
        )
    else:
        policies = policies.filter(service__isnull=True, product=product)
    matches = list(
        policies.select_related("service", "product").prefetch_related("tiers")
    )
    specific = [p for p in matches if p.service_id or p.product_id]
    matches = specific or matches
    if len(matches) > 1:
        raise ValidationError(
            "Existem políticas de comissão sobrepostas. Corrija a vigência antes de concluir."
        )
    if not matches:
        return None
    policy = matches[0]
    tiers = list(policy.tiers.all())
    if not tiers or tiers[0].threshold != 0:
        raise ValidationError(
            "A política de comissão precisa de uma faixa inicial com meta zero."
        )
    tz = ZoneInfo(tenant.timezone or "America/Recife")
    first = datetime.combine(day.replace(day=1), time.min, tz)
    after = datetime.combine(day + timedelta(days=1), time.min, tz)
    previous = ProfessionalCommission.objects.filter(
        tenant=tenant,
        professional=professional,
        status__in=["pending", "paid"],
        source_type__in=[
            "appointment",
            "product",
            "command_service",
            "command_product",
        ],
    ).filter(
        Q(
            calculation__earned_on__gte=day.replace(day=1),
            calculation__earned_on__lte=day,
        )
        | Q(calculation__isnull=True, created_at__gte=first, created_at__lt=after)
    ).aggregate(v=Sum("gross_amount"))["v"] or Decimal(0)
    # Sequential progress: the reached rate applies to this event, never rewrites previous snapshots.
    target = previous + Decimal(gross)
    tier = max((t for t in tiers if t.threshold <= target), key=lambda t: t.threshold)
    material_cost = (
        max(Decimal(materials), Decimal(0)) if policy.deduct_materials else Decimal(0)
    )
    base = max(Decimal(gross) - material_cost, Decimal(0))
    amount = (base * tier.rate / 100).quantize(Decimal(".01"))
    return amount, {
        "policy_id": policy.pk,
        "name": policy.name,
        "rate": str(tier.rate),
        "threshold": str(tier.threshold),
        "previous_gross": str(previous),
        "gross": str(gross),
        "materials": str(material_cost),
        "base": str(base),
        "amount": str(amount),
        "earned_on": day.isoformat(),
    }


def save_snapshot(commission, result, earned_on=None):
    day = (
        earned_on
        or timezone.now()
        .astimezone(ZoneInfo(commission.tenant.timezone or "America/Recife"))
        .date()
    )
    if result:
        _, details = result
        day = date.fromisoformat(details["earned_on"])
        policy_id = details["policy_id"]
    else:
        details = {
            "legacy": True,
            "gross": str(commission.gross_amount),
            "amount": str(commission.commission_amount),
        }
        policy_id = None
    return CommissionSnapshot.objects.get_or_create(
        commission=commission,
        defaults={"policy_id": policy_id, "details": details, "earned_on": day},
    )


def material_cost(appointment):
    if not appointment:
        return Decimal(0)
    return MaterialConsumption.objects.filter(
        tenant=appointment.tenant, appointment=appointment, reversed_at__isnull=True
    ).aggregate(v=Sum("cost_snapshot"))["v"] or Decimal(0)
