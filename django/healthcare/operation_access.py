from django.core.exceptions import PermissionDenied
from accounts.permissions import has_capability
from billing.entitlements import is_healthcare_tenant, module_enabled
from .services import assert_clinical_access

ADMIN = {'owner', 'tenant-admin', 'manager'}
STAFF = ADMIN | {'reception', 'professional', 'healthcare'}


def operator(user):
    if (not user.is_authenticated or not user.is_active or user.is_superuser
            or not user.tenant_id or user.role not in STAFF or not is_healthcare_tenant(user.tenant)
            or user.tenant.archived_at or user.tenant.deleted_at):
        raise PermissionDenied('Acesso restrito à equipe ativa da clínica.')
    if not has_capability(user, 'agenda.manage'):
        raise PermissionDenied('Sem permissão para agenda.')
    if user.role in {'professional', 'healthcare'}:
        assert_clinical_access(user)
    return user.tenant


def appointments_for(user):
    from scheduling.models import Appointment
    tenant = operator(user)
    rows = Appointment.objects.filter(tenant=tenant)
    if user.role in {'professional', 'healthcare'}:
        rows = rows.filter(professional__user=user, professional__active=True)
    return rows


def can_read_clinical(user):
    if not module_enabled(user.tenant, 'medical_records'):
        return False
    try:
        assert_clinical_access(user)
    except PermissionDenied:
        return False
    return True


def can_receive(user):
    return module_enabled(user.tenant, 'finance') and (
        has_capability(user, 'finance.manage') or user.role in {'professional', 'healthcare'})
