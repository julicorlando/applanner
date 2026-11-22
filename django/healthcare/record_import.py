"""Imports the clinic's old Word patient sheets into the shared dental record.

Step 1 (preview): the file is read on the server and every patient, visit, budget and
observation is shown; nothing is written. The parsed result travels back signed.
Step 2 (confirm): patients are matched by name (accents/case ignored) and created or
completed (never overwritten); each dated visit becomes one note on the original date,
with "Procedimento clínico" and "Tratamento ortodôntico" kept apart and the values and
professional written exactly as on the sheet. Re-running the same file adds nothing twice.
"""
import hashlib
import json
from datetime import date, datetime, time

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache

from core.audit import append_audit
from core.crypto import encrypt_text
from scheduling.models import Customer

from .document_models import PatientNote
from .navigation import shell_context
from .patient_record import access, is_clinical
from .record_import_parser import fold, read_upload, same_person

SALT = "healthcare.record-import.v1"
MAX_UPLOAD = 60 * 1024 * 1024
ADMIN_ROLES = {"owner", "tenant-admin", "manager"}
KIND_LABELS = {"visit": "Atendimento", "budget": "Orçamento", "observation": "Observações clínicas", "sheet": "Observações da ficha antiga"}


def can_import(user):
    tenant, clinical = access(user)
    if user.role in ADMIN_ROLES or clinical or is_clinical(user):
        return tenant
    raise PermissionDenied("A importação de fichas é feita pelo responsável da clínica ou pelo dentista.")


class UploadForm(forms.Form):
    file = forms.FileField(label="Fichas clínicas (.zip com os arquivos Word ou um .docx)")

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if upload.size > MAX_UPLOAD:
            raise forms.ValidationError("Arquivo acima de 60 MB. Envie em partes.")
        if not upload.name.lower().endswith((".zip", ".docx")):
            raise forms.ValidationError("Envie um .zip com as fichas em Word ou um arquivo .docx.")
        return upload


def _at(day):
    # Midday local time keeps the original calendar day in any timezone conversion.
    return timezone.make_aware(datetime.combine(date.fromisoformat(day), time(12, 0)))


def _key(tenant, patient_key, kind, day, text):
    digest = hashlib.sha256(f"{tenant.pk}|{patient_key}|{kind}|{day}|{text}".encode()).hexdigest()[:40]
    return f"ficha:{digest}"


def plan_notes(sheet, today):
    """Every dated item of a sheet as notes: (day, kind, content). Nothing on the sheet is left out."""
    notes = []
    for day, visit in sorted(sheet["visits"].items()):
        if day:
            notes.append((day, "visit", {"procedure": "\n".join(visit["procedure"]),
                                         "orthodontic": "\n".join(visit["orthodontic"]), "text": ""}))
    for day, text in sorted(sheet["budgets"].items()):
        if day:
            notes.append((day, "budget", {"procedure": "", "orthodontic": "", "text": f"Orçamento/procedimentos:\n{text}"}))
    clinical = sheet.get("clinical_notes") or {}
    for day, text in sorted(clinical.items()):
        if day:
            notes.append((day, "observation", {"procedure": "", "orthodontic": "", "text": f"Observações clínicas:\n{text}"}))
    summary = []
    if clinical.get(""):
        summary.append(f"Observações clínicas:\n{clinical['']}")
    if sheet["observations"]:
        summary.append(f"Observações da ficha:\n{sheet['observations']}")
    if sheet["budgets"].get(""):
        summary.append(f"Orçamento/procedimentos (sem data legível na ficha):\n{sheet['budgets']['']}")
    undated = sheet["visits"].get("")
    if undated:
        summary.append("Procedimentos sem data na ficha:\n" + "\n".join(undated["procedure"] + undated["orthodontic"]))
    if sheet["remarks"]:
        summary.append("Anotação no nome da ficha: " + "; ".join(sheet["remarks"]))
    summary.extend(sheet["sheet_details"])
    if summary:
        dated = [n[0] for n in notes]
        notes.append((max(dated) if dated else today.isoformat(), "sheet",
                      {"procedure": "", "orthodontic": "", "text": "\n\n".join(summary)}))
    return notes


def _existing(queryset):
    found = {}
    for customer in queryset:
        found.setdefault(fold(customer.name), []).append(customer)
    return found


def find_patient(existing, sheet):
    """Existing patient with the same name (accents/case ignored) and a compatible birth date."""
    for customer in existing.get(sheet["key"].split("#")[0], []):
        if same_person(customer.birth_date and customer.birth_date.isoformat(), sheet["birth_date"]):
            return customer
    return None


def preview_rows(sheets, tenant):
    existing = _existing(Customer.objects.filter(tenant=tenant).only("pk", "name", "birth_date"))
    today = timezone.localdate()
    rows = []
    for sheet in sheets:
        if sheet.get("skip"):
            rows.append({"sheet": sheet, "notes": [], "match": None})
            continue
        notes = plan_notes(sheet, today)
        rows.append({"sheet": sheet, "match": find_patient(existing, sheet), "notes": notes,
                     "birth": date.fromisoformat(sheet["birth_date"]) if sheet["birth_date"] else None,
                     "display": [{"day": date.fromisoformat(day), "kind": KIND_LABELS[kind], **content} for day, kind, content in notes],
                     "procedures": sum(len(v["procedure"]) + len(v["orthodontic"]) for v in sheet["visits"].values())})
    return rows


@transaction.atomic
def apply(tenant, user, sheets, request=None, owner=None):
    today = timezone.localdate()
    report = {"created": 0, "completed": 0, "matched": 0, "notes": 0, "already": 0, "skipped": 0}
    existing = _existing(Customer.objects.select_for_update().filter(tenant=tenant))
    created_here = {}
    author = f"Ficha antiga importada por {(user.get_full_name() or user.email)}"[:160]
    owner = owner or user
    for sheet in sheets:
        if sheet.get("skip"):
            report["skipped"] += 1
            continue
        patient = created_here.get(sheet["key"]) or find_patient(existing, sheet)
        birth = date.fromisoformat(sheet["birth_date"]) if sheet["birth_date"] else None
        if patient is None:
            patient = Customer(tenant=tenant, name=sheet["name"][:150], phone=sheet["phone"], birth_date=birth,
                               city=sheet["city"][:100], state=sheet["state"])
            patient.registered_by = owner
            patient.save()
            created_here[sheet["key"]] = patient
            report["created"] += 1
        else:
            # Already registered: the registration stays as the clinic typed it; only the sheet goes in.
            report["matched"] += 1
        for day, kind, content in plan_notes(sheet, today):
            raw = json.dumps(content, ensure_ascii=False, sort_keys=True)
            key = _key(tenant, sheet["key"], kind, day, raw)
            if PatientNote.objects.filter(tenant=tenant, import_key=key).exists():
                report["already"] += 1
                continue
            try:
                with transaction.atomic():
                    PatientNote.objects.create(tenant=tenant, customer=patient, author=user, author_name=author,
                                               text_encrypted=encrypt_text(raw), occurred_at=_at(day), import_key=key)
            except IntegrityError:
                report["already"] += 1
                continue
            report["notes"] += 1
    append_audit(tenant=tenant, user=user, request=request, action="clinical.patient_sheets.imported",
                 entity_type="Tenant", entity_id=tenant.pk, after=report)
    return report


def handle(request, tenant, *, context, done_url, owner=None, again_url):
    if request.method == "POST" and request.POST.get("action") == "confirm":
        try:
            payload = signing.loads(request.POST.get("payload", ""), salt=SALT, max_age=6 * 3600)
        except signing.BadSignature:
            messages.error(request, "A prévia expirou ou foi alterada. Envie o arquivo novamente.")
            return redirect(again_url)
        if payload.get("tenant") != tenant.pk or payload.get("user") != request.user.pk:
            raise PermissionDenied
        report = apply(tenant, request.user, payload["sheets"], request, owner=owner)
        messages.success(request, (f"Importação concluída: {report['created']} paciente(s) novo(s), {report['matched']} já "
                                   f"cadastrado(s) (cadastro mantido), {report['notes']} registro(s) no prontuário"
                                   + (f", {report['already']} já importado(s) antes" if report["already"] else "") + "."))
        return redirect(done_url)
    context.setdefault("form", UploadForm())
    context["again_url"] = again_url
    if request.method == "POST":
        form = UploadForm(request.POST, request.FILES)
        context["form"] = form
        if form.is_valid():
            upload = form.cleaned_data["file"]
            try:
                sheets, problems = read_upload(upload.name, upload.read())
            except Exception:  # noqa: BLE001 - any unreadable archive is reported to the user
                form.add_error("file", "Não foi possível abrir o arquivo. Confira se é um .zip ou .docx válido.")
            else:
                rows = preview_rows(sheets, tenant)
                context.update({
                    "rows": rows, "problems": problems,
                    "payload": signing.dumps({"tenant": tenant.pk, "user": request.user.pk, "sheets": sheets}, salt=SALT, compress=True),
                    "totals": {"sheets": len(rows), "new": sum(1 for r in rows if not r["match"] and r["notes"]),
                               "matched": sum(1 for r in rows if r["match"]),
                               "notes": sum(len(r["notes"]) for r in rows),
                               "procedures": sum(r.get("procedures", 0) for r in rows),
                               "issues": sum(len(r["sheet"]["issues"]) for r in rows) + len(problems)},
                })
    return render(request, "healthcare/record_import.html", context)


@login_required
@never_cache
def import_sheets(request):
    tenant = can_import(request.user)
    return handle(request, tenant, context={**shell_context(request.user, request), "base_template": "healthcare/physio_shell.html"},
                  done_url="dental-assessments", again_url=reverse("dental-record-import"))
