from celery import shared_task
from django.utils import timezone

from .models import CheckoutSession,Payment,Subscription


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
    overdue=Payment.objects.filter(
        status=Payment.Status.PENDING,
        due_at__isnull=False,
        due_at__lt=now,
    ).count()
    return {"expired_trials":expired_trials,"pending_overdue":overdue}
