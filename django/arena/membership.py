from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from billing.entitlements import module_enabled
from finance.models import FinancialTransaction

from .models import Membership, MembershipConflict, MembershipReservation, Reservation
from .services import ArenaReservationService


def _occurs(membership, day):
    if day < membership.start_date:
        return False
    if membership.end_date and day > membership.end_date:
        return False

    if membership.frequency==Membership.Frequency.MONTHLY:
        return membership.day_of_month is not None and day.day==membership.day_of_month

    if membership.weekday is None or day.isoweekday()!=membership.weekday:
        return False

    anchor=membership.start_date
    while anchor.isoweekday()!=membership.weekday:
        anchor+=timedelta(days=1)
    if day<anchor:
        return False
    interval=14 if membership.frequency==Membership.Frequency.BIWEEKLY else 7
    return (day-anchor).days % interval == 0


def _ensure_monthly_finance(membership):
    if membership.monthly_amount<=0 or not module_enabled(membership.tenant,"finance"):
        return None
    today=timezone.localdate()
    key=f"arena-membership-{membership.pk}-{today:%Y%m}"
    tx,_=FinancialTransaction.objects.get_or_create(
        tenant=membership.tenant,
        idempotency_key=key,
        defaults={
            "source_type":"arena_membership",
            "source_id":membership.pk,
            "type":FinancialTransaction.Type.INCOME,
            "description":f"Mensalidade Arena #{membership.pk}",
            "amount":membership.monthly_amount,
            "payment_method":"outro",
            "status":FinancialTransaction.Status.PENDING,
            "due_at":today,
            "competence_at":today,
        },
    )
    return tx


@transaction.atomic
def generate_membership(membership):
    membership=(
        Membership.objects
        .select_for_update()
        .select_related("tenant","customer","court","modality")
        .get(pk=membership.pk,status=Membership.Status.ACTIVE)
    )
    today=timezone.localdate()
    from_day=max(today,membership.start_date)
    if membership.next_generation_date and membership.next_generation_date>from_day:
        from_day=membership.next_generation_date

    to_day=today+timedelta(days=max(7,membership.generate_days_ahead))
    if membership.end_date and membership.end_date<to_day:
        to_day=membership.end_date
    if from_day>to_day:
        return {"generated":0,"conflicts":0,"until":to_day.isoformat()}

    service=ArenaReservationService()
    tz=ZoneInfo(membership.tenant.timezone or "America/Recife")
    generated=0
    conflicts=0
    day=from_day
    while day<=to_day:
        if not _occurs(membership,day):
            day+=timedelta(days=1)
            continue

        if MembershipReservation.objects.filter(
            membership=membership,occurrence_date=day
        ).exists():
            day+=timedelta(days=1)
            continue

        start=datetime.combine(day,membership.start_time,tzinfo=tz)
        end=start+timedelta(minutes=membership.duration_minutes)
        try:
            reservation,_token=service.create_reservation(
                tenant=membership.tenant,
                court=membership.court,
                modality=membership.modality,
                start=start,
                end=end,
                customer=membership.customer,
                customer_name=membership.customer.name,
                customer_phone=membership.customer.phone,
                customer_email=membership.customer.email,
                source=Reservation.Source.RECURRING,
                notes=f"Mensalista #{membership.pk}",
                public_rules=False,
            )
            MembershipReservation.objects.create(
                membership=membership,
                reservation=reservation,
                tenant=membership.tenant,
                occurrence_date=day,
            )
            MembershipConflict.objects.filter(
                membership=membership,starts_at=start,resolved_at__isnull=True
            ).update(resolved_at=timezone.now())
            generated+=1
        except ValidationError as exc:
            message="; ".join(exc.messages) if hasattr(exc,"messages") else str(exc)
            MembershipConflict.objects.update_or_create(
                membership=membership,
                starts_at=start,
                defaults={
                    "tenant":membership.tenant,
                    "occurrence_date":day,
                    "reason":message[:300],
                    "resolved_at":None,
                },
            )
            conflicts+=1
        day+=timedelta(days=1)

    membership.next_generation_date=to_day+timedelta(days=1)
    membership.save(update_fields=["next_generation_date","updated_at"])
    _ensure_monthly_finance(membership)
    return {"generated":generated,"conflicts":conflicts,"until":to_day.isoformat()}
