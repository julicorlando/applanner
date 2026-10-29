import hashlib
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from core.crypto import encrypt_text, decrypt_text
from billing.entitlements import require_module
from .models import MedicalRecordAccessLog, MedicalRecordEntry


CLINICAL_ROLES = {"owner", "manager", "tenant-admin", "professional", "healthcare"}


def assert_clinical_access(user):
    # Platform administration is not a clinical authorization.
    from scheduling.models import Professional
    if (not user.is_authenticated or not user.is_active or not user.tenant_id
            or user.role not in CLINICAL_ROLES
            or not Professional.objects.filter(user=user, tenant_id=user.tenant_id, active=True).exists()):
        raise PermissionDenied("Acesso restrito a profissional clínico ativo e vinculado à empresa.")


def _ip_hash(ip):
    return hashlib.sha256((ip or "").encode()).hexdigest() if ip else ""


def clinical_records_for(*, user, tenant):
    assert_clinical_access(user)
    if user.tenant_id != tenant.pk:
        raise PermissionDenied("Acesso a outra clínica negado.")
    # Only the responsible clinician may access the record. Shared-care grants
    # require an explicit authorization workflow, never an administrative bypass.
    from .models import ClinicalCareGrant
    grants=ClinicalCareGrant.objects.filter(tenant=tenant,grantee__user=user,
        grantee__active=True,revoked_at__isnull=True).values_list("customer_id","source_professional_id","granted_by_id")
    scope=Q(professional__user=user,professional_snapshot__user_id=user.pk)
    # A previous release may insert without the newly added snapshot column.
    # Its immutable author must still match the current professional login.
    scope |= Q(professional__user=user,created_by=user,professional_snapshot={})
    for patient_id,professional_id,author_id in grants:
        scope |= Q(customer_id=patient_id,professional_id=professional_id) & (Q(professional_snapshot__user_id=author_id) | Q(created_by_id=author_id,professional_snapshot={}))
    return MedicalRecordEntry.objects.filter(scope,tenant=tenant)


@transaction.atomic
def create_record(*, tenant, customer, professional, title, content, user,
                  appointment=None, record_type="evolution", ip="", supersedes=None,
                  correction_reason=""):
    assert_clinical_access(user)
    require_module(tenant, "medical_records")
    if (user.tenant_id != tenant.pk or customer.tenant_id != tenant.pk
            or professional.tenant_id != tenant.pk or professional.user_id != user.pk
            or not professional.active):
        raise PermissionDenied("Paciente/profissional sem vínculo clínico autorizado.")
    if appointment and (appointment.tenant_id != tenant.pk
            or appointment.customer_id != customer.pk
            or appointment.professional_id != professional.pk):
        raise PermissionDenied("Agendamento não corresponde ao paciente e profissional.")
    if record_type not in MedicalRecordEntry.Type.values:
        raise ValidationError("Tipo de registro clínico inválido.")
    if not isinstance(content, str) or not content.strip() or len(content) > 250000:
        raise ValidationError("Conteúdo clínico vazio ou muito extenso.")
    if supersedes:
        read_record(entry=supersedes, user=user, ip=ip)
        if (supersedes.tenant_id != tenant.pk or supersedes.customer_id != customer.pk
                or supersedes.professional_id != professional.pk):
            raise PermissionDenied("Retificação não corresponde ao registro original.")
        if not correction_reason.strip():
            raise ValidationError("Informe o motivo da retificação.")
    entry = MedicalRecordEntry.objects.create(
        tenant=tenant, customer=customer, professional=professional, appointment=appointment,
        record_type=record_type, title=title[:190], content_encrypted=encrypt_text(content),
        created_by=user, supersedes=supersedes,
        professional_snapshot={**(professional.clinical_registration.snapshot() if hasattr(professional,"clinical_registration") else {"name":professional.name}),"user_id":user.pk},
        correction_reason_encrypted=encrypt_text(correction_reason) if supersedes else "",
    )
    MedicalRecordAccessLog.objects.create(
        tenant=tenant, entry=entry, user=user,
        action=MedicalRecordAccessLog.Action.CREATE, ip_hash=_ip_hash(ip),
    )
    return entry


@transaction.atomic
def read_record(*, entry, user, ip=""):
    if not clinical_records_for(user=user, tenant=entry.tenant).filter(pk=entry.pk).exists():
        raise PermissionDenied("Acesso sem vínculo com o atendimento negado.")
    MedicalRecordAccessLog.objects.create(
        tenant=entry.tenant, entry=entry, user=user,
        action=MedicalRecordAccessLog.Action.VIEW, ip_hash=_ip_hash(ip),
    )
    return decrypt_text(entry.content_encrypted)
