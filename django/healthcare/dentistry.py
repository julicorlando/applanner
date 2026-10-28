"""Tenant-isolated encrypted dental chart and encounter records.

All clinical content is stored using the existing encrypted medical-record
service; no unencrypted patient findings are written to JSON database columns.
"""
import json
from django.core.exceptions import PermissionDenied, ValidationError
from billing.entitlements import module_enabled
from billing.models import TenantModuleAddon, ModuleRequest
from .models import MedicalRecordEntry
from .services import create_record, read_record, assert_clinical_access

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
                          procedures, plan, odontogram, appointment=None, ip=""):
    _require_dentistry(tenant)
    for value in (anamnesis, findings, procedures, plan):
        if not isinstance(value, str) or len(value) > 20000:
            raise ValidationError("Campo clínico inválido ou muito extenso.")
    payload = {"schema": 1, "kind": "dental_encounter",
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
    entries = MedicalRecordEntry.objects.filter(tenant=tenant, customer=customer,
        record_type=MedicalRecordEntry.Type.PROCEDURE).order_by("created_at")
    result = []
    for entry in entries:
        raw = read_record(entry=entry, user=user, ip=ip)
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get("kind") == "dental_encounter":
            result.append({"entry_id": entry.pk, "created_at": entry.created_at, "data": payload})
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
    assert_clinical_access(user)
    _require_dentistry(tenant)
    if user.tenant_id != tenant.pk or user.role not in {"owner", "tenant-admin"}:
        raise PermissionDenied("Somente o responsável da clínica pode solicitar vagas.")
    if module.slug != "dental-professional-extra" or not module.active or not module.addon_sellable:
        raise ValidationError("Adicional odontológico indisponível.")
    monthly_price = module.addon_monthly_price
    if monthly_price is None or monthly_price < Decimal("0"):
        raise ValidationError("Master precisa definir o preço do adicional.")
    return ModuleRequest.objects.create(tenant=tenant, module=module, requested_by=user,
        public_id=public_id, quoted_monthly_price=monthly_price, tenant_note=note[:500])
