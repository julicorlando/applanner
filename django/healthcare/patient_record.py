"""Prontuário do paciente (odontologia): uma página com o cadastro, as evoluções,
os registros da recepção, os documentos emitidos e os pagamentos, agrupados por dia.
Cada dentista vê os próprios pacientes e registros; a recepção e a gestão veem e editam todos. Receber um valor aqui lança a linha na folha do caixa como paga.

Every read of clinical content is logged (MedicalRecordAccessLog / audit trail).
Clinical records themselves stay immutable: new content comes as new evolutions
(dentists) or team observations (anyone with access, reception included)."""
import json
import uuid
from collections import defaultdict
from datetime import datetime, time, timedelta
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
from core.crypto import decrypt_text, encrypt_text
from scheduling.models import Appointment, Customer, Professional

from .dental_assessment_forms import TEXT_FIELDS
from .document_models import KINDS as DOCUMENT_KINDS, ClinicalIssuedDocument, PatientNote
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


def build_timeline(*, tenant, patient, user, ip="", clinical=False):
    days = defaultdict(lambda: {"records": [], "notes": [], "payments": [], "documents": []})
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
    for note in PatientNote.objects.filter(tenant=tenant, customer=patient).order_by("-occurred_at", "-created_at", "-pk")[:500]:
        days[_local_day(note.effective_at)]["notes"].append({
            "sections": note_sections(decrypt_text(note.text_encrypted)), "author": note.author_name,
            "at": note.effective_at, "imported": bool(note.import_key)})
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
        from finance.clinic_models import ClinicCashEntry, ClinicReceipt
        for row in (ClinicCashEntry.objects.filter(session__tenant=tenant, customer=patient)
                    .exclude(status="cancelled").select_related("session").order_by("-created_at")[:200]):
            days[_local_day(row.session.opened_at)]["payments"].append({
                "total": row.total, "method": row.method_name or "Em aberto", "open": row.status == "open",
                "professional": row.professional_name, "notes": row.notes, "source": "Folha do caixa"})
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

    def clean(self):
        data = super().clean()
        if not data.get("professional") and not (data.get("professional_name") or "").strip():
            self.add_error("professional_name", "Selecione o profissional ou digite o nome de quem atendeu.")
        _not_future(self, data, "paid_on")
        return data


def _not_future(form, data, field):
    data[field] = data.get(field) or timezone.localdate()
    if data[field] > timezone.localdate():
        form.add_error(field, "A data não pode ser no futuro.")


def _at_day(day):
    """Today keeps the real time; an earlier day is filed at noon of that day."""
    if not day or day == timezone.localdate():
        return None
    return timezone.make_aware(datetime.combine(day, time(12, 0)))


EVOLUTION_FIELDS = (("procedure", "Procedimento clínico"), ("orthodontic", "Tratamento ortodôntico"), ("text", "Observação"))
NOTE_FIELDS = EVOLUTION_FIELDS + (("plan", "Plano de tratamento"),)


def note_sections(raw):
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        data = None
    if not isinstance(data, dict):
        return [("Observação", raw)] if (raw or "").strip() else []
    return [(label, str(data[key]).strip()) for key, label in NOTE_FIELDS if str(data.get(key) or "").strip()]


class NoteForm(forms.Form):
    procedure = forms.CharField(label="Procedimento clínico", required=False, max_length=4000,
                                widget=forms.Textarea(attrs={"rows": 3}))
    orthodontic = forms.CharField(label="Tratamento ortodôntico", required=False, max_length=4000,
                                  widget=forms.Textarea(attrs={"rows": 3}))
    text = forms.CharField(label="Observação", required=False, max_length=4000, widget=forms.Textarea(attrs={"rows": 3}))
    occurred_on = forms.DateField(label="Data da evolução", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    def clean(self):
        data = super().clean()
        if not any(len((data.get(key) or "").strip()) >= 3 for key, _ in EVOLUTION_FIELDS):
            raise forms.ValidationError("Escreva o procedimento, o tratamento ortodôntico ou uma observação.")
        _not_future(self, data, "occurred_on")
        return data


PLAN_ROWS = 30


class PlanForm(forms.Form):
    occurred_on = forms.DateField(label="Data do plano", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    professional = forms.ModelChoiceField(queryset=Professional.objects.none(), label="Dentista responsável", required=False,
                                          empty_label="Não informado")
    notes = forms.CharField(label="Observação do plano (opcional)", required=False, max_length=2000,
                            widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["professional"].queryset = Professional.objects.filter(tenant=tenant, active=True).order_by("name")
        self.items = []

    def clean(self):
        data = super().clean()
        _not_future(self, data, "occurred_on")
        post, items = self.data, []
        teeth, procedures, prices = post.getlist("plan_tooth"), post.getlist("plan_procedure"), post.getlist("plan_price")
        for index, procedure in enumerate(procedures[:PLAN_ROWS]):
            procedure = " ".join(procedure.split())[:200]
            tooth = " ".join((teeth[index] if index < len(teeth) else "").split())[:20]
            raw = (prices[index] if index < len(prices) else "").strip().replace("R$", "").replace(" ", "")
            if not procedure and not raw and not tooth:
                continue
            if not procedure:
                raise forms.ValidationError(f"Item {index + 1}: informe o procedimento.")
            try:
                price = Decimal((raw.replace(".", "").replace(",", ".") if "," in raw else raw) or "0").quantize(Decimal("0.01"))
            except InvalidOperation:
                raise forms.ValidationError(f"Item {index + 1}: valor inválido.")
            if not price.is_finite() or price < 0 or price > Decimal("999999.99"):
                raise forms.ValidationError(f"Item {index + 1}: valor inválido.")
            items.append({"tooth": tooth, "procedure": procedure, "price": price})
        if not items:
            raise forms.ValidationError("Adicione pelo menos um procedimento ao plano de tratamento.")
        self.items = items
        return data

    def text(self):
        lines = []
        professional = self.cleaned_data.get("professional")
        if professional:
            lines.append(f"Dentista responsável: {professional.name}")
        for number, item in enumerate(self.items, start=1):
            tooth = f"Dente {item['tooth']} · " if item["tooth"] else ""
            lines.append(f"{number}. {tooth}{item['procedure']} · {_brl(item['price'])}")
        lines.append(f"Total do plano: {_brl(sum((i['price'] for i in self.items), Decimal('0')))}")
        if (self.cleaned_data.get("notes") or "").strip():
            lines.append(f"Observação: {self.cleaned_data['notes'].strip()}")
        return "\n".join(lines)


def _brl(value):
    return "R$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


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


@login_required
@never_cache
def patient_record(request, pk):
    tenant, clinical = access(request.user)
    from finance.reception_permissions import allowed, require
    require(request.user, "prontuarios")
    patient = get_object_or_404(shared_patients(request.user), pk=pk, tenant=tenant)
    self_url = reverse("dental-patient-record", args=[patient.pk])
    cash_tenant = _cash_access(request.user) if patient.active else None
    session = _open_session(request, tenant) if cash_tenant else None
    receive_form = ReceiveForm(request.POST if request.POST.get("action") == "receive" else None, tenant=tenant,
                               initial={"request_id": uuid.uuid4(), "paid_on": timezone.localdate(),
                                        "professional": _default_professional(request.user, patient, clinical)}) if cash_tenant else None
    note_form = NoteForm(request.POST if request.POST.get("action") == "note" else None, initial={"occurred_on": timezone.localdate()})
    plan_form = PlanForm(request.POST if request.POST.get("action") == "plan" else None, tenant=tenant,
                         initial={"occurred_on": timezone.localdate(), "professional": _default_professional(request.user, patient, clinical)})
    if request.method == "POST":
        action = request.POST.get("action")
        if action in {"note", "plan"}:
            require(request.user, "evolucao")
        if action == "note":
            if note_form.is_valid():
                content = {key: (note_form.cleaned_data.get(key) or "").strip() for key, _ in EVOLUTION_FIELDS}
                note = PatientNote.objects.create(
                    tenant=tenant, customer=patient, text_encrypted=encrypt_text(json.dumps(content, ensure_ascii=False)),
                    author=request.user, author_name=(request.user.get_full_name() or request.user.email)[:160],
                    occurred_at=_at_day(note_form.cleaned_data["occurred_on"]))
                append_audit(tenant=tenant, user=request.user, request=request, action="clinical.patient_note.created",
                             entity_type="PatientNote", entity_id=note.pk, after={"customer": patient.pk})
                messages.success(request, "Evolução salva no prontuário.")
                return redirect(self_url)
        elif action == "plan":
            if plan_form.is_valid():
                note = PatientNote.objects.create(
                    tenant=tenant, customer=patient,
                    text_encrypted=encrypt_text(json.dumps({"plan": plan_form.text()}, ensure_ascii=False)),
                    author=request.user, author_name=(request.user.get_full_name() or request.user.email)[:160],
                    occurred_at=_at_day(plan_form.cleaned_data["occurred_on"]))
                append_audit(tenant=tenant, user=request.user, request=request, action="clinical.patient_plan.created",
                             entity_type="PatientNote", entity_id=note.pk, after={"customer": patient.pk, "items": len(plan_form.items)})
                messages.success(request, "Plano de tratamento salvo no prontuário.")
                return redirect(self_url)
        elif action == "receive":
            if not cash_tenant:
                raise PermissionDenied("Seu perfil não registra recebimentos no caixa.")
            if receive_form.is_valid():
                from django.db import transaction
                from core.unit_scope import selected_unit
                from finance.clinic_cash import add_entry
                from finance.clinic_services import day_sheet
                data = receive_form.cleaned_data
                try:
                    # Each professional has their own cash sheet per day, opened on the first receipt.
                    with transaction.atomic():
                        session = day_sheet(tenant, selected_unit(request, tenant), data["professional"], request.user,
                                            day=data["paid_on"])
                    row = add_entry(user=request.user, session_id=session.pk, customer=patient, notes=data["notes"],
                                    professional=data["professional"], professional_name=data["professional_name"],
                                    dentist_amount=data["dentist_amount"], clinic_amount=data["clinic_amount"],
                                    other_amount=data["other_amount"], method=data["method"], request_id=data["request_id"])
                except ValidationError as exc:
                    receive_form.add_error(None, exc)
                else:
                    total = f"{row.total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    messages.success(request, f"Pagamento de R$ {total} ({row.method_name}) recebido e lançado no caixa de {data['paid_on']:%d/%m/%Y} de {session.label}.")
                    return redirect(self_url)
        else:
            raise PermissionDenied
    append_audit(tenant=tenant, user=request.user, request=request, action="clinical.dental.patient_record.viewed",
                 entity_type="Customer", entity_id=patient.pk)
    from .patient_registration import missing_registration
    birth = patient.birth_date
    today = timezone.localdate()
    return render(request, "healthcare/dental_patient_record.html", {
        **shell_context(request.user, request),
        "patient": patient, "clinical": clinical,
        "initials": "".join(word[0] for word in patient.name.split()[:2]).upper(),
        "age": (today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))) if birth else None,
        "missing": missing_registration(patient),
        "timeline": build_timeline(tenant=tenant, patient=patient, user=request.user, ip=request.META.get("REMOTE_ADDR", ""),
                                   clinical=clinical),
        "can_schedule": has_capability(request.user, "agenda.manage") and request.user.role not in {"professional", "healthcare"},
        "document_kinds": DOCUMENT_KINDS,
        "receive_form": receive_form if allowed(request.user, "caixa") else None, "cash_session": session,
        "note_form": note_form, "plan_form": plan_form, "can_evolve": allowed(request.user, "evolucao"),
        "plan_rows": range(8),
    })
