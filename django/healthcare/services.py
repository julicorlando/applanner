import hashlib
from django.core.exceptions import PermissionDenied
from core.crypto import encrypt_text,decrypt_text
from billing.entitlements import require_module
from .models import MedicalRecordAccessLog,MedicalRecordEntry


def _ip_hash(ip):
    return hashlib.sha256((ip or "").encode()).hexdigest() if ip else ""


def create_record(*,tenant,customer,professional,title,content,user,appointment=None,record_type="evolution",ip=""):
    require_module(tenant,"medical_records")
    if customer.tenant_id!=tenant.id or professional.tenant_id!=tenant.id:
        raise PermissionDenied("Paciente/profissional pertence a outro tenant.")
    entry=MedicalRecordEntry.objects.create(
        tenant=tenant,customer=customer,professional=professional,appointment=appointment,
        record_type=record_type,title=title[:190],content_encrypted=encrypt_text(content),created_by=user,
    )
    MedicalRecordAccessLog.objects.create(
        tenant=tenant,entry=entry,user=user,action=MedicalRecordAccessLog.Action.CREATE,ip_hash=_ip_hash(ip)
    )
    return entry


def read_record(*,entry,user,ip=""):
    if user.tenant_id!=entry.tenant_id and not user.is_superuser:
        raise PermissionDenied("Acesso negado.")
    MedicalRecordAccessLog.objects.create(
        tenant=entry.tenant,entry=entry,user=user,action=MedicalRecordAccessLog.Action.VIEW,ip_hash=_ip_hash(ip)
    )
    return decrypt_text(entry.content_encrypted)
