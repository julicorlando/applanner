"""Versioned, encrypted physiotherapy assessments; finalize once into the clinical ledger."""

import hashlib
import json
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from core.audit import append_audit
from core.crypto import encrypt_text, decrypt_text
from billing.entitlements import module_enabled, require_module
from scheduling.models import Professional
from .models import (
    PhysiotherapyAssessment,
    PhysiotherapyAssessmentVersion,
    PhysiotherapyAssessmentDocument,
    ClinicalAttachment,
)
from .services import (
    assert_clinical_access,
    clinical_records_for,
    create_record,
    read_record,
)
from .clinical import validate_document_upload


class AssessmentConflict(ValidationError):
    pass


def is_physiotherapy(tenant):
    return (tenant.category or "").strip().lower() == "fisioterapia" or module_enabled(
        tenant, "physiotherapy"
    )


def authorize(user):
    assert_clinical_access(user)
    require_module(user.tenant, "medical_records")
    if not is_physiotherapy(user.tenant):
        raise PermissionDenied("Avaliação exclusiva de Fisioterapia.")


def assessments_for(user):
    authorize(user)
    records = clinical_records_for(user=user, tenant=user.tenant)
    return PhysiotherapyAssessment.objects.filter(tenant_id=user.tenant_id).filter(
        Q(created_by=user, professional__user=user, professional__active=True)
        | Q(status="finalized", final_entry__in=records)
    )


def read_assessment(*, assessment, user, request=None, version=None):
    if not assessments_for(user).filter(pk=assessment.pk).exists():
        raise PermissionDenied("Avaliação sem vínculo autorizado.")
    if version is not None:
        if (
            assessment.created_by_id != user.pk
            or assessment.professional.user_id != user.pk
        ):
            raise PermissionDenied("O histórico de rascunhos é restrito ao autor.")
        text = assessment.versions.get(number=version).payload_encrypted
    elif assessment.status == "finalized":
        text = read_record(entry=assessment.final_entry, user=user)
    else:
        text = assessment.payload_encrypted
    append_audit(
        tenant=assessment.tenant,
        user=user,
        request=request,
        action="clinical.assessment.read",
        entity_type="PhysiotherapyAssessment",
        entity_id=assessment.pk,
        after={"version": version or assessment.version},
    )
    return (
        json.loads(decrypt_text(text))
        if version is not None or assessment.status != "finalized"
        else json.loads(text)
    )


def canonical(payload):
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        cls=DjangoJSONEncoder,
        allow_nan=False,
    )


def clinical_name(professional, registration):
    name = (registration.professional_name or professional.user.get_full_name()).strip()
    if (
        not name
        and professional.name.strip().casefold()
        != professional.tenant.name.strip().casefold()
    ):
        name = professional.name.strip()
    return name


@transaction.atomic
def save_assessment(*, form, user, assessment_id=None, finalize=False, request=None):
    authorize(user)
    if form.user.pk != user.pk or form.finalizing != finalize or not form.is_valid():
        raise ValidationError("Revise os campos da avaliação antes de salvar.")
    data = dict(form.cleaned_data)
    # A single lock order prevents a retry on /new/ from deadlocking an edit.
    professional = Professional.objects.select_for_update().get(
        pk=data["professional"].pk, tenant_id=user.tenant_id, user=user, active=True
    )
    existing = None
    if assessment_id:
        existing = (
            assessments_for(user)
            .select_for_update(of=("self",))
            .select_related("professional", "customer", "final_entry")
            .get(pk=assessment_id)
        )
        if (
            existing.created_by_id != user.pk
            or existing.professional_id != professional.pk
        ):
            raise PermissionDenied
        if existing.status == "finalized":
            if finalize:
                return existing
            raise ValidationError("Avaliação finalizada não pode ser sobrescrita.")
        if existing.version != data["version"]:
            raise AssessmentConflict(
                "Outra sessão salvou esta avaliação. Recarregue a versão atual antes de mesclar suas alterações."
            )
    if existing and existing.submission_key != data["submission_key"]:
        raise PermissionDenied
    if not existing:
        replayed = (
            PhysiotherapyAssessment.objects.select_for_update()
            .filter(submission_key=data["submission_key"])
            .first()
        )
        if replayed:
            if (
                replayed.created_by_id != user.pk
                or replayed.professional_id != professional.pk
                or replayed.customer_id != data["customer"].pk
            ):
                raise PermissionDenied
            if finalize and replayed.status == "finalized":
                return replayed
            raise AssessmentConflict(
                "Este formulário já foi salvo. Abra a avaliação existente antes de continuar."
            )
    patient = data["customer"]
    appointment = data.get("appointment")
    if patient.tenant_id != user.tenant_id:
        raise PermissionDenied
    if existing and (
        existing.customer_id != patient.pk
        or existing.professional_id != professional.pk
    ):
        raise PermissionDenied
    if appointment and (
        appointment.tenant_id != user.tenant_id
        or appointment.customer_id != patient.pk
        or appointment.professional_id != professional.pk
        or appointment.status in {"cancelled", "canceled"}
    ):
        raise ValidationError(
            "O atendimento deve corresponder ao paciente e ao profissional."
        )
    registration = getattr(professional, "clinical_registration", None)
    if finalize:
        if not registration or registration.council != "CREFITO":
            raise ValidationError(
                "Cadastre a identificação CREFITO antes de finalizar."
            )
        registration.full_clean()
        if not clinical_name(professional, registration):
            raise ValidationError(
                "Informe o nome da pessoa responsável na identificação profissional para assinar."
            )
        if (
            not appointment
            or not data.get("attestation")
            or not data.get("chief_complaint")
            or not data.get("goals")
            or not data.get("treatment_plan")
        ):
            raise ValidationError(
                "Finalização exige atendimento, queixa, objetivos, plano e confirmação de autoria."
            )
    snapshot = (
        registration.snapshot()
        if registration
        else {"name": professional.user.get_full_name() or professional.name}
    )
    if registration:
        snapshot["name"] = clinical_name(professional, registration) or snapshot["name"]
    snapshot["user_id"] = user.pk
    attachments = data.pop("documents", [])
    removed = list(data.pop("remove_documents", []))
    for name in (
        "customer",
        "professional",
        "appointment",
        "version",
        "attestation",
        "submission_key",
    ):
        data.pop(name, None)
    signature_image = data.pop("signature_png", "")
    payload = {
        "schema": "applanner.physiotherapy.v2",
        "kind": "physio_assessment",
        "sections": data,
        "signature_png": signature_image,
        "professional": snapshot,
        "patient": {
            "id": patient.pk,
            "name": patient.name,
            "phone": patient.phone,
            "birth_date": patient.birth_date,
        },
        "clinic": {"id": user.tenant_id, "name": user.tenant.name},
    }
    if len(canonical(payload)) > 230000:
        raise ValidationError(
            "A avaliação excede o tamanho permitido. Reduza os textos ou a assinatura."
        )
    row = existing or PhysiotherapyAssessment.objects.create(
        tenant=user.tenant,
        customer=patient,
        professional=professional,
        created_by=user,
        submission_key=form.cleaned_data["submission_key"],
        payload_encrypted=encrypt_text("{}"),
    )
    for document in removed:
        if document.assessment_id != row.pk or document.removed_at:
            raise PermissionDenied
        document.removed_at = timezone.now()
        document.save(update_fields=["removed_at"])
        append_audit(
            tenant=user.tenant,
            user=user,
            request=request,
            action="clinical.assessment.document.unlinked",
            entity_type="PhysiotherapyAssessmentDocument",
            entity_id=document.pk,
        )
    cipher = Fernet(settings.FIELD_ENCRYPTION_KEY.encode())
    for upload in attachments:
        raw, mime, filename = validate_document_upload(upload=upload)
        document = PhysiotherapyAssessmentDocument.objects.create(
            assessment=row,
            filename_encrypted=encrypt_text(filename),
            content_encrypted=cipher.encrypt(raw),
            mime_type=mime,
            sha256=hashlib.sha256(raw).hexdigest(),
            size=len(raw),
            uploaded_by=user,
        )
        append_audit(
            tenant=user.tenant,
            user=user,
            request=request,
            action="clinical.assessment.document.attached",
            entity_type="PhysiotherapyAssessmentDocument",
            entity_id=document.pk,
            after={"sha256": document.sha256},
        )
    documents = list(row.documents.filter(removed_at__isnull=True).order_by("pk"))
    if len(documents) > 20 or sum(d.size for d in documents) > 50 * 1024 * 1024:
        raise ValidationError(
            "Uma avaliação aceita até 20 documentos, totalizando no máximo 50 MB."
        )
    payload["documents"] = [
        {
            "id": d.pk,
            "filename": decrypt_text(d.filename_encrypted),
            "sha256": d.sha256,
            "size": d.size,
        }
        for d in documents
    ]
    row.version += 1
    payload["revision"] = row.version
    if finalize:
        now = timezone.now()
        payload["signature"] = {
            "signed_by": user.pk,
            "name": snapshot["name"],
            "council": "CREFITO",
            "number": registration.number,
            "jurisdiction": registration.jurisdiction,
            "signed_at": now.isoformat(),
            "payload_sha256": hashlib.sha256(canonical(payload).encode()).hexdigest(),
            "attested": True,
            "method": "authenticated_professional_attestation",
        }
        text = canonical(payload)
        entry = create_record(
            tenant=user.tenant,
            customer=patient,
            professional=professional,
            user=user,
            appointment=appointment,
            title="Avaliação fisioterapêutica — " + str(data["evaluation_date"]),
            record_type="physio_evaluation",
            content=text,
            physiotherapy_assessment=row,
        )
        for document in documents:
            document.final_document = ClinicalAttachment.objects.create(
                entry=entry,
                kind="document",
                filename_encrypted=document.filename_encrypted,
                content_encrypted=document.content_encrypted,
                mime_type=document.mime_type,
                sha256=document.sha256,
                size=document.size,
                uploaded_by=document.uploaded_by,
            )
            document.save(update_fields=["final_document"])
        row.status = "finalized"
        row.final_entry = entry
        row.signed_at = now
    else:
        text = canonical(payload)
    row.appointment = appointment
    row.payload_encrypted = encrypt_text(text)
    row.save()
    fingerprint = hashlib.sha256(text.encode()).hexdigest()
    PhysiotherapyAssessmentVersion.objects.create(
        assessment=row,
        number=row.version,
        status=row.status,
        payload_encrypted=row.payload_encrypted,
        sha256=fingerprint,
        created_by=user,
    )
    append_audit(
        tenant=user.tenant,
        user=user,
        request=request,
        action="clinical.assessment.finalized"
        if finalize
        else "clinical.assessment.draft.saved",
        entity_type="PhysiotherapyAssessment",
        entity_id=row.pk,
        after={
            "version": row.version,
            "status": row.status,
            "sha256": fingerprint,
            "entry_id": row.final_entry_id,
        },
    )
    return row


def read_assessment_document(*, document, user, request=None):
    read_assessment(assessment=document.assessment, user=user, request=request)
    if document.removed_at:
        raise PermissionDenied("Documento desvinculado do rascunho.")
    raw = Fernet(settings.FIELD_ENCRYPTION_KEY.encode()).decrypt(
        bytes(document.content_encrypted)
    )
    if hashlib.sha256(raw).hexdigest() != document.sha256:
        raise ValidationError("Integridade do documento inválida.")
    append_audit(
        tenant=user.tenant,
        user=user,
        request=request,
        action="clinical.assessment.document.downloaded",
        entity_type="PhysiotherapyAssessmentDocument",
        entity_id=document.pk,
    )
    return raw, decrypt_text(document.filename_encrypted)
