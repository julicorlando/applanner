"""Appointment-scoped read access never changes clinical authorship."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.utils import timezone
from scheduling.models import Appointment
from billing.entitlements import module_enabled


def scheduled_dental_patients(user):
    rows=Appointment.objects.none()
    if not user or not user.is_authenticated or not user.is_active or user.is_superuser or not user.tenant_id or user.tenant.archived_at or user.tenant.deleted_at:
        return rows.values('customer_id')
    if not module_enabled(user.tenant,'dentistry') or not module_enabled(user.tenant,'medical_records'):
        return rows.values('customer_id')
    try:zone=ZoneInfo(user.tenant.timezone or 'America/Recife')
    except (ZoneInfoNotFoundError,ValueError):zone=timezone.get_default_timezone()
    start=timezone.now().astimezone(zone).replace(hour=0,minute=0,second=0,microsecond=0)
    return Appointment.objects.filter(tenant_id=user.tenant_id,professional__tenant_id=user.tenant_id,
        professional__user=user,professional__active=True,professional__clinical_registration__council='CRO',
        status__in=['pending','confirmed','waiting','in_progress'],ends_at__gte=start).exclude(
        professional__clinical_registration__number='').exclude(professional__clinical_registration__jurisdiction='').values('customer_id')
