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


def professional_capacity(tenant, subscription=None):
    """The trial follows the same limits; absent legacy limits remain undeclared."""
    subscription=subscription or active_subscription(tenant)
    raw=(subscription.plan.features or {}).get("professionals") if subscription else None
    def positive_limit(value):
        return int(value) if not isinstance(value,bool) and str(value).isdigit() and int(value)>0 else None
    plan_limit=positive_limit(raw)
    override=(tenant.metadata or {}).get("professional_limit_override")
    unlimited=override==0 and not isinstance(override,bool)
    overridden=unlimited or positive_limit(override) is not None
    effective=None if unlimited else positive_limit(override) if overridden else plan_limit
    used=tenant.professionals.filter(active=True).count()
    return {"plan_limit":plan_limit,"limit":effective,"used":used,"overridden":overridden,
            "unlimited":unlimited,"available":max(0,effective-used) if effective is not None else None,
            "exceeded":effective is not None and used>effective}


def validate_professional_capacity(professional):
    from django.core.exceptions import ValidationError
    if not professional.tenant_id or not professional.active:
        return
    # Editing an existing active professional must not suspend legacy operation.
    if professional.pk and type(professional).objects.filter(pk=professional.pk,
            tenant_id=professional.tenant_id,active=True).exists():
        return
    capacity=professional_capacity(professional.tenant)
    if capacity["limit"] is not None and capacity["used"]>=capacity["limit"]:
        raise ValidationError(
            f"Limite de {capacity['limit']} profissionais ativos atingido. "
            "Desative um profissional ou solicite ao Master a ampliação do limite."
        )


def arena_limit(tenant,key):
    """Zero/absent means unrestricted; explicit Master releases win over the plan."""
    override=(tenant.metadata or {}).get(f"{key}_limit_override")
    subscription=active_subscription(tenant)
    raw=(subscription.plan.features or {}).get(key) if subscription else None
    if override is not None:
        raw=override
    return int(raw) if not isinstance(raw,bool) and str(raw).isdigit() and int(raw)>0 else None


def validate_court_capacity(court):
    from django.core.exceptions import ValidationError
    if not court.tenant_id or not court.active:
        return
    if court.pk and type(court).objects.filter(pk=court.pk,tenant_id=court.tenant_id,active=True).exists():
        return
    limit=arena_limit(court.tenant,"courts")
    if limit is not None and court.tenant.sports_courts.filter(active=True).count()>=limit:
        label="quadra ativa" if limit==1 else "quadras ativas"
        raise ValidationError(f"Limite de {limit} {label} atingido. Desative uma quadra ou solicite uma liberação ao Master.")


def validate_reservation_capacity(tenant,start):
    from zoneinfo import ZoneInfo
    from datetime import datetime
    from django.core.exceptions import ValidationError
    from arena.models import Reservation
    limit=arena_limit(tenant,"reservations")
    if limit is None:
        return
    tz=ZoneInfo(tenant.timezone or "America/Recife")
    month=start.astimezone(tz)
    beginning=datetime(month.year,month.month,1,tzinfo=tz)
    end=datetime(month.year+1,1,1,tzinfo=tz) if month.month==12 else datetime(month.year,month.month+1,1,tzinfo=tz)
    used=Reservation.objects.filter(tenant=tenant,starts_at__gte=beginning,starts_at__lt=end,
        status__in=[Reservation.Status.PENDING_PAYMENT,Reservation.Status.CONFIRMED,Reservation.Status.COMPLETED]).count()
    if used>=limit:
        label="reserva" if limit==1 else "reservas"
        raise ValidationError(f"Limite de {limit} {label} neste mês atingido. Entre em contato com a arena para verificar uma liberação.")
