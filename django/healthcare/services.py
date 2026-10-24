import hashlib
from django.core.exceptions import PermissionDenied
from core.crypto import encrypt_text,decrypt_text
from billing.entitlements import require_module
from .models import MedicalRecordAccessLog,MedicalRecordEntry


CLINICAL_ROLES={"owner","manager","tenant-admin","professional","healthcare"}


def assert_clinical_access(user):
    if not user.is_superuser and getattr(user,"role",None) not in CLINICAL_ROLES:
        raise PermissionDenied("Acesso restrito à equipe clínica autorizada.")


def _ip_hash(ip):
    return hashlib.sha256((ip or "").encode()).hexdigest() if ip else ""


def create_record(*,tenant,customer,professional,title,content,user,appointment=None,record_type="evolution",ip=""):
    assert_clinical_access(user)
    require_module(tenant,"medical_records")
    if customer.tenant_id!=tenant.id or professional.tenant_id!=tenant.id:
        raise PermissionDenied("Paciente/profissional pertence a outro tenant.")
    if appointment and (appointment.tenant_id!=tenant.id or appointment.customer_id!=customer.id):
        raise PermissionDenied("O agendamento não corresponde ao paciente desta empresa.")
    entry=MedicalRecordEntry.objects.create(
        tenant=tenant,customer=customer,professional=professional,appointment=appointment,
        record_type=record_type,title=title[:190],content_encrypted=encrypt_text(content),created_by=user,
    )
    MedicalRecordAccessLog.objects.create(
        tenant=tenant,entry=entry,user=user,action=MedicalRecordAccessLog.Action.CREATE,ip_hash=_ip_hash(ip)
    )
    return entry


def read_record(*,entry,user,ip=""):
    _assert_clinical_access(user)
    if user.tenant_id!=entry.tenant_id and not user.is_superuser:
        raise PermissionDenied("Acesso negado.")
    MedicalRecordAccessLog.objects.create(
        tenant=entry.tenant,entry=entry,user=user,action=MedicalRecordAccessLog.Action.VIEW,ip_hash=_ip_hash(ip)
    )
    return decrypt_text(entry.content_encrypted)
