from django.utils import timezone

from .models import Subscription, TenantModule


def active_subscription(tenant):
    return (
        Subscription.objects
        .filter(
            tenant=tenant,
            status__in=[Subscription.Status.TRIAL,Subscription.Status.ACTIVE],
        )
        .select_related("plan")
        .order_by("-started_at")
        .first()
    )


def module_enabled(tenant, module_slug: str) -> bool:
    override=(
        TenantModule.objects
        .filter(tenant=tenant,module__slug=module_slug,module__active=True)
        .values_list("enabled",flat=True)
        .first()
    )
    if override is not None:
        return bool(override)

    subscription=active_subscription(tenant)
    if not subscription:
        return False

    if subscription.status==Subscription.Status.TRIAL and subscription.trial_ends_at:
        if subscription.trial_ends_at < timezone.now():
            return False

    return subscription.plan.module_links.filter(
        module__slug=module_slug,
        module__active=True,
        enabled=True,
    ).exists()


def require_module(tenant,module_slug: str):
    if not module_enabled(tenant,module_slug):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied(f"Módulo '{module_slug}' não está disponível para este estabelecimento.")
