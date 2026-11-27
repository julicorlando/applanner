"""Prontuário do paciente (odontologia): uma página com o cadastro, a evolução clínica, o plano de
tratamento, os documentos emitidos e os pagamentos, agrupados por dia.
Cada dentista vê os próprios pacientes e registros; a recepção e a gestão veem e editam todos.
Receber um valor aqui lança a linha na folha do caixa como paga.

Evolução clínica (evolution_services): nasce RASCUNHO (o autor edita/exclui), vira FINALIZADO
(imutável) no botão "Salvar e finalizar atendimento" ou após DENTAL_EVOLUTION_DRAFT_HOURS, e só
muda por "Retificar lançamento" (original RETIFICADO preservado + novo registro ligado a ele).
O plano de tratamento é orçamento: fica no próprio quadro e não entra no histórico até ser executado.
Every read of clinical content is logged (MedicalRecordAccessLog / audit trail)."""
import json
import uuid
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache

from accounts.permissions import has_capability
from billing.entitlements import module_enabled, require_module
from core.audit import append_audit
from core.crypto import decrypt_text
from scheduling.models import Appointment, Customer, Professional

from .dental_assessment_forms import TEXT_FIELDS
from .document_models import KINDS as DOCUMENT_KINDS, ClinicalIssuedDocument, PatientNote
from .evolution_models import DentalEvolution, DentalPlanItem, PatientNoteRectification
from .evolution_services import (can_rectify, clean_fields, create_draft, delete_draft, draft_hours, evolution_text,
                                 execute_plan_item, finalize_attendance, finalize_expired, plan_items, rectify,
                                 rectify_note, save_plan, update_draft, void, void_note)
from .models import DentalAssessment, MedicalRecordAccessLog, MedicalRecordEntry
from .navigation import dental_workspace, shell_context
from .services import _ip_hash, assert_clinical_access

CLINIC_TEAM = {"owner", "tenant-admin", "manager", "reception"}
SECTION_ORDER = ["initial_evolution", "orthodontic_treatment", "complementary_notes", "findings", "chief_complaint", "guidance"]
LEGACY_KEYS = {"procedures": "Procedimento clínico", "findings": "Exame clínico", "anamnesis": "Anamnese",
               "treatment_plan": "Plano de tratamento", "notes": "Observações", "content": "Registro"}
PHYSIO_TYPES = {"physio_evaluation", "physio_evolution"}


def is_clinical(user):
    try:
        assert_clinical_access(user)
        return True
    except PermissionDenied:
        return False


def team_member(user):
    """Non-clinical staff allowed to work with the shared dental record."""
    if user.role not in CLINIC_TEAM:
        return False
    return user.role != "reception" or has_capability(user, "agenda.manage")


def access(user):
    """Dental clinics share one record per patient among dentists and the front desk."""
    if (not user.is_authenticated or not user.is_active or user.is_superuser or not user.tenant_id
            or user.tenant.archived_at or user.tenant.deleted_at):
        raise PermissionDenied
    tenant = user.tenant
    if not dental_workspace(tenant):
        raise PermissionDenied("Prontuário compartilhado disponível para clínicas odontológicas.")
    require_module(tenant, "dentistry")
    require_module(tenant, "medical_records")
    clinical = is_clinical(user)
    if not clinical and not team_member(user):
        raise PermissionDenied("Acesso restrito à equipe da clínica.")
    return tenant, clinical


def shared_patients(user):
    """Patients this user may open: each dentist sees their own; the front desk and managers see all."""
    try:
        tenant, clinical = access(user)
    except PermissionDenied:
        return Customer.objects.none()
    if clinical:
        from .patient_scope import patients_for
        return patients_for(user)
    return Customer.objects.filter(tenant=tenant)


def _read_entry(entry, user, ip):
    MedicalRecordAccessLog.objects.create(tenant=entry.tenant, entry=entry, user=user,
                                          action=MedicalRecordAccessLog.Action.VIEW, ip_hash=_ip_hash(ip))
    return decrypt_text(entry.content_encrypted)


def _payload_sections(payload):
    sections = payload.get("sections") if isinstance(payload, dict) else None
    out = []
    if isinstance(sections, dict):
        for key in SECTION_ORDER + [k for k in TEXT_FIELDS if k not in SECTION_ORDER]:
            value = sections.get(key)
            if isinstance(value, str) and value.strip():
                out.append((TEXT_FIELDS[key], value.strip()))
        plan = sections.get("treatment_plan")
        if isinstance(plan, list):
            items = [str(item.get("text", "")).strip() for item in plan if isinstance(item, dict)]
            items = [item for item in items if item]
            if items:
                out.append(("Plano de tratamento", "\n".join(items)))
        return out
    if isinstance(payload, dict):
        for key, label in LEGACY_KEYS.items():
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                out.append((label, value.strip()))
    return out


def _entry_sections(text):
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return [("Registro", text.strip())] if (text or "").strip() else []
    sections = _payload_sections(payload)
    if not sections and isinstance(payload, str) and payload.strip():
        sections = [("Registro", payload.strip())]
    return sections


def _author(professional, snapshot=None):
    snapshot = snapshot or {}
    registration = getattr(professional, "clinical_registration", None)
    name = (snapshot.get("name") or (registration.professional_name if registration else "")
            or (professional.user.get_full_name() if professional.user_id else "") or professional.name)
    council = ""
    if registration and registration.number:
        council = f"{registration.council}-{registration.jurisdiction} {registration.number}"
    return f"{name} · {council}" if council else name


def _local_day(value):
    return timezone.localtime(value).date()


def _person(user):
    return (user.get_full_name() or user.email) if user else "Sistema"


def _writer(stored, user):
    """Records saved while the user had no name show the e-mail; once the clinic registers the name, show it."""
    if user is not None and stored in {"", user.email} and user.get_full_name():
        return user.get_full_name()
    return stored


def _fill(tooth, procedure, orthodontic, notes, day, professional_id):
    """Prefill of the edit/rectify dialog (the same text the page already shows)."""
    return json.dumps({"tooth": tooth or "", "procedure": procedure or "", "orthodontic": orthodontic or "",
                       "notes": notes or "", "clinical_date": day.isoformat(), "professional": professional_id or ""},
                      ensure_ascii=False)


def _evolution_sections(text, tooth=""):
    out = [("Dente", tooth)] if tooth else []
    return out + [(label, text[key]) for key, label in EVOLUTION_LABELS if text.get(key)]


def evolution_view(evolution, user, can_evolve=False):
    text = evolution_text(evolution)
    previous = evolution.previous
    note_link = getattr(evolution, "replaces_note", None) if evolution.previous_id is None else None
    row = {
        "id": evolution.pk, "status": evolution.status, "status_label": evolution.get_status_display(),
        "sections": _evolution_sections(text, evolution.tooth), "author": _writer(evolution.author_name, evolution.created_by),
        "professional": evolution.professional.name if evolution.professional_id else "",
        "at": evolution.created_at, "finalized_at": evolution.finalized_at, "auto": evolution.finalized_automatically,
        "from_plan": bool(evolution.plan_item_id),
        "corrects": previous.clinical_date if previous else (timezone.localtime(note_link.note.effective_at).date() if note_link else None),
        "rectified": None, "can_edit": False, "can_rectify": False,
        "fill": _fill(evolution.tooth, text["procedure"], text["orthodontic"], text["notes"], evolution.clinical_date,
                      evolution.professional_id),
    }
    if evolution.status == DentalEvolution.Status.RECTIFIED:
        row["rectified"] = {"at": evolution.rectified_at, "by": _person(evolution.rectified_by),
                            "reason": decrypt_text(evolution.rectification_reason_encrypted)}
        row["voided"] = not evolution.corrections.exists()
        if row["voided"]:
            row["status_label"] = "Anulado"
    elif evolution.status == DentalEvolution.Status.FINALIZED:
        row["can_rectify"] = can_evolve and can_rectify(user, evolution.created_by_id)
    else:
        row["can_edit"] = can_evolve and evolution.created_by_id == user.pk
        row["expires_at"] = evolution.created_at + timedelta(hours=draft_hours())
    return row


def _evolutions(tenant, patient):
    return (DentalEvolution.objects.filter(tenant=tenant, customer=patient)
            .select_related("professional", "previous", "rectified_by", "created_by", "replaces_note__note"))


def hidden_rectified(tenant, patient):
    """How many rectified records the default view hides (shown with the audit toggle)."""
    return (_evolutions(tenant, patient).filter(status=DentalEvolution.Status.RECTIFIED).count()
            + PatientNoteRectification.objects.filter(note__tenant=tenant, note__customer=patient).count())


def current_drafts(tenant, patient, user, can_evolve=False):
    return [evolution_view(e, user, can_evolve) for e in
            _evolutions(tenant, patient).filter(status=DentalEvolution.Status.DRAFT).order_by("created_at", "pk")]


def build_timeline(*, tenant, patient, user, ip="", clinical=False, audit=False, can_evolve=False):
    days = defaultdict(lambda: {"records": [], "evolutions": [], "notes": [], "payments": [], "documents": []})
    assessments = DentalAssessment.objects.filter(tenant=tenant, customer=patient)
    entries = MedicalRecordEntry.objects.filter(tenant=tenant, customer=patient)
    if clinical:
        # A dentist sees only their own records (plus the existing scheduled cross-cover).
        from .dental_assessment_services import assessments_for
        from .services import clinical_records_for
        assessments = assessments.filter(pk__in=assessments_for(user).values("pk"))
        entries = entries.filter(pk__in=clinical_records_for(user=user, tenant=tenant).values("pk"))
    assessments = (assessments
                   .select_related("final_entry", "professional__clinical_registration", "professional__user")
                   .order_by("-updated_at", "-pk")[:100])
    for row in assessments:
        try:
            if row.status == DentalAssessment.Status.FINALIZED and row.final_entry_id:
                payload = json.loads(_read_entry(row.final_entry, user, ip))
                day = row.final_entry.effective_date
            else:
                payload = json.loads(decrypt_text(row.payload_encrypted))
                day = _local_day(row.updated_at)
        except (ValueError, TypeError):
            continue
        sections = _payload_sections(payload)
        days[day]["records"].append({
            "kind": "Atendimento" if row.status == DentalAssessment.Status.FINALIZED else "Atendimento em rascunho",
            "author": _author(row.professional, (payload or {}).get("professional")),
            "sections": sections, "draft": row.status != DentalAssessment.Status.FINALIZED,
            "url": reverse("dental-assessment-detail", args=[row.pk])
            if row.professional.user_id == user.pk and row.created_by_id == user.pk else "",
        })
    entries = (entries.filter(dental_assessment__isnull=True, clinicalissueddocument__isnull=True)
               .exclude(record_type__in=PHYSIO_TYPES)
               .select_related("professional__clinical_registration", "professional__user")
               .order_by("-created_at", "-pk")[:200])
    for entry in entries:
        days[entry.effective_date]["records"].append({
            "kind": entry.get_record_type_display(), "title": entry.title,
            "author": _author(entry.professional, entry.professional_snapshot),
            "sections": _entry_sections(_read_entry(entry, user, ip)), "draft": False, "url": "",
        })
    # Evolução clínica: rascunhos ficam no quadro do atendimento; retificados só no modo auditoria.
    evolutions = _evolutions(tenant, patient).exclude(status=DentalEvolution.Status.DRAFT)
    if not audit:
        evolutions = evolutions.exclude(status=DentalEvolution.Status.RECTIFIED)
    for evolution in evolutions[:500]:
        days[evolution.clinical_date]["evolutions"].append(evolution_view(evolution, user, can_evolve))
    rectified = {r.note_id: r for r in PatientNoteRectification.objects.filter(note__tenant=tenant, note__customer=patient)
                 .select_related("rectified_by")}
    for note in PatientNote.objects.filter(tenant=tenant, customer=patient).select_related("author").order_by("-occurred_at", "-created_at", "-pk")[:500]:
        raw = decrypt_text(note.text_encrypted)
        if _is_plan(raw):
            continue  # the treatment plan lives in its own card, not in the history
        link = rectified.get(note.pk)
        if link and not audit:
            continue
        fields = note_fields(raw)
        day = _local_day(note.effective_at)
        days[day]["notes"].append({
            "id": note.pk, "sections": note_sections(raw), "author": _writer(note.author_name, note.author),
            "at": note.effective_at, "imported": bool(note.import_key),
            "rectified": {"at": link.rectified_at, "by": _person(link.rectified_by),
                          "reason": decrypt_text(link.reason_encrypted)} if link else None,
            "can_rectify": bool(can_evolve and not link and can_rectify(user, note.author_id)),
            "voided": bool(link and link.replacement_id is None),
            "fill": _fill("", fields.get("procedure"), fields.get("orthodontic"), fields.get("text"), day, None),
        })
    documents = ClinicalIssuedDocument.objects.filter(tenant=tenant, customer=patient, status="finalized")
    if clinical:
        documents = documents.filter(professional__user=user)
    for doc in (documents
                .select_related("professional").order_by("-finalized_at")[:100]):
        days[_local_day(doc.finalized_at)]["documents"].append({
            "title": doc.title, "kind": doc.get_kind_display(), "author": doc.professional.name,
            "replaced": bool(doc.replaced_by) if doc.kind == "budget" else False,
            "url": reverse("clinical-document-detail", args=[doc.pk]) if doc.professional.user_id == user.pk else ""})
    if module_enabled(tenant, "finance"):
        from finance.clinic_models import ClinicCashEntry, ClinicCashEntryRemoval, ClinicReceipt
        pending_removal = set(ClinicCashEntryRemoval.objects.filter(entry__session__tenant=tenant, entry__customer=patient,
                                                                    status="requested").values_list("entry_id", flat=True))
        for row in (ClinicCashEntry.objects.filter(session__tenant=tenant, customer=patient)
                    .exclude(status="cancelled").select_related("session").order_by("-created_at")[:200]):
            days[_local_day(row.session.opened_at)]["payments"].append({
                "total": row.total, "method": row.method_name or "Em aberto", "open": row.status == "open",
                "professional": row.professional_name, "notes": row.notes, "source": "Folha do caixa",
                "entry": row.pk, "pending_removal": row.pk in pending_removal})
        for receipt in (ClinicReceipt.objects.filter(installment__charge__tenant=tenant, installment__charge__customer=patient)
                        .select_related("installment__charge").order_by("-created_at")[:200]):
            charge = receipt.installment.charge
            days[_local_day(receipt.created_at)]["payments"].append({
                "total": receipt.amount, "method": receipt.method_name, "open": False, "professional": "",
                "notes": f"{charge.description} · parcela {receipt.installment.number}", "source": "Conta a receber"})
    return [{"day": day, **items} for day, items in sorted(days.items(), key=lambda pair: pair[0], reverse=True)]


class ReceiveForm(forms.Form):
    request_id = forms.UUIDField(widget=forms.HiddenInput)
    professional = forms.ModelChoiceField(queryset=Professional.objects.none(), label="Dentista / profissional", required=False,
                                          empty_label="Não está na lista (digitar abaixo)")
    professional_name = forms.CharField(label="Profissional não cadastrado (nome)", max_length=120, required=False)
    dentist_amount = forms.DecimalField(label="Dentista (R$)", max_digits=12, decimal_places=2, min_value=0, initial=0, required=False)
    clinic_amount = forms.DecimalField(label="Consultório (R$)", max_digits=12, decimal_places=2, min_value=0, initial=0, required=False)
    other_amount = forms.DecimalField(label="Outros (R$)", max_digits=12, decimal_places=2, min_value=0, initial=0, required=False)
    method = forms.ModelChoiceField(queryset=Customer.objects.none(), label="Forma de pagamento")
    notes = forms.CharField(label="Observação (opcional)", max_length=300, required=False)
    paid_on = forms.DateField(label="Data do recebimento", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    def __init__(self, *args, tenant, **kwargs):
        from finance.clinic_models import ClinicPaymentMethod
        super().__init__(*args, **kwargs)
        self.fields["professional"].queryset = Professional.objects.filter(tenant=tenant, active=True).order_by("name")
        self.fields["method"].queryset = ClinicPaymentMethod.objects.filter(tenant=tenant, active=True).order_by("kind", "name")
        from finance.clinic_cash import split_fields
        split_fields(self, tenant=tenant)

    def clean(self):
        from finance.clinic_cash import clean_split
        data = super().clean()
        if not data.get("professional") and not (data.get("professional_name") or "").strip():
            self.add_error("professional_name", "Selecione o profissional ou digite o nome de quem atendeu.")
        _not_future(self, data, "paid_on")
        clean_split(self, data)
        return data


def _not_future(form, data, field):
    data[field] = data.get(field) or timezone.localdate()
    if data[field] > timezone.localdate():
        form.add_error(field, "A data não pode ser no futuro.")


EVOLUTION_LABELS = (("procedure", "Procedimento clínico"), ("orthodontic", "Tratamento ortodôntico"), ("notes", "Observação"))
# Legacy PatientNote keys (evolutions written before the draft/finalized lifecycle).
NOTE_FIELDS = (("procedure", "Procedimento clínico"), ("orthodontic", "Tratamento ortodôntico"), ("text", "Observação"),
               ("plan", "Plano de tratamento"))


def note_fields(raw):
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        data = None
    if not isinstance(data, dict):
        return {"text": raw or ""}
    return {key: str(data.get(key) or "").strip() for key, _ in NOTE_FIELDS}


def note_sections(raw):
    fields = note_fields(raw)
    return [(label, fields[key]) for key, label in NOTE_FIELDS if fields.get(key)]


class EvolutionForm(forms.Form):
    """Lançamento rápido da evolução clínica: nasce como rascunho."""
    professional = forms.ModelChoiceField(queryset=Professional.objects.none(), label="Dentista responsável", required=False,
                                          empty_label="Não informado")
    tooth = forms.CharField(label="Dente", required=False, max_length=20,
                            widget=forms.TextInput(attrs={"inputmode": "numeric", "placeholder": "Ex.: 46", "autocomplete": "off"}))
    procedure = forms.CharField(label="Procedimento clínico", required=False, max_length=4000,
                                widget=forms.Textarea(attrs={"rows": 2}))
    orthodontic = forms.CharField(label="Tratamento ortodôntico", required=False, max_length=4000,
                                  widget=forms.Textarea(attrs={"rows": 2}))
    notes = forms.CharField(label="Observação", required=False, max_length=4000, widget=forms.Textarea(attrs={"rows": 2}))
    clinical_date = forms.DateField(label="Data do atendimento", required=False,
                                    widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["professional"].queryset = Professional.objects.filter(tenant=tenant, active=True).order_by("name")

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        try:
            return clean_fields(data)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages)


PLAN_ROWS = 30


def _price(raw):
    raw = (raw or "").strip().replace("R$", "").replace(" ", "")
    price = Decimal((raw.replace(".", "").replace(",", ".") if "," in raw else raw) or "0").quantize(Decimal("0.01"))
    if not price.is_finite() or price < 0 or price > Decimal("999999.99"):
        raise InvalidOperation
    return price


def posted_plan_rows(post):
    """Rows of the plan table, in screen order. Raises ValidationError with the row number."""
    ids, teeth, procedures, prices, statuses = (post.getlist(name) for name in
                                                ("plan_id", "plan_tooth", "plan_procedure", "plan_price", "plan_status"))
    rows = []
    for index, procedure in enumerate(procedures[:PLAN_ROWS]):
        procedure = " ".join(procedure.split())[:200]
        tooth = " ".join((teeth[index] if index < len(teeth) else "").split())[:20]
        raw = prices[index] if index < len(prices) else ""
        pk = ids[index] if index < len(ids) else ""
        if not procedure and not raw.strip() and not tooth:
            continue
        if not procedure:
            raise ValidationError(f"Item {index + 1}: informe o procedimento.")
        try:
            price = _price(raw)
        except (InvalidOperation, ValueError):
            raise ValidationError(f"Item {index + 1}: valor inválido.")
        status = statuses[index] if index < len(statuses) else ""
        rows.append({"id": int(pk) if pk.isdigit() else None, "tooth": tooth, "procedure": procedure, "price": price,
                     "status": status if status in {"planned", "quoted"} else "planned"})
    return rows


def plan_view(tenant, patient):
    items = list(plan_items(tenant, patient).prefetch_related("evolutions"))
    open_items, done = [], []
    for item in items:
        row = {"id": item.pk, "tooth": item.tooth, "procedure": decrypt_text(item.procedure_encrypted), "price": item.price,
               "status": item.status, "status_label": item.get_status_display(), "executed_at": item.executed_at,
               "professional_id": item.professional_id}
        (open_items if item.status in DentalPlanItem.EDITABLE else done).append(row)
    professional = next((i["professional_id"] for i in open_items if i["professional_id"]), None)
    return {"open": open_items, "done": done, "professional": professional,
            "total": sum((i["price"] for i in open_items), Decimal("0"))}


def _is_plan(raw):
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return isinstance(data, dict) and bool(str(data.get("plan") or "").strip())


def plan_versions(tenant, patient, limit=20, user=None):
    """Versions of the plan saved before plan items existed, shown inside the plan card.
    A version removed by mistake-cleanup ("Apagar esta versão") is hidden; the original stays for audit."""
    out = []
    voided = set(PatientNoteRectification.objects.filter(note__tenant=tenant, note__customer=patient)
                 .values_list("note_id", flat=True))
    for note in PatientNote.objects.filter(tenant=tenant, customer=patient).select_related("author").order_by("-occurred_at", "-created_at", "-pk")[:300]:
        if note.pk in voided:
            continue
        raw = decrypt_text(note.text_encrypted)
        if _is_plan(raw):
            out.append({"id": note.pk, "at": note.effective_at, "author": _writer(note.author_name, note.author), "text": json.loads(raw)["plan"],
                        "can_delete": bool(user and can_rectify(user, note.author_id))})
            if len(out) >= limit:
                break
    return out


def _cash_access(user):
    from finance.clinic_services import access as finance_access
    try:
        return finance_access(user)
    except PermissionDenied:
        return None


def _open_session(request, tenant):
    from core.unit_scope import selected_unit
    from finance.models import CashSession
    return CashSession.objects.filter(tenant=tenant, unit=selected_unit(request, tenant), status="open").first()


def _default_professional(user, patient, clinical):
    if clinical:
        own = Professional.objects.filter(tenant_id=user.tenant_id, user=user, active=True).values_list("pk", flat=True).first()
        if own:
            return own
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return (Appointment.objects.filter(tenant_id=user.tenant_id, customer=patient, starts_at__gte=start,
                                       starts_at__lt=start + timedelta(days=1))
            .exclude(status__in=["cancelled", "canceled", "no_show"]).order_by("starts_at")
            .values_list("professional_id", flat=True).first())


def _plan_receivables(tenant, patient):
    """Pending amounts of this patient's approved treatment plans (paid from here into the dentist's day sheet)."""
    from finance.models import FinancialTransaction
    from .models import ClinicalTreatmentPlan
    plans = ClinicalTreatmentPlan.objects.filter(entry__tenant=tenant, entry__customer=patient).values("pk")
    return FinancialTransaction.objects.filter(tenant=tenant, source_type="clinical-plan", type="income", status="pending",
                                               source_id__in=plans).order_by("created_at")


def _payment_methods(tenant):
    from finance.clinic_models import ClinicPaymentMethod
    return list(ClinicPaymentMethod.objects.filter(tenant=tenant, active=True).order_by("kind", "name"))


def _can_documents(user):
    """Same rule as the documents page: the clinic team prepares, the professional reviews and emits."""
    try:
        from .document_views import staff
        staff(type("R", (), {"user": user})())
        return True
    except PermissionDenied:
        return False


EVOLUTION_ACTIONS = {"evolution", "evolution-edit", "evolution-delete", "finalize", "rectify", "rectify-note",
                     "void", "void-note"}


def _evolution_action(request, action, tenant, patient):
    """Rascunho, finalização e retificação da evolução. Returns the bound form when it must be shown again."""
    user, post = request.user, request.POST
    form = EvolutionForm(post, tenant=tenant)
    if action == "evolution":
        if not form.is_valid():
            # “Finalizar” with an empty form just closes the drafts already in the attendance.
            if post.get("finish") and not any((post.get(k) or "").strip() for k in ("tooth", "procedure", "orthodontic", "notes")):
                done = finalize_attendance(user=user, patient=patient, request=request)
                messages.success(request, f"Atendimento finalizado: {len(done)} lançamento(s) registrados no prontuário."
                                 if done else "Não há rascunhos seus para finalizar.")
                return None
            return form
        create_draft(user=user, patient=patient, data=form.cleaned_data, request=request)
        if post.get("finish"):
            done = finalize_attendance(user=user, patient=patient, request=request)
            messages.success(request, f"Atendimento finalizado: {len(done)} lançamento(s) registrados no prontuário.")
        else:
            messages.success(request, "Lançamento adicionado ao atendimento como rascunho.")
        return None
    if action == "finalize":
        done = finalize_attendance(user=user, patient=patient, request=request)
        messages.success(request, f"Atendimento finalizado: {len(done)} lançamento(s) registrados no prontuário."
                         if done else "Não há rascunhos seus para finalizar.")
        return None
    if action in {"void", "void-note"}:
        try:
            if action == "void":
                target = post.get("evolution") or ""
                evolution = get_object_or_404(DentalEvolution, pk=target if target.isdigit() else 0, tenant=tenant, customer=patient)
                void(user=user, evolution_id=evolution.pk, reason=post.get("reason"), request=request)
            else:
                note_id = post.get("note") or ""
                note = get_object_or_404(PatientNote, pk=note_id if note_id.isdigit() else 0, tenant=tenant, customer=patient)
                void_note(user=user, note=note, reason=post.get("reason"), request=request)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, "Lançamento anulado e retirado do histórico. O original fica guardado no modo auditoria.")
        return None
    target = post.get("evolution") or ""
    if not target.isdigit() and action != "rectify-note":
        raise PermissionDenied
    if action == "evolution-delete":
        evolution = get_object_or_404(DentalEvolution, pk=target, tenant=tenant, customer=patient)
        delete_draft(user=user, evolution_id=evolution.pk, request=request)
        messages.success(request, "Rascunho excluído.")
        return None
    if not form.is_valid():
        messages.error(request, " ".join(e for errors in form.errors.values() for e in errors))
        return None
    if action == "evolution-edit":
        evolution = get_object_or_404(DentalEvolution, pk=target, tenant=tenant, customer=patient)
        update_draft(user=user, evolution_id=evolution.pk, data=form.cleaned_data, request=request)
        messages.success(request, "Rascunho atualizado.")
    elif action == "rectify":
        evolution = get_object_or_404(DentalEvolution, pk=target, tenant=tenant, customer=patient)
        rectify(user=user, evolution_id=evolution.pk, reason=post.get("reason"), data=form.cleaned_data, request=request)
        messages.success(request, "Lançamento retificado. O registro original fica guardado para auditoria.")
    else:
        note_id = post.get("note") or ""
        note = get_object_or_404(PatientNote, pk=note_id if note_id.isdigit() else 0, tenant=tenant, customer=patient)
        rectify_note(user=user, note=note, reason=post.get("reason"), data=form.cleaned_data, request=request)
        messages.success(request, "Lançamento retificado. O registro original fica guardado para auditoria.")
    return None


def _plan_action(request, tenant, patient):
    post = request.POST
    try:
        rows = posted_plan_rows(post)
        professional = None
        if (post.get("plan_professional") or "").isdigit():
            professional = get_object_or_404(Professional, pk=post["plan_professional"], tenant=tenant, active=True)
        save_plan(user=request.user, patient=patient, rows=rows, professional=professional, request=request)
        execute = post.get("execute") or ""
        if execute.isdigit():
            item = get_object_or_404(DentalPlanItem, pk=execute, tenant=tenant, customer=patient)
            execute_plan_item(user=request.user, item_id=item.pk, request=request)
            messages.success(request, "Procedimento executado: lançado na evolução como rascunho. Revise e finalize o atendimento.")
        else:
            messages.success(request, "Plano de tratamento salvo.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))


@login_required
@never_cache
def patient_record(request, pk):
    tenant, clinical = access(request.user)
    from finance.reception_permissions import allowed, require
    require(request.user, "prontuarios")
    patient = get_object_or_404(shared_patients(request.user), pk=pk, tenant=tenant)
    self_url = reverse("dental-patient-record", args=[patient.pk])
    # Time-based finalization also runs here, so an open page never offers to edit an expired draft.
    finalize_expired(customer=patient)
    cash_tenant = _cash_access(request.user) if patient.active else None
    session = _open_session(request, tenant) if cash_tenant else None
    receive_form = ReceiveForm(request.POST if request.POST.get("action") == "receive" else None, tenant=tenant,
                               initial={"request_id": uuid.uuid4(), "paid_on": timezone.localdate(),
                                        "professional": _default_professional(request.user, patient, clinical)}) if cash_tenant else None
    evolution_form = EvolutionForm(tenant=tenant, initial={"clinical_date": timezone.localdate(),
                                                           "professional": _default_professional(request.user, patient, clinical)})
    if request.method == "POST":
        action = request.POST.get("action")
        if action in EVOLUTION_ACTIONS:
            require(request.user, "evolucao")
            try:
                bound = _evolution_action(request, action, tenant, patient)
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
                bound = None
            if bound is None:
                return redirect(self_url + "#evolucao")
            evolution_form = bound
        elif action == "plan":
            require(request.user, "plano")
            _plan_action(request, tenant, patient)
            return redirect(self_url + "#plano")
        elif action == "receive":
            if not cash_tenant:
                raise PermissionDenied("Seu perfil não registra recebimentos no caixa.")
            if receive_form.is_valid():
                from django.db import transaction
                from core.unit_scope import selected_unit
                from finance.clinic_cash import add_split_entry
                from finance.clinic_services import day_sheet
                data = receive_form.cleaned_data
                try:
                    # One clinic cash sheet per day, opened on the first receipt; the line keeps the professional.
                    # Sheet and line in one step: a refused line never leaves an empty extra sheet behind.
                    with transaction.atomic():
                        session = day_sheet(tenant, selected_unit(request, tenant), data["professional"], request.user,
                                            day=data["paid_on"])
                        rows = add_split_entry(user=request.user, session_id=session.pk, customer=patient, notes=data["notes"],
                                               professional=data["professional"], professional_name=data["professional_name"],
                                               dentist_amount=data["dentist_amount"], clinic_amount=data["clinic_amount"],
                                               other_amount=data["other_amount"], method=data["method"], request_id=data["request_id"],
                                               second_method=data.get("second_method"), second_amount=data.get("second_amount"))
                except ValidationError as exc:
                    receive_form.add_error(None, exc)
                else:
                    total = f"{sum(r.total for r in rows):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    how = " + ".join(r.method_name for r in rows)
                    messages.success(request, f"Pagamento de R$ {total} ({how}) recebido e lançado no caixa da clínica de {data['paid_on']:%d/%m/%Y}, para {rows[0].professional_name}.")
                    return redirect(self_url)
        elif action in {"deactivate", "reactivate"}:
            if not (request.user.role in {"owner", "tenant-admin", "manager"} or allowed(request.user, "cadastro")):
                raise PermissionDenied("Seu perfil não altera o cadastro de pacientes.")
            active = action == "reactivate"
            reason = " ".join((request.POST.get("reason") or "").split())[:300]
            if not active and len(reason) < 3:
                messages.error(request, "Informe o motivo para inativar o paciente.")
                return redirect(self_url)
            from django.db import transaction as db_tx
            with db_tx.atomic():
                locked = type(patient).objects.select_for_update().get(pk=patient.pk, tenant=tenant)
                if locked.active != active:
                    locked.active = active
                    locked.save(update_fields=["active"])
                    append_audit(tenant=tenant, user=request.user, request=request,
                                 action="clinical.patient.reactivated" if active else "clinical.patient.deactivated",
                                 entity_type="Customer", entity_id=patient.pk, before={"active": not active},
                                 after={"active": active, "reason": reason})
            messages.success(request, "Paciente reativado." if active else
                             "Paciente inativado. Ele sai da lista de pacientes; o prontuário continua guardado.")
            return redirect(self_url)
        elif action in {"payment-delete", "payment-ask"}:
            from finance.clinic_cash import cancel_entry, request_removal
            from finance.clinic_models import ClinicCashEntry
            entry_id = request.POST.get("entry") or ""
            row = get_object_or_404(ClinicCashEntry, pk=entry_id if entry_id.isdigit() else 0, session__tenant=tenant,
                                    customer=patient)
            reason = " ".join((request.POST.get("reason") or "").split())[:300]
            try:
                if action == "payment-delete":
                    from finance.clinic_cash import decide_removal
                    ask = row.removal_requests.filter(status="requested").first()
                    if ask and request.user.role in {"owner", "tenant-admin", "manager"}:
                        decide_removal(user=request.user, removal_id=ask.pk, approve=True, note=reason)
                    else:
                        cancel_entry(user=request.user, entry_id=row.pk, reason=reason)
                    messages.success(request, "Pagamento apagado. Ele saiu do histórico e da folha do caixa.")
                else:
                    request_removal(user=request.user, entry_id=row.pk, reason=reason)
                    messages.success(request, "Pedido enviado. O gestor aprova ou recusa na folha do caixa.")
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
            return redirect(self_url)
        elif action == "receive-plan":
            if not cash_tenant:
                raise PermissionDenied("Seu perfil não registra recebimentos no caixa.")
            from .finance_views import receive_plan
            pending = _plan_receivables(tenant, patient).filter(pk=request.POST.get("transaction") or 0).first()
            if pending is None:
                messages.error(request, "Este recebível não está mais pendente.")
                return redirect(self_url)
            try:
                entry = receive_plan(request, pending.pk, request.POST.get("method", ""), request.POST.get("paid_on", ""))
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
            else:
                messages.success(request, f"Recebimento lançado na folha do caixa da clínica, para {entry.professional_name}.")
            return redirect(self_url)
        else:
            raise PermissionDenied
    audit = request.GET.get("auditoria") == "1"
    append_audit(tenant=tenant, user=request.user, request=request,
                 action="clinical.dental.patient_record.audit_viewed" if audit else "clinical.dental.patient_record.viewed",
                 entity_type="Customer", entity_id=patient.pk)
    from .patient_registration import missing_registration
    birth = patient.birth_date
    today = timezone.localdate()
    can_evolve = allowed(request.user, "evolucao")
    plan = plan_view(tenant, patient)
    return render(request, "healthcare/dental_patient_record.html", {
        **shell_context(request.user, request),
        "patient": patient, "clinical": clinical,
        "initials": "".join(word[0] for word in patient.name.split()[:2]).upper(),
        "age": (today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))) if birth else None,
        "missing": missing_registration(patient),
        "timeline": build_timeline(tenant=tenant, patient=patient, user=request.user, ip=request.META.get("REMOTE_ADDR", ""),
                                   clinical=clinical, audit=audit, can_evolve=can_evolve),
        "audit": audit, "hidden_rectified": hidden_rectified(tenant, patient),
        "can_schedule": has_capability(request.user, "agenda.manage") and request.user.role not in {"professional", "healthcare"},
        "document_kinds": DOCUMENT_KINDS, "can_documents": patient.active and _can_documents(request.user),
        "receive_form": receive_form if allowed(request.user, "caixa") else None, "cash_session": session,
        "can_edit_patient": request.user.role in {"owner", "tenant-admin", "manager"} or allowed(request.user, "cadastro"),
        "can_delete_payment": request.user.role in {"owner", "tenant-admin", "manager"} or allowed(request.user, "apagar_lancamento"),
        "plan_receivables": list(_plan_receivables(tenant, patient)[:50]) if cash_tenant and allowed(request.user, "caixa") else [],
        "payment_methods": _payment_methods(tenant) if cash_tenant else [],
        "evolution_form": evolution_form, "can_evolve": can_evolve,
        "drafts": current_drafts(tenant, patient, request.user, can_evolve), "draft_hours": draft_hours(),
        "professionals": list(Professional.objects.filter(tenant=tenant, active=True).order_by("name").values("pk", "name")),
        "can_plan": allowed(request.user, "plano"), "plan": plan,
        "plan_professional": plan["professional"] or _default_professional(request.user, patient, clinical),
        "plan_versions": plan_versions(tenant, patient, user=request.user),
        "reasons": RECTIFY_REASONS,
    })


RECTIFY_REASONS = ("Erro de digitação", "Dente incorreto", "Procedimento incorreto", "Data incorreta")
