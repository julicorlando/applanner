"""Regras do plano de tratamento e da evolução clínica odontológica.

Transições permitidas:
  Plano:     PLANEJADO <-> EM_ORCAMENTO -> EXECUTADO (gera evolução em rascunho)
             EXECUTADO -> PLANEJADO só se o rascunho gerado for excluído.
  Evolução:  RASCUNHO -> FINALIZADO (botão ou após DENTAL_EVOLUTION_DRAFT_HOURS)
             FINALIZADO -> RETIFICADO (motivo obrigatório + novo registro ligado ao original)

Toda criação, edição de rascunho, exclusão de rascunho, finalização e retificação grava AuditLog
(usuário, data/hora, IP, user-agent e estado anterior/novo). O estado registrado no log leva o
hash do conteúdo clínico, nunca o texto: o prontuário continua criptografado."""
import hashlib
import json
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from core.audit import append_audit
from core.crypto import decrypt_text, encrypt_text

from .evolution_models import DentalEvolution, DentalPlanItem, PatientNoteRectification

MANAGERS = {"owner", "tenant-admin", "manager"}
TEXT_FIELDS = ("procedure", "orthodontic", "notes")
REASON_MIN, REASON_MAX = 5, 300


def draft_hours():
    return max(1, int(getattr(settings, "DENTAL_EVOLUTION_DRAFT_HOURS", 12)))


def _author_name(user):
    return ((user.get_full_name() if hasattr(user, "get_full_name") else "") or user.email or str(user.pk))[:160]


def _dec(value):
    return decrypt_text(value) if value else ""


def evolution_text(evolution):
    return {key: _dec(getattr(evolution, f"{key}_encrypted")) for key in TEXT_FIELDS}


def _canonical(evolution):
    text = evolution_text(evolution)
    return json.dumps({"tooth": evolution.tooth, "clinical_date": evolution.clinical_date.isoformat(),
                       "professional_id": evolution.professional_id, "plan_item_id": evolution.plan_item_id,
                       "previous_id": evolution.previous_id, **text},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(evolution):
    return hashlib.sha256(_canonical(evolution).encode()).hexdigest()


def audit_state(evolution):
    """Estado anterior/novo para o log: metadados + hash do conteúdo (sem texto clínico)."""
    return {"status": evolution.status, "tooth": evolution.tooth, "clinical_date": evolution.clinical_date,
            "professional_id": evolution.professional_id, "plan_item_id": evolution.plan_item_id,
            "previous_id": evolution.previous_id, "content_sha256": _sha(evolution),
            "finalized_at": evolution.finalized_at, "rectified_at": evolution.rectified_at,
            "rectified_by_id": evolution.rectified_by_id}


def plan_state(item):
    return {"status": item.status, "tooth": item.tooth, "price": item.price, "position": item.position,
            "professional_id": item.professional_id,
            "procedure_sha256": hashlib.sha256(_dec(item.procedure_encrypted).encode()).hexdigest()}


def _audit(*, tenant, user, request, action, entity, before=None, after=None):
    append_audit(tenant=tenant, user=user, request=request, action=action, entity_type=type(entity).__name__,
                 entity_id=entity.pk, before=before, after=after)


def clean_fields(data):
    """Validate the clinical fields typed by the professional."""
    tooth = " ".join(str(data.get("tooth") or "").split())[:20]
    out = {key: str(data.get(key) or "").strip()[:4000] for key in TEXT_FIELDS}
    if not any(len(out[key]) >= 3 for key in TEXT_FIELDS):
        raise ValidationError("Escreva o procedimento, o tratamento ortodôntico ou uma observação.")
    day = data.get("clinical_date") or timezone.localdate()
    if day > timezone.localdate():
        raise ValidationError("A data não pode ser no futuro.")
    return {"tooth": tooth, "clinical_date": day, "professional": data.get("professional"), **out}


def _apply(evolution, fields):
    evolution.tooth = fields["tooth"]
    evolution.clinical_date = fields["clinical_date"]
    evolution.professional = fields.get("professional")
    for key in TEXT_FIELDS:
        setattr(evolution, f"{key}_encrypted", encrypt_text(fields[key]) if fields[key] else "")


def _check_patient(user, patient):
    if patient.tenant_id != user.tenant_id:
        raise PermissionDenied("Paciente de outra clínica.")


def _check_professional(user, professional):
    if professional is not None and (professional.tenant_id != user.tenant_id or not professional.active):
        raise PermissionDenied("Profissional de outra clínica.")


def _lock(model, pk, user):
    row = model._base_manager.select_for_update().filter(pk=pk, tenant_id=user.tenant_id).first()
    if row is None:
        raise PermissionDenied("Registro não encontrado nesta clínica.")
    return row


# ---------------------------------------------------------------- evolução: rascunho

@transaction.atomic
def create_draft(*, user, patient, data, plan_item=None, request=None):
    _check_patient(user, patient)
    fields = clean_fields(data)
    _check_professional(user, fields.get("professional"))
    evolution = DentalEvolution(tenant_id=user.tenant_id, customer=patient, created_by=user,
                                author_name=_author_name(user), plan_item=plan_item)
    _apply(evolution, fields)
    evolution.save()
    _audit(tenant=user.tenant, user=user, request=request, action="clinical.dental.evolution.created",
           entity=evolution, after=audit_state(evolution))
    return evolution


def _own_draft(evolution_id, user):
    evolution = _lock(DentalEvolution, evolution_id, user)
    if evolution.status != DentalEvolution.Status.DRAFT:
        raise ValidationError("Este lançamento já foi finalizado. Use “Retificar lançamento”.")
    if evolution.created_by_id != user.pk:
        raise PermissionDenied("Somente quem lançou edita ou exclui o rascunho.")
    if _expired(evolution):
        # The page finalizes it on the next load (finalize_expired); here we only refuse the change.
        raise ValidationError(f"O rascunho passou de {draft_hours()} horas e foi finalizado. Use “Retificar lançamento”.")
    return evolution


@transaction.atomic
def update_draft(*, user, evolution_id, data, request=None):
    evolution = _own_draft(evolution_id, user)
    before = audit_state(evolution)
    fields = clean_fields(data)
    _check_professional(user, fields.get("professional"))
    _apply(evolution, fields)
    evolution.save()
    _audit(tenant=user.tenant, user=user, request=request, action="clinical.dental.evolution.draft_updated",
           entity=evolution, before=before, after=audit_state(evolution))
    return evolution


@transaction.atomic
def delete_draft(*, user, evolution_id, request=None):
    evolution = _own_draft(evolution_id, user)
    before = audit_state(evolution)
    item = evolution.plan_item
    pk = evolution.pk
    evolution.delete()
    evolution.pk = pk
    _audit(tenant=user.tenant, user=user, request=request, action="clinical.dental.evolution.draft_deleted",
           entity=evolution, before=before)
    # The plan item comes back to the plan when its only (draft) evolution is discarded.
    if item and not item.evolutions.exists():
        item = DentalPlanItem._base_manager.select_for_update().get(pk=item.pk)
        item_before = plan_state(item)
        item.status, item.executed_at, item.executed_by = DentalPlanItem.Status.PLANNED, None, None
        item.save()
        _audit(tenant=user.tenant, user=user, request=request, action="clinical.dental.plan_item.reopened",
               entity=item, before=item_before, after=plan_state(item))


# ---------------------------------------------------------------- evolução: finalização

def _expired(evolution, now=None):
    return evolution.created_at <= (now or timezone.now()) - timedelta(hours=draft_hours())


@transaction.atomic
def finalize(evolutions, *, user=None, automatic=False, request=None):
    done = []
    for evolution in evolutions:
        evolution = DentalEvolution._base_manager.select_for_update().get(pk=evolution.pk)
        if evolution.status != DentalEvolution.Status.DRAFT:
            continue
        before = audit_state(evolution)
        evolution.status = DentalEvolution.Status.FINALIZED
        evolution.finalized_at = timezone.now()
        evolution.finalized_by = None if automatic else user
        evolution.finalized_automatically = automatic
        evolution.content_sha256 = _sha(evolution)
        evolution.save()
        _audit(tenant=evolution.tenant, user=None if automatic else user, request=request,
               action="clinical.dental.evolution.auto_finalized" if automatic else "clinical.dental.evolution.finalized",
               entity=evolution, before=before, after=audit_state(evolution))
        done.append(evolution)
    return done


def finalize_attendance(*, user, patient, request=None):
    """“Salvar e finalizar atendimento”: fecha todos os rascunhos do usuário para este paciente."""
    _check_patient(user, patient)
    drafts = DentalEvolution.objects.filter(tenant_id=user.tenant_id, customer=patient, created_by=user,
                                            status=DentalEvolution.Status.DRAFT)
    return finalize(list(drafts), user=user, request=request)


def finalize_expired(*, customer=None, now=None):
    limit = (now or timezone.now()) - timedelta(hours=draft_hours())
    drafts = DentalEvolution.objects.filter(status=DentalEvolution.Status.DRAFT, created_at__lte=limit)
    if customer is not None:
        drafts = drafts.filter(customer=customer)
    return len(finalize(list(drafts.order_by("pk")[:500]), automatic=True))


# ---------------------------------------------------------------- evolução: retificação

def can_rectify(user, author_id):
    return user.pk == author_id or getattr(user, "role", "") in MANAGERS


def _clean_reason(reason):
    reason = " ".join(str(reason or "").split())
    if not REASON_MIN <= len(reason) <= REASON_MAX:
        raise ValidationError(f"Informe o motivo da retificação ({REASON_MIN} a {REASON_MAX} caracteres).")
    return reason


def _correction(*, user, original_patient, fields, plan_item=None, previous=None):
    """The corrected record is born finalized: it is an addendum signed by whoever rectified."""
    evolution = DentalEvolution(tenant_id=user.tenant_id, customer=original_patient, created_by=user,
                                author_name=_author_name(user), plan_item=plan_item, previous=previous)
    _apply(evolution, fields)
    evolution.status = DentalEvolution.Status.FINALIZED
    evolution.finalized_at = timezone.now()
    evolution.finalized_by = user
    evolution.content_sha256 = _sha(evolution)
    evolution.save()
    return evolution


@transaction.atomic
def rectify(*, user, evolution_id, reason, data, request=None):
    original = _lock(DentalEvolution, evolution_id, user)
    if original.status != DentalEvolution.Status.FINALIZED:
        raise ValidationError("Somente lançamentos finalizados são retificados; rascunhos se editam direto.")
    if not can_rectify(user, original.created_by_id):
        raise PermissionDenied("Somente quem lançou ou a gestão da clínica retifica este lançamento.")
    reason = _clean_reason(reason)
    fields = clean_fields(data)
    _check_professional(user, fields.get("professional"))
    before = audit_state(original)
    original.status = DentalEvolution.Status.RECTIFIED
    original.rectified_at = timezone.now()
    original.rectified_by = user
    original.rectification_reason_encrypted = encrypt_text(reason)
    original.save()
    correction = _correction(user=user, original_patient=original.customer, fields=fields,
                             plan_item=original.plan_item, previous=original)
    reason_hash = hashlib.sha256(reason.encode()).hexdigest()
    _audit(tenant=user.tenant, user=user, request=request, action="clinical.dental.evolution.rectified",
           entity=original, before=before, after={**audit_state(original), "replaced_by": correction.pk,
                                                  "reason_sha256": reason_hash})
    _audit(tenant=user.tenant, user=user, request=request, action="clinical.dental.evolution.created",
           entity=correction, after={**audit_state(correction), "rectifies": original.pk})
    return correction


@transaction.atomic
def rectify_note(*, user, note, reason, data, request=None):
    """Evoluções antigas (PatientNote) ficam intactas; a retificação as marca e cria o registro novo."""
    from .document_models import PatientNote
    note = PatientNote.objects.select_for_update().get(pk=note.pk, tenant_id=user.tenant_id)
    if PatientNoteRectification.objects.filter(note=note).exists():
        raise ValidationError("Este lançamento já foi retificado.")
    if not can_rectify(user, note.author_id):
        raise PermissionDenied("Somente quem lançou ou a gestão da clínica retifica este lançamento.")
    reason = _clean_reason(reason)
    fields = clean_fields(data)
    _check_professional(user, fields.get("professional"))
    correction = _correction(user=user, original_patient=note.customer, fields=fields)
    link = PatientNoteRectification.objects.create(note=note, replacement=correction, reason_encrypted=encrypt_text(reason),
                                                   rectified_by=user)
    raw = decrypt_text(note.text_encrypted)
    append_audit(tenant=user.tenant, user=user, request=request, action="clinical.dental.patient_note.rectified",
                 entity_type="PatientNote", entity_id=note.pk,
                 before={"status": "finalized", "content_sha256": hashlib.sha256(raw.encode()).hexdigest()},
                 after={"status": "rectified", "replaced_by": correction.pk, "rectification_id": link.pk,
                        "reason_sha256": hashlib.sha256(reason.encode()).hexdigest()})
    _audit(tenant=user.tenant, user=user, request=request, action="clinical.dental.evolution.created",
           entity=correction, after={**audit_state(correction), "rectifies_note": note.pk})
    return correction


# ---------------------------------------------------------------- plano de tratamento

def plan_items(tenant, patient):
    return DentalPlanItem.objects.filter(tenant=tenant, customer=patient).select_related("professional")


@transaction.atomic
def save_plan(*, user, patient, rows, professional=None, request=None):
    """Sincroniza a tabela do plano. rows: [{id|None, tooth, procedure, price, status}] na ordem da tela.
    Itens editáveis ausentes de rows são apagados (é orçamento, não prontuário)."""
    _check_patient(user, patient)
    _check_professional(user, professional)
    current = {item.pk: item for item in DentalPlanItem._base_manager.select_for_update()
               .filter(tenant_id=user.tenant_id, customer=patient)}
    kept = set()
    allowed_status = {DentalPlanItem.Status.PLANNED, DentalPlanItem.Status.QUOTED}
    for position, row in enumerate(rows):
        status = row.get("status") or DentalPlanItem.Status.PLANNED
        if status not in allowed_status:
            raise ValidationError("Use “Executar” para registrar o procedimento na evolução.")
        price = Decimal(row["price"])
        item = current.get(row.get("id")) if row.get("id") else None
        if row.get("id") and item is None:
            raise PermissionDenied("Item de outro paciente.")
        if item is not None:
            kept.add(item.pk)
            if item.status not in DentalPlanItem.EDITABLE:
                continue  # executed rows are read-only; ignore whatever was posted
            if (item.tooth, _dec(item.procedure_encrypted), item.price, item.status, item.position, item.professional_id) == (
                    row["tooth"], row["procedure"], price, status, position, getattr(professional, "pk", None)):
                continue
            before = plan_state(item)
            item.tooth, item.price, item.status, item.position = row["tooth"], price, status, position
            item.procedure_encrypted = encrypt_text(row["procedure"])
            item.professional = professional
            item.save()
            _audit(tenant=user.tenant, user=user, request=request, action="clinical.dental.plan_item.updated",
                   entity=item, before=before, after=plan_state(item))
        else:
            item = DentalPlanItem.objects.create(tenant_id=user.tenant_id, customer=patient, professional=professional,
                                                 tooth=row["tooth"], procedure_encrypted=encrypt_text(row["procedure"]),
                                                 price=price, status=status, position=position, created_by=user)
            kept.add(item.pk)
            _audit(tenant=user.tenant, user=user, request=request, action="clinical.dental.plan_item.created",
                   entity=item, after=plan_state(item))
    for pk, item in current.items():
        if pk in kept or item.status not in DentalPlanItem.EDITABLE:
            continue
        before = plan_state(item)
        item.delete()
        item.pk = pk
        _audit(tenant=user.tenant, user=user, request=request, action="clinical.dental.plan_item.deleted",
               entity=item, before=before)


@transaction.atomic
def execute_plan_item(*, user, item_id, data=None, request=None):
    """Marca o item como executado e abre a evolução correspondente em rascunho."""
    item = _lock(DentalPlanItem, item_id, user)
    if item.status not in DentalPlanItem.EDITABLE:
        raise ValidationError("Este item já foi executado.")
    before = plan_state(item)
    item.status = DentalPlanItem.Status.EXECUTED
    item.executed_at = timezone.now()
    item.executed_by = user
    item.save()
    _audit(tenant=user.tenant, user=user, request=request, action="clinical.dental.plan_item.executed",
           entity=item, before=before, after=plan_state(item))
    fields = {"tooth": item.tooth, "procedure": _dec(item.procedure_encrypted), "professional": item.professional,
              **(data or {})}
    return create_draft(user=user, patient=item.customer, data=fields, plan_item=item, request=request)
