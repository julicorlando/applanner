"""Register or complete a patient's administrative data from inside the clinical record."""
import re
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from billing.entitlements import module_enabled, require_module
from core.audit import append_audit
from scheduling.models import Customer
from scheduling.patient_fields import cpf_fingerprint, normalize_cpf
from .navigation import dental_workspace, shell_context
from .patient_scope import patients_for
from .services import assert_clinical_access

REQUIRED = {
    "phone": "telefone",
    "cpf": "CPF",
    "street": "logradouro",
    "address_number": "número",
    "district": "bairro",
    "city": "cidade",
    "state": "UF",
}
FIELDS = ["name", "phone", "email", "cpf", "birth_date", "postal_code", "street", "address_number",
          "address_complement", "district", "city", "state"]


def missing_registration(customer):
    """Labels of required administrative fields still blank (name is always present)."""
    missing = [label for field, label in REQUIRED.items() if not str(getattr(customer, field, "") or "").strip()]
    if len((customer.name or "").split()) < 2:
        missing.insert(0, "nome completo")
    return missing


class PatientForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = FIELDS
        labels = {"name": "Nome completo", "phone": "Telefone / WhatsApp", "email": "E-mail (opcional)",
                  "birth_date": "Data de nascimento (opcional)", "postal_code": "CEP (opcional)",
                  "address_complement": "Complemento (opcional)"}
        widgets = {"birth_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "state": forms.TextInput(attrs={"maxlength": 2, "style": "text-transform:uppercase"})}

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.tenant = tenant
        for field in REQUIRED:
            self.fields[field].required = True
        self.fields["name"].required = True
        self.fields["email"].required = False
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "pa-input")

    def clean_name(self):
        name = re.sub(r"\s+", " ", self.cleaned_data.get("name") or "").strip()
        if len(name.split()) < 2:
            raise forms.ValidationError("Informe o nome completo (nome e sobrenome).")
        return name

    def clean_state(self):
        state = (self.cleaned_data.get("state") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", state):
            raise forms.ValidationError("Informe a UF com duas letras.")
        return state

    def clean_cpf(self):
        try:
            cpf = normalize_cpf(self.cleaned_data.get("cpf"))
        except forms.ValidationError:
            raise forms.ValidationError("Informe um CPF válido.") from None
        clash = Customer.objects.filter(tenant=self.instance.tenant, cpf_hash=cpf_fingerprint(cpf))
        if cpf and clash.exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Já existe um paciente com este CPF na clínica. Peça à recepção para localizar o cadastro existente.")
        return cpf


def _clinical_user(request):
    user = request.user
    assert_clinical_access(user)
    if user.is_superuser or not user.tenant_id or user.tenant.archived_at or user.tenant.deleted_at:
        raise PermissionDenied
    require_module(user.tenant, "medical_records")
    return user.tenant


def _return_url(request, patient):
    target = _safe_next(request)
    if target:
        create = reverse("dental-assessment-create")
        if target.split("?")[0] == create and "customer=" not in target:
            return f"{create}?customer={patient.pk}"
        return target
    tenant = patient.tenant
    if dental_workspace(tenant) and module_enabled(tenant, "dentistry"):
        return reverse("dental-assessment-create") + f"?customer={patient.pk}"
    return reverse("clinical-patient", args=[patient.pk])


@login_required
@never_cache
def patient_form(request, pk=None):
    tenant = _clinical_user(request)
    patient = get_object_or_404(patients_for(request.user).filter(active=True), pk=pk, tenant=tenant) if pk else None
    form = PatientForm(request.POST or None, instance=patient, tenant=tenant)
    if request.method == "POST" and form.is_valid():
        changed = [name for name in form.changed_data if name in FIELDS]
        row = form.save(commit=False)
        if not patient:
            row.registered_by = request.user
        row.save()
        append_audit(tenant=tenant, user=request.user, request=request,
                     action="clinical.patient.completed" if patient else "clinical.patient.registered",
                     entity_type="Customer", entity_id=row.pk, after={"fields": changed})
        messages.success(request, "Cadastro do paciente atualizado." if patient else "Paciente cadastrado.")
        return redirect(_return_url(request, row))
    return render(request, "healthcare/patient_registration.html", {
        **shell_context(request.user, request),
        "form": form, "patient": patient,
        "missing": missing_registration(patient) if patient else [],
        "next": _safe_next(request),
    })


def _safe_next(request):
    target = request.POST.get("next") or request.GET.get("next") or ""
    ok = target.startswith("/") and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure())
    return target if ok else ""
