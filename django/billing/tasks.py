from celery import shared_task
from django.utils import timezone

from .models import CheckoutSession,Payment,Subscription


@shared_task
def queue_subscription_reminders():
    from .reminders import queue_subscription_reminder
    ids=Subscription.objects.exclude(status__in=[Subscription.Status.CANCELLED,Subscription.Status.SUSPENDED]).values_list("pk",flat=True)
    return sum(queue_subscription_reminder(pk) for pk in ids.iterator())


@shared_task
def expire_checkouts():
    return CheckoutSession.objects.filter(
        status__in=[
            CheckoutSession.Status.STARTED,
            CheckoutSession.Status.AWAITING_PAYMENT,
        ],
        expires_at__lte=timezone.now(),
    ).update(status=CheckoutSession.Status.EXPIRED,updated_at=timezone.now())


@shared_task
def reconcile_subscription_states():
    now=timezone.now()
    expired_trials=Subscription.objects.filter(
        status=Subscription.Status.TRIAL,
        trial_ends_at__isnull=False,
        trial_ends_at__lt=now,
    ).update(status=Subscription.Status.PAST_DUE,updated_at=now)
    due_pix=Subscription.objects.filter(
        status=Subscription.Status.ACTIVE,provider_subscription_id="",
        next_billing_at__isnull=False,next_billing_at__lte=now,
        payments__metadata__method="pix",payments__status=Payment.Status.PAID,
    ).distinct().values_list("pk",flat=True)
    due_pix_count=Subscription.objects.filter(pk__in=due_pix).update(
        status=Subscription.Status.PAST_DUE,updated_at=now,
    )
    overdue=Payment.objects.filter(
        status=Payment.Status.PENDING,
        due_at__isnull=False,
        due_at__lt=now,
    ).count()
    return {"expired_trials":expired_trials,"pix_renewals_due":due_pix_count,"pending_overdue":overdue}


@shared_task(bind=True,max_retries=3,autoretry_for=(Exception,),retry_backoff=True)
def sync_per_unit_addon_pricing_task(self,tenant_id):
    from .module_services import sync_per_unit_addon_pricing
    row=sync_per_unit_addon_pricing(tenant_id)
    return row.pk if row else None


@shared_task
def reconcile_pending_pix():
    import logging
    from datetime import timedelta
    from .models import PixCharge
    from .pix_reconciliation import reconcile_pix_charge
    ids=list(PixCharge.objects.filter(payment__status=Payment.Status.PENDING,
        created_at__gte=timezone.now()-timedelta(days=7)).order_by("updated_at").values_list("pk",flat=True)[:100])
    confirmed=0
    for pk in ids:
        try:
            confirmed+=int(reconcile_pix_charge(pk))
        except (RuntimeError,ValueError):
            logging.getLogger(__name__).warning("Não foi possível reconciliar a cobrança Pix %s",pk)
        finally:
            PixCharge.objects.filter(pk=pk).update(updated_at=timezone.now())
    return confirmed
