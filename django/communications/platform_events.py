"""Private, deduplicated platform events. Notification bodies never contain client data."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
import hashlib
import json
import logging

from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import pre_save, post_save
from django.urls import reverse
from django.utils import timezone

from .mobile_delivery import queue_push
from .mobile_models import PushSubscription

_suppressed = ContextVar("applanner_bulk_platform_events", default=False)


@contextmanager
def suppress_platform_events():
    token = _suppressed.set(True)
    try:
        yield
    finally:
        _suppressed.reset(token)


def master_notice(key, title, url="/master/"):
    count = 0
    for subscription in PushSubscription.objects.filter(
            active=True, tenant__isnull=True, customer__isnull=True,
            user__is_superuser=True, user__is_active=True, user__deleted_at__isnull=True):
        queue_push(subscription, "platform:" + key, {
            "title": title, "body": "Uma atualização da plataforma está disponível. Abra o Master para conferir.",
            "url": url, "tag": hashlib.sha256(("platform:" + key).encode()).hexdigest(),
        })
        count += 1
    return count


def after_commit_notice(key, title, url="/master/"):
    def publish():
        try:
            master_notice(key, title, url)
        except Exception as exc:
            logging.getLogger(__name__).warning("Evento Push pendente de reconciliação (%s).", type(exc).__name__)
    transaction.on_commit(publish)


def payment_notice(payment):
    if payment.purpose != "subscription" or payment.environment in {"sandbox", "test"}:
        return
    titles = {"pending": "Nova cobrança criada", "paid": "Pagamento confirmado",
              "failed": "Falha no pagamento", "expired": "Cobrança expirada",
              "cancelled": "Cobrança cancelada", "refunded": "Pagamento estornado",
              "partially_refunded": "Pagamento parcialmente estornado"}
    title = titles.get(payment.status)
    if title:
        after_commit_notice(f"payment:{payment.pk}:{payment.status}", title,
                            reverse("master-charge-detail", args=[payment.pk]))
    if payment.status == "pending" and payment.due_at and payment.due_at <= timezone.now():
        after_commit_notice(f"payment:{payment.pk}:overdue:{payment.due_at.isoformat()}",
                            "Cobrança em atraso", reverse("master-charge-detail", args=[payment.pk]))


def subscription_notice(subscription):
    url = reverse("master-company-detail", args=[subscription.tenant_id])
    if subscription.status in {"trial", "past_due"} and subscription.trial_ends_at:
        if subscription.trial_ends_at <= timezone.now() and not subscription.payments.filter(status="paid").exists():
            after_commit_notice(f"subscription:{subscription.pk}:trial-ended:{subscription.trial_ends_at.isoformat()}",
                                "Teste grátis encerrado", url)
    if subscription.status == "past_due":
        cycle = subscription.next_billing_at or subscription.trial_ends_at or subscription.started_at
        after_commit_notice(f"subscription:{subscription.pk}:past-due:{cycle.isoformat()}",
                            "Assinatura em atraso", url)
    elif subscription.status in {"cancelled", "suspended"}:
        after_commit_notice(f"subscription:{subscription.pk}:{subscription.status}",
                            "Assinatura cancelada" if subscription.status == "cancelled" else "Assinatura suspensa", url)


TRACKED = {
    "tenants.Tenant": ("name", "status", "public_enabled", "public_booking_enabled", "deleted_at", "archived_at"),
    "scheduling.Customer": ("name", "phone", "email", "active"),
    "billing.Payment": ("status", "due_at", "amount"),
    "billing.Subscription": ("status", "plan_id", "trial_ends_at", "next_billing_at"),
    "billing.Plan": ("name", "monthly_price", "quarterly_price", "semiannual_price", "annual_price",
                     "active", "public_visible", "features"),
    "billing.Module": ("name", "active", "addon_monthly_price", "addon_sellable", "per_unit_billing"),
    "accounts.User": ("is_active", "role", "tenant_id"),
}


def remember(sender, instance, raw=False, **kwargs):
    if raw or _suppressed.get():
        return
    fields = TRACKED.get(sender._meta.label)
    if fields:
        instance._push_previous = sender.objects.filter(pk=instance.pk).values(*fields).first() if instance.pk else None


def changed(sender, instance, created, raw=False, **kwargs):
    if raw or _suppressed.get():
        return
    fields = TRACKED.get(sender._meta.label)
    if not fields:
        return
    previous = getattr(instance, "_push_previous", None)
    current = {field: getattr(instance, field) for field in fields}
    if not created and previous == current:
        return
    label = sender._meta.label
    if label == "billing.Payment":
        payment_notice(instance)
        return
    if label == "billing.Subscription":
        subscription_notice(instance)
        if not created and previous and previous.get("plan_id") == instance.plan_id and previous.get("status") == instance.status:
            return
        title = "Novo teste grátis" if created and instance.status == "trial" else "Nova assinatura" if created else "Assinatura atualizada"
        url = reverse("master-company-detail", args=[instance.tenant_id])
    elif label == "tenants.Tenant":
        title = "Nova empresa cadastrada" if created else "Cadastro da empresa atualizado"
        url = reverse("master-company-detail", args=[instance.pk])
    elif label == "scheduling.Customer":
        title = "Novo cliente cadastrado" if created else "Cadastro de cliente atualizado"
        url = reverse("master-company-detail", args=[instance.tenant_id])
    elif label == "billing.Plan":
        title = "Novo plano cadastrado" if created else "Plano atualizado"
        url = reverse("master-resource-list", args=["planos"])
    elif label == "billing.Module":
        title = "Novo módulo cadastrado" if created else "Módulo atualizado"
        url = "/master/"
    else:
        title = "Novo usuário cadastrado" if created else "Acesso de usuário atualizado"
        url = "/master/"
    version = "created" if created else str(getattr(instance, "updated_at", timezone.now()))
    digest = hashlib.sha256(json.dumps(current, sort_keys=True, default=str).encode()).hexdigest()[:20]
    after_commit_notice(f"{label}:{instance.pk}:{version}:{digest}", title, url)


def audit_changed(sender, instance, created, raw=False, **kwargs):
    if not created or raw or _suppressed.get():
        return
    # The above entity signals already report these changes.
    if instance.entity_type.lower() in {"tenant", "customer", "payment", "subscription", "plan", "module", "user"}:
        return
    after_commit_notice(f"audit:{instance.pk}", "Alteração administrativa registrada")


def install():
    for model in TRACKED:
        pre_save.connect(remember, sender=model, dispatch_uid="push-previous:" + model)
        post_save.connect(changed, sender=model, dispatch_uid="push-changed:" + model)
    post_save.connect(audit_changed, sender="core.AuditLog", dispatch_uid="push-platform-audit")


@shared_task
def reconcile_platform_events():
    """Recover events from bulk updates and deadlines; never modifies billing state."""
    if not PushSubscription.objects.filter(active=True, tenant__isnull=True,
            user__is_superuser=True, user__is_active=True).exists():
        return 0
    from billing.models import Payment, Subscription
    now = timezone.now()
    threshold = now - timedelta(days=1)
    count = 0
    for payment in Payment.objects.filter(purpose="subscription").exclude(environment__in=["sandbox", "test"]).filter(
            Q(updated_at__gte=threshold) | Q(status="pending", due_at__lte=now)).order_by("pk").iterator(chunk_size=200):
        payment_notice(payment)
        count += 1
    for subscription in Subscription.objects.filter(Q(status__in=["past_due", "cancelled", "suspended"]) |
            Q(status="trial", trial_ends_at__lte=now)).order_by("pk").iterator(chunk_size=200):
        subscription_notice(subscription)
        count += 1
    return count
