"""Recurring company billing reminders, independent of customer notifications."""
import hashlib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from communications.models import Notification, UserNotification
from .access import current_subscription, paid_access_until
from .models import Subscription, SubscriptionNoticeLog


def billing_notice(subscription, now=None):
    if not subscription or subscription.status in {Subscription.Status.CANCELLED, Subscription.Status.SUSPENDED}:
        return None
    deadline=paid_access_until(subscription)
    kind="payment" if deadline else "trial"
    deadline=deadline or subscription.trial_ends_at or subscription.next_billing_at
    if not deadline:
        return None
    try:
        tz=ZoneInfo(subscription.tenant.timezone or "America/Recife")
    except ZoneInfoNotFoundError:
        tz=ZoneInfo("America/Recife")
    now=now or timezone.now()
    local_deadline=deadline.astimezone(tz)
    days=(local_deadline.date()-now.astimezone(tz).date()).days
    if days>3:
        return None
    overdue=deadline<=now
    title=("Pagamento da assinatura vencido" if overdue else
           "Seu teste grátis termina hoje" if kind=="trial" and days==0 else
           f"Seu teste grátis termina em {days} dias" if kind=="trial" else
           "Sua assinatura vence hoje" if days==0 else
           f"Sua assinatura vence em {days} {'dia' if days==1 else 'dias'}")
    label=local_deadline.strftime("%d/%m/%Y às %H:%M")
    if overdue:
        message=f"O prazo terminou em {label}. Regularize o pagamento para liberar o acesso ao ApPlanner."
    elif kind=="trial":
        message=f"Seu teste termina em {label}. Assine para continuar usando o ApPlanner após esse prazo."
    elif subscription.provider_subscription_id:
        message=f"A renovação está prevista para {label}. Confira a forma de pagamento da assinatura automática; o acesso depende da confirmação do pagamento."
    else:
        message=f"Seu ciclo vence em {label}. No Pix, cada ciclo precisa de um novo pagamento para manter o acesso."
    return {"kind":kind,"deadline":deadline,"days":days,"overdue":overdue,
            "title":title,"message":message,"action_url":reverse("billing-subscription-status")}


def payment_reminder(request):
    user=request.user
    if not user.is_authenticated or not user.tenant_id or user.is_superuser or user.role not in {"owner","manager"}:
        return {}
    notice=billing_notice(current_subscription(user.tenant))
    # Keep the existing trial popup; recurring renewals also remain visible on every page.
    return {"billing_due_notice":notice} if notice else {}


def queue_subscription_reminder(subscription_id, now=None):
    with transaction.atomic():
        subscription=Subscription.objects.select_for_update().select_related("tenant").filter(pk=subscription_id).first()
        if not subscription or current_subscription(subscription.tenant).pk!=subscription.pk:
            return 0
        notice=billing_notice(subscription,now)
        if not notice:
            return 0
        stages={2,0} if notice["kind"]=="trial" else {3,1,0}
        if not notice["overdue"] and notice["days"] not in stages:
            return 0
        users=list(User.objects.filter(tenant=subscription.tenant,is_active=True,role__in=["owner","manager"]))
        if not users:
            return 0
        # UTC deadline identifies a cycle; changing dates or renewing creates a new key.
        fingerprint=hashlib.sha256(notice["deadline"].isoformat().encode()).hexdigest()[:20]
        stage="overdue" if notice["overdue"] else str(notice["days"])
        key=f"{notice['kind']}:{fingerprint}:{stage}"
        _,created=SubscriptionNoticeLog.objects.get_or_create(subscription=subscription,notice_key=key,defaults={"tenant":subscription.tenant})
        if not created:
            return 0
        for user in users:
            UserNotification.objects.create(tenant=subscription.tenant,user=user,type="subscription",title=notice["title"],
                message=notice["message"],action_url=notice["action_url"],severity="danger" if notice["overdue"] else "warning")
        base=settings.PUBLIC_BASE_URL.rstrip("/")
        text=f"{subscription.tenant.name}\n\n{notice['message']}\n\nPlano e pagamento: {base}{notice['action_url']}"
        for email in sorted({user.email for user in users if user.email}):
            Notification.objects.create(tenant=subscription.tenant,channel="email",destination=email,
                template_key="subscription_due",payload={"subject":f"ApPlanner — {notice['title']}","text":text,
                "subscription_id":subscription.pk,"notice_key":key})
        return 1


def reminder_is_current(notification):
    subscription=Subscription.objects.select_related("tenant").filter(pk=notification.payload.get("subscription_id"),tenant_id=notification.tenant_id).first()
    if not subscription or current_subscription(subscription.tenant).pk!=subscription.pk:
        return False
    notice=billing_notice(subscription)
    if not notice:
        return False
    fingerprint=hashlib.sha256(notice["deadline"].isoformat().encode()).hexdigest()[:20]
    stage="overdue" if notice["overdue"] else str(notice["days"])
    return notification.payload.get("notice_key")==f"{notice['kind']}:{fingerprint}:{stage}"
