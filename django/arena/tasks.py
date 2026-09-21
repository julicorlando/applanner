from celery import shared_task

from .membership import generate_membership
from .models import Membership


@shared_task
def generate_due_memberships(limit=250):
    memberships=(
        Membership.objects
        .filter(status=Membership.Status.ACTIVE)
        .select_related("tenant")
        .order_by("next_generation_date","id")[:max(1,min(500,int(limit)))]
    )
    result={"memberships":0,"generated":0,"conflicts":0}
    for membership in memberships:
        try:
            one=generate_membership(membership)
        except Exception:
            continue
        result["memberships"]+=1
        result["generated"]+=one["generated"]
        result["conflicts"]+=one["conflicts"]
    return result


@shared_task
def expire_unpaid_reservations(limit=200):
    from django.utils import timezone
    from billing.models import TenantPaymentTransaction
    from .models import Reservation,ReservationFinance,ReservationHistory

    rows=(
        ReservationFinance.objects
        .filter(
            payment_state=ReservationFinance.State.PENDING,
            expires_at__isnull=False,
            expires_at__lt=timezone.now(),
        )
        .select_related("reservation","tenant")
        .order_by("expires_at")[:limit]
    )
    count=0
    for finance in rows:
        reservation=finance.reservation
        if reservation.status!=Reservation.Status.PENDING_PAYMENT:
            continue
        reservation.status=Reservation.Status.CANCELLED
        reservation.payment_status=Reservation.PaymentStatus.CANCELLED
        reservation.cancelled_at=timezone.now()
        reservation.save(update_fields=["status","payment_status","cancelled_at","updated_at"])
        finance.payment_state=ReservationFinance.State.EXPIRED
        finance.save(update_fields=["payment_state","updated_at"])
        TenantPaymentTransaction.objects.filter(
            tenant=reservation.tenant,
            reference_type="reservation",
            reference_id=reservation.pk,
            status__in=[
                TenantPaymentTransaction.Status.CREATED,
                TenantPaymentTransaction.Status.PENDING,
            ],
        ).update(status=TenantPaymentTransaction.Status.EXPIRED,updated_at=timezone.now())
        ReservationHistory.objects.create(
            reservation=reservation,
            action="payment_expired",
            old_status=Reservation.Status.PENDING_PAYMENT,
            new_status=Reservation.Status.CANCELLED,
            notes="Prazo do sinal expirado; horário liberado",
        )
        count+=1
    return count


@shared_task
def refresh_arena_customer_metrics():
    from decimal import Decimal
    from django.db.models import Count,Max,Sum,Q
    from django.utils import timezone
    from scheduling.models import Customer
    from .models import CustomerMetric,GamePlayer,Membership,Reservation

    today=timezone.now()
    count=0
    for customer in Customer.objects.filter(active=True).iterator(chunk_size=200):
        qs=Reservation.objects.filter(
            tenant=customer.tenant,
            customer=customer,
        )
        aggregate=qs.aggregate(
            last=Max("starts_at"),
            reservations=Count("id",filter=Q(status__in=[
                Reservation.Status.CONFIRMED,Reservation.Status.COMPLETED,Reservation.Status.NO_SHOW
            ])),
            cancellations=Count("id",filter=Q(status=Reservation.Status.CANCELLED)),
            no_shows=Count("id",filter=Q(status=Reservation.Status.NO_SHOW)),
            spent=Sum("total_amount",filter=Q(status__in=[
                Reservation.Status.CONFIRMED,Reservation.Status.COMPLETED
            ])),
        )
        reservations=aggregate["reservations"] or 0
        spent=aggregate["spent"] or Decimal("0")
        last=aggregate["last"]
        days=(today-last).days if last else None
        segment=CustomerMetric.Segment.NEW
        if reservations>=10 or spent>=Decimal("1500"):
            segment=CustomerMetric.Segment.VIP
        elif days is not None and days>=60:
            segment=CustomerMetric.Segment.INACTIVE
        elif days is not None and days>=30:
            segment=CustomerMetric.Segment.CHURN_RISK
        elif reservations>=2:
            segment=CustomerMetric.Segment.RECURRING
        CustomerMetric.objects.update_or_create(
            tenant=customer.tenant,customer=customer,
            defaults={
                "last_reservation_at":last,
                "reservation_count":reservations,
                "cancellation_count":aggregate["cancellations"] or 0,
                "no_show_count":aggregate["no_shows"] or 0,
                "total_spent":spent,
                "average_ticket":(spent/reservations if reservations else Decimal("0")),
                "is_membership":Membership.objects.filter(
                    tenant=customer.tenant,customer=customer,status=Membership.Status.ACTIVE
                ).exists(),
                "game_count":GamePlayer.objects.filter(
                    tenant=customer.tenant,customer=customer,
                    participation_status=GamePlayer.ParticipationStatus.CONFIRMED,
                ).count(),
                "segment":segment,
            },
        )
        count+=1
    return count
