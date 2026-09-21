from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from finance.models import FinancialTransaction

from .models import CustomerMembership,CustomerPackage,WaitlistEntry


@shared_task
def bill_due_memberships(limit=250):
    today=timezone.localdate()
    rows=CustomerMembership.objects.filter(
        status=CustomerMembership.Status.ACTIVE,
        next_due_at__lte=today,
    ).select_related("tenant","customer","package").order_by("next_due_at")[:limit]
    count=0
    for row in rows:
        competence=row.next_due_at.strftime("%Y%m")
        key=f"customer-membership:{row.pk}:{competence}"
        FinancialTransaction.objects.get_or_create(
            tenant=row.tenant,
            idempotency_key=key,
            defaults={
                "source_type":"customer_membership",
                "source_id":row.pk,
                "type":FinancialTransaction.Type.INCOME,
                "description":f"Mensalidade {row.package.name} · {row.customer.name}",
                "amount":row.recurring_amount,
                "status":FinancialTransaction.Status.PENDING,
                "due_at":row.next_due_at,
                "competence_at":row.next_due_at,
            },
        )
        row.last_billed_at=today
        row.next_due_at=row.next_due_at+timedelta(
            days=90 if row.cycle==CustomerMembership.Cycle.QUARTERLY else 30
        )
        row.save(update_fields=["last_billed_at","next_due_at","updated_at"])
        count+=1
    return count


@shared_task
def expire_packages_and_waitlist():
    now=timezone.now()
    expired=CustomerPackage.objects.filter(
        status=CustomerPackage.Status.ACTIVE,
        expires_at__isnull=False,
        expires_at__lte=now,
    ).update(status=CustomerPackage.Status.EXPIRED,updated_at=now)
    wait=WaitlistEntry.objects.filter(
        status=WaitlistEntry.Status.WAITING,
        preferred_date__lt=timezone.localdate(),
    ).update(status=WaitlistEntry.Status.EXPIRED,updated_at=now)
    return {"packages":expired,"waitlist":wait}
