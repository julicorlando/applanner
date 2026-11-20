"""Fase de implantação: transcrição de prontuários anteriores com a data clínica original.

A data/hora real de digitação (``created_at``) nunca é alterada. A data clínica
informada fica em ``clinical_date`` e o registro aponta para a janela de
implantação em que foi transcrito, para que a origem fique visível e auditável.
"""
from datetime import date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from core.audit import append_audit
from .implementation_models import ClinicalImplementationPeriod

MAX_DAYS = 180
EARLIEST = date(1900, 1, 1)
MANAGERS = {"owner", "tenant-admin"}


def tenant_today(tenant):
    try:
        zone = ZoneInfo(tenant.timezone or "America/Recife")
    except (ZoneInfoNotFoundError, ValueError):
        zone = timezone.get_default_timezone()
    return timezone.now().astimezone(zone).date()


def active_period(tenant, today=None):
    if tenant is None:
        return None
    today = today or tenant_today(tenant)
    return (
        ClinicalImplementationPeriod.objects.filter(
            tenant=tenant, closed_at__isnull=True, starts_on__lte=today, ends_on__gte=today
        )
        .order_by("-pk")
        .first()
    )


def can_manage(user, tenant):
    return bool(
        user and user.is_authenticated and user.is_active and not user.is_superuser
        and tenant and user.tenant_id == tenant.pk and user.role in MANAGERS
        and not tenant.archived_at and not tenant.deleted_at
    )


def _lock(tenant, user):
    if not can_manage(user, tenant):
        raise PermissionDenied("Somente o responsável da clínica gerencia a implantação.")
    from tenants.models import Tenant
    Tenant.objects.select_for_update().get(pk=tenant.pk)


@transaction.atomic
def open_period(*, tenant, user, ends_on, request=None):
    _lock(tenant, user)
    today = tenant_today(tenant)
    if active_period(tenant, today):
        raise ValidationError("Já existe uma implantação em andamento.")
    if not isinstance(ends_on, date) or ends_on < today or ends_on > today + timedelta(days=MAX_DAYS):
        raise ValidationError(f"Escolha um término entre hoje e {MAX_DAYS} dias.")
    row = ClinicalImplementationPeriod.objects.create(
        tenant=tenant, starts_on=today, ends_on=ends_on, opened_by=user
    )
    append_audit(tenant=tenant, user=user, request=request, action="clinical.implementation.opened",
                 entity_type="ClinicalImplementationPeriod", entity_id=row.pk,
                 after={"starts_on": today.isoformat(), "ends_on": ends_on.isoformat()})
    return row


@transaction.atomic
def close_period(*, tenant, user, request=None):
    _lock(tenant, user)
    row = active_period(tenant)
    if not row:
        raise ValidationError("Não há implantação em andamento.")
    row.closed_at = timezone.now()
    row.closed_by = user
    row.save(update_fields=["closed_at", "closed_by"])
    append_audit(tenant=tenant, user=user, request=request, action="clinical.implementation.closed",
                 entity_type="ClinicalImplementationPeriod", entity_id=row.pk,
                 after={"closed_at": row.closed_at.isoformat()})
    return row


def validate_transcription(*, tenant, clinical_date):
    """Retorna a janela ativa ou recusa a transcrição."""
    period = active_period(tenant)
    if not period:
        raise ValidationError(
            "A fase de implantação não está ativa. O responsável da clínica pode ativá-la em Configurações."
        )
    if not isinstance(clinical_date, date) or not EARLIEST <= clinical_date <= tenant_today(tenant):
        raise ValidationError("A data do prontuário original deve ser hoje ou anterior.")
    return period
