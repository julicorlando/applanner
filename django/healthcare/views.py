from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from billing.entitlements import module_enabled
from scheduling.models import Customer
from .services import assert_clinical_access
from .dentistry import save_dental_encounter, dental_history, dental_professional_allowance, SURFACES
from .forms import DentalEncounterForm,DENTAL_DETAILS


def _clinic(request):
    tenant = getattr(request.user, "tenant", None)
    if tenant is None:
        raise PermissionDenied("Selecione uma clínica.")
    if not module_enabled(tenant, "dentistry"):
        raise PermissionDenied("Módulo Odontologia não habilitado.")
    return tenant


@login_required
@never_cache
def dental_home(request):
    tenant = _clinic(request)
    assert_clinical_access(request.user)
    return render(request, "healthcare/dental_home.html", {
        "patients": Customer.objects.filter(tenant=tenant).order_by("name")[:200],
        "professional_allowance": dental_professional_allowance(tenant),
    })


@login_required
@never_cache
def dental_encounter(request):
    tenant = _clinic(request)
    assert_clinical_access(request.user)
    if request.method == "GET":
        from django.urls import reverse
        from urllib.parse import urlencode
        params = {key: request.GET[key] for key in ("customer", "appointment") if request.GET.get(key)}
        return redirect(reverse("dental-assessment-create") + ("?" + urlencode(params) if params else ""))
    form = DentalEncounterForm(request.POST or None, tenant=tenant, user=request.user)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            registration=getattr(data["professional"],"clinical_registration",None)
            if not registration or registration.council!="CRO":
                raise ValidationError("Cadastre CRO/UF em Identificação profissional antes do atendimento.")
            entry = save_dental_encounter(
                tenant=tenant, customer=data["customer"], professional=data["professional"],
                appointment=data["appointment"], user=request.user,
                anamnesis=data["anamnesis"], findings=data["findings"],
                procedures=data["procedures"], plan=data["plan"],
                odontogram=data["odontogram_json"],
                ip=request.META.get("REMOTE_ADDR", ""),
                clinical_details={key:data.get(key,"") for key in DENTAL_DETAILS},
                treatment_plan_reference=data.get("plan_reference"),
            )
            return redirect("clinical-record",pk=entry.pk)
        except (ValidationError, PermissionDenied) as exc:
            form.add_error(None, str(exc))
    return render(request, "healthcare/dental_encounter.html", {"form": form, "surfaces": sorted(SURFACES)})


@login_required
@never_cache
def dental_patient(request, customer_id):
    tenant = _clinic(request)
    assert_clinical_access(request.user)
    patient = get_object_or_404(Customer, pk=customer_id, tenant=tenant)
    return render(request, "healthcare/dental_patient.html", {
        "patient": patient, "history": dental_history(
            tenant=tenant, customer=patient, user=request.user,
            ip=request.META.get("REMOTE_ADDR", ""),
        ),
    })


@login_required
@never_cache
def dental_chart(request,customer_id):
    tenant=_clinic(request)
    patient=get_object_or_404(Customer,pk=customer_id,tenant=tenant)
    history=dental_history(tenant=tenant,customer=patient,user=request.user)
    return JsonResponse({"odontogram":history[-1]["data"]["odontogram"] if history else {}})
