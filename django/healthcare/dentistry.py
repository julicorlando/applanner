"""Tenant-isolated encrypted dental chart and encounter records.

All clinical content is stored using the existing encrypted medical-record
service; no unencrypted patient findings are written to JSON database columns.
"""
import json
from django.core.exceptions import PermissionDenied, ValidationError
from billing.entitlements import module_enabled
from billing.models import TenantModuleAddon
from .models import MedicalRecordEntry
from .services import create_record, read_record, assert_clinical_access, clinical_records_for

PERMANENT_TEETH = frozenset(
    f"{quadrant}{tooth}" for quadrant in (1, 2, 3, 4) for tooth in range(1, 9)
)
PRIMARY_TEETH = frozenset(
    f"{quadrant}{tooth}" for quadrant in (5, 6, 7, 8) for tooth in range(1, 6)
)
ALL_TEETH = PERMANENT_TEETH | PRIMARY_TEETH
SURFACES = frozenset(("mesial", "distal", "vestibular", "lingual", "palatina", "oclusal", "incisal", "cervical", "raiz"))
CONDITIONS = frozenset(("higido", "carie", "restauracao", "ausente", "extracao_indicada", "endodontia",
                        "coroa", "implante", "fratura", "selante", "protese", "outro"))


def _require_dentistry(tenant):
    if not module_enabled(tenant, "dentistry"):
        raise PermissionDenied("Módulo de odontologia não habilitado para esta clínica.")


def validate_odontogram(teeth):
    if not isinstance(teeth, dict):
        raise ValidationError("Odontograma deve ser um objeto de dentes.")
    cleaned = {}
    for tooth, observations in teeth.items():
        if tooth not in ALL_TEETH or not isinstance(observations, list):
            raise ValidationError("Dente FDI ou observações inválidos.")
        if len(observations) > 30:
            raise ValidationError("Número excessivo de observações.")
        cleaned[tooth] = []
        for item in observations:
            if not isinstance(item, dict) or item.get("condition") not in CONDITIONS:
                raise ValidationError("Condição odontológica inválida.")
            surfaces = item.get("surfaces", [])
            if not isinstance(surfaces, list) or any(s not in SURFACES for s in surfaces):
                raise ValidationError("Superfícies odontológicas inválidas.")
            note = item.get("note", "")
            if not isinstance(note, str) or len(note) > 2000:
                raise ValidationError("Observação inválida.")
            cleaned[tooth].append({"condition": item["condition"], "surfaces": list(dict.fromkeys(surfaces)), "note": note})
    return cleaned


def save_dental_encounter(*, tenant, customer, professional, user, anamnesis, findings,
                          procedures, plan, odontogram, appointment=None, ip="", clinical_details=None, treatment_plan_reference=None):
    _require_dentistry(tenant)
    if user.tenant_id != tenant.pk and not user.is_superuser:
        raise PermissionDenied("Profissional de outra clínica.")
    if not professional.active:
        raise ValidationError("Profissional inativo.")
    for value in (anamnesis, findings, procedures, plan):
        if not isinstance(value, str) or len(value) > 20000:
            raise ValidationError("Campo clínico inválido ou muito extenso.")
    details=clinical_details or {}
    from .forms import DENTAL_DETAILS
    if not isinstance(details,dict) or any(key not in DENTAL_DETAILS or not isinstance(value,str) or len(value)>20000 for key,value in details.items()):
        raise ValidationError("Detalhes clínicos odontológicos inválidos.")
    if treatment_plan_reference:
        read_record(entry=treatment_plan_reference.entry,user=user,ip=ip)
        if treatment_plan_reference.entry.tenant_id!=tenant.pk or treatment_plan_reference.entry.customer_id!=customer.pk:
            raise PermissionDenied("Plano de outro paciente ou clínica.")
    payload = {"treatment_plan_id":treatment_plan_reference.pk if treatment_plan_reference else None,"clinical_details":details,"schema": 1, "kind": "dental_encounter",
               "anamnesis": anamnesis, "findings": findings,
               "procedures": procedures, "treatment_plan": plan,
               "odontogram": validate_odontogram(odontogram)}
    return create_record(tenant=tenant, customer=customer, professional=professional,
                         user=user, appointment=appointment, title="Evolução odontológica",
                         record_type=MedicalRecordEntry.Type.PROCEDURE,
                         content=json.dumps(payload, ensure_ascii=False), ip=ip)


def dental_history(*, tenant, customer, user, ip=""):
    assert_clinical_access(user)
    _require_dentistry(tenant)
    if user.tenant_id != tenant.pk and not user.is_superuser:
        raise PermissionDenied("Acesso a outra clínica negado.")
    if customer.tenant_id != tenant.pk:
        raise PermissionDenied("Paciente de outra clínica.")
    entries = clinical_records_for(user=user, tenant=tenant).filter(customer=customer,
        record_type=MedicalRecordEntry.Type.PROCEDURE).order_by("created_at")
    result = []
    for entry in entries:
        raw = read_record(entry=entry, user=user, ip=ip)
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get("kind") == "dental_encounter":
            result.append({"entry_id": entry.pk, "created_at": entry.created_at, "professional": entry.professional, "data": payload, "chart_json": json.dumps(payload["odontogram"])})
    return result


def dental_professional_allowance(tenant):
    """One dentist is included; only ACTIVE paid extra seats increase allowance."""
    extras = TenantModuleAddon.objects.filter(tenant=tenant,
        module__slug="dental-professional-extra",
        status=TenantModuleAddon.Status.ACTIVE).values_list("quantity", flat=True).first() or 0
    return 1 + extras


def request_extra_dentist(*, tenant, user, module, public_id, note=""):
    """Creates a request only. Master approval/payment uses the existing billing workflow."""
    from decimal import Decimal
    _require_dentistry(tenant)
    if user.tenant_id != tenant.pk or user.role not in {"owner", "tenant-admin"}:
        raise PermissionDenied("Somente o responsável da clínica pode solicitar vagas.")
    if module.slug != "dental-professional-extra" or not module.active or not module.addon_sellable:
        raise ValidationError("Adicional odontológico indisponível.")
    monthly_price = module.addon_monthly_price
    if monthly_price is None or monthly_price < Decimal("0"):
        raise ValidationError("Master precisa definir o preço do adicional.")
    from billing.module_services import request_module
    return request_module(tenant=tenant,module=module,user=user,note=note)
