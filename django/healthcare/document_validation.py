"""Public authenticity check opened from the QR code printed on issued documents.

Shows only issuance metadata (type, clinic, professional, date, masked patient
name, PDF fingerprint); clinical content is never exposed. Anyone holding the
printed document can register that they validated it.
"""
import hashlib
import re
from django import forms
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from accounts.login_limits import attempt_budget, limited_response
from core.audit import append_audit
from core.crypto import decrypt_json
from .document_models import ClinicalIssuedDocument, ClinicalDocumentValidation

CODE = re.compile(r"[A-Za-z0-9_-]{20,40}")


def masked_name(name):
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return ""
    connectors = {"da", "de", "do", "das", "dos", "e"}
    tail = [p if p.lower() in connectors else p[0].upper() + "." for p in parts[1:]]
    return " ".join([parts[0]] + tail)


class ValidationForm(forms.Form):
    validator_name = forms.CharField(label="Seu nome completo", min_length=3, max_length=120)
    validator_role = forms.CharField(label="Empresa, farmácia ou função (opcional)", required=False, max_length=120)
    confirm = forms.BooleanField(label="Conferi que o documento impresso corresponde aos dados desta página")


@never_cache
@require_http_methods(["GET", "POST"])
def validate(request, code):
    if not CODE.fullmatch(code or ""):
        raise Http404
    row = get_object_or_404(
        ClinicalIssuedDocument.objects.select_related("tenant", "customer"),
        verification_code=code, status="finalized",
    )
    form = ValidationForm(request.POST or None)
    if request.method == "POST":
        _, wait = attempt_budget(request, "document-validation", code)
        if wait:
            return limited_response(wait)
        if form.is_valid():
            ip = request.META.get("REMOTE_ADDR", "")
            entry = ClinicalDocumentValidation.objects.create(
                document=row,
                validator_name=form.cleaned_data["validator_name"].strip(),
                validator_role=form.cleaned_data["validator_role"].strip(),
                ip_hash=hashlib.sha256(ip.encode()).hexdigest() if ip else "",
            )
            append_audit(tenant=row.tenant, user=None, request=request, action="clinical.document.validated",
                         entity_type="ClinicalIssuedDocument", entity_id=row.pk,
                         after={"validation_id": entry.pk})
            return redirect(request.path + "?registrado=1")
    try:
        signature = decrypt_json(row.signature_snapshot_encrypted) if row.signature_snapshot_encrypted else {}
    except Exception:  # noqa: BLE001 - a damaged snapshot must not break the public check
        signature = {}
    return render(request, "healthcare/document_validation.html", {
        "row": row,
        "clinic": row.tenant.name,
        "patient": masked_name(row.customer.name),
        "signature": signature,
        "validations": row.validations.all()[:20],
        "form": form,
        "registered": request.GET.get("registrado") == "1",
    }, status=200)
