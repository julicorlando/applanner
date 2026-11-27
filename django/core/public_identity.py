"""Stable public links and platform registration verification."""
import secrets
from datetime import timedelta

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone

from tenants.models import Tenant, TenantOnboarding, Unit
from scheduling.models import Professional

VERIFIED_MODULE = 'verified-business'
REGISTRATION_FLAGS = (
    'company_done', 'branding_done', 'unit_done', 'professional_done',
    'service_done', 'schedule_done', 'payment_done', 'public_page_done',
)


def assign_short_code(instance, kwargs):
    if not instance.public_short_code:
        instance.public_short_code = secrets.token_hex(6)
        if kwargs.get('update_fields') is not None:
            kwargs['update_fields'] = set(kwargs['update_fields']) | {'public_short_code'}


def short_url(instance, unit=None):
    name = 'professional-short-link' if isinstance(instance, Professional) else 'tenant-short-link'
    path = reverse(name, args=[instance.public_short_code]) if instance.public_short_code else ''
    if path and unit:
        path += f'?unit={unit.pk}'
    return settings.PUBLIC_BASE_URL.rstrip('/') + path if path else ''


def verification_status(tenant):
    """The badge confirms registration completion, not service quality."""
    unlock_at = tenant.created_at + timedelta(days=7)
    row = TenantOnboarding.objects.filter(tenant=tenant).first()
    complete = bool(row and row.completed_at and all(getattr(row, field) for field in REGISTRATION_FLAGS))
    elapsed = timezone.now() >= unlock_at
    operational = tenant.status == Tenant.Status.ACTIVE and not tenant.deleted_at and not tenant.archived_at
    eligible = complete and elapsed and operational
    from billing.entitlements import module_enabled
    enabled = module_enabled(tenant, VERIFIED_MODULE)
    reasons = []
    if not elapsed:
        reasons.append('Aguardar sete dias completos desde o cadastro da empresa.')
    if not complete:
        reasons.append('Concluir todas as etapas do cadastro inicial.')
    if not operational:
        reasons.append('Manter a empresa ativa.')
    return {'eligible': eligible, 'verified': eligible and enabled,
            'enabled': enabled, 'unlock_at': unlock_at, 'reasons': reasons}


def tenant_short_link(request, code):
    tenant = get_object_or_404(Tenant, public_short_code=code, public_enabled=True,
        status__in=[Tenant.Status.TRIAL, Tenant.Status.ACTIVE], deleted_at__isnull=True,
        archived_at__isnull=True)
    url = reverse('tenant-public', args=[tenant.public_slug or tenant.slug])
    raw = request.GET.get('unit')
    if raw:
        unit = get_object_or_404(Unit, pk=raw if raw.isdigit() else 0, tenant=tenant, active=True)
        url += f'?unit={unit.pk}'
    return redirect(url)  # Temporary redirect follows later slug changes.


def professional_short_link(request, code):
    professional = get_object_or_404(Professional.objects.select_related('tenant'),
        public_short_code=code, active=True, tenant__public_enabled=True,
        tenant__status__in=[Tenant.Status.TRIAL, Tenant.Status.ACTIVE],
        tenant__deleted_at__isnull=True, tenant__archived_at__isnull=True)
    if not professional.public_slug:
        from django.http import Http404
        raise Http404
    url = reverse('professional-public', args=[
        professional.tenant.public_slug or professional.tenant.slug, professional.public_slug])
    if professional.unit_id:
        get_object_or_404(Unit, pk=professional.unit_id, tenant=professional.tenant, active=True)
        url += f'?unit={professional.unit_id}'
    return redirect(url)
