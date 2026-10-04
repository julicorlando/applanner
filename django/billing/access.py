"""Subscription entitlement checked on every request, without provider calls."""
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from .models import Subscription, Payment


def current_subscription(tenant):
    return Subscription.objects.filter(tenant=tenant).order_by('-started_at','-pk').first()


def subscription_allows_access(subscription, now=None):
    now=now or timezone.now()
    if not subscription or subscription.status in {Subscription.Status.CANCELLED,Subscription.Status.SUSPENDED}:
        return False
    if subscription.trial_ends_at and now < subscription.trial_ends_at:
        return True
    payment=subscription.payments.filter(tenant_id=subscription.tenant_id,purpose='subscription',status=Payment.Status.PAID).order_by('-paid_at','-pk').first()
    if not payment:
        return False
    paid_at=payment.paid_at or payment.updated_at
    months={'monthly':1,'quarterly':3,'semiannual':6,'annual':12}[subscription.billing_cycle]
    cycle_start=paid_at
    if subscription.trial_ends_at and subscription.started_at <= paid_at <= subscription.trial_ends_at:
        cycle_start=subscription.trial_ends_at
    covered_until=cycle_start+relativedelta(months=months)
    if subscription.next_billing_at:
        covered_until=max(covered_until,subscription.next_billing_at)
    return now < covered_until


def eligible_for_payment(subscription):
    if not subscription:
        return False
    if subscription.status in {Subscription.Status.TRIAL,Subscription.Status.PAST_DUE}:
        return True
    return subscription.status==Subscription.Status.ACTIVE and (
        not subscription_allows_access(subscription) or
        not subscription.payments.filter(tenant_id=subscription.tenant_id,purpose='subscription',status=Payment.Status.PAID).exists()
    )


def trial_prompt(request):
    user=request.user
    if not user.is_authenticated or request.method!='GET' or request.path.startswith('/account/'):
        return {}
    if not request.session.pop('trial_prompt_login',False):
        return {}
    if not user.tenant_id or user.role not in {'owner','manager'} or user.is_superuser:
        return {}
    subscription=current_subscription(user.tenant)
    if not subscription or not subscription.trial_ends_at or subscription.status not in {Subscription.Status.TRIAL,Subscription.Status.PAST_DUE,Subscription.Status.ACTIVE}:
        return {}
    if subscription.payments.filter(tenant_id=user.tenant_id,purpose='subscription',status=Payment.Status.PAID).exists():
        return {}
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        tz=ZoneInfo(user.tenant.timezone or 'America/Recife')
    except ZoneInfoNotFoundError:
        tz=ZoneInfo('America/Recife')
    remaining=(subscription.trial_ends_at.astimezone(tz).date()-timezone.now().astimezone(tz).date()).days
    return {'trial_subscription_prompt':{'days':remaining,'ends_at':subscription.trial_ends_at.astimezone(tz),'ends_label':subscription.trial_ends_at.astimezone(tz).strftime('%d/%m/%Y às %H:%M')}} if remaining in {2,0} else {}
