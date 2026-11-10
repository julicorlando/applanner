from decimal import Decimal
import hashlib
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from accounts.permissions import has_capability
from scheduling.models import Service
from tenants.models import Unit
from .portal import _tenant
from .models import BeautySettings, SalonResource, RecoveryOffer, BarberCommandPayment
from .stages import configure_stages


def manager(request):
    tenant = _tenant(request)
    from billing.segment_access import require_segment

    require_segment(tenant, "barbearia")
    if not has_capability(request.user, "barber.manage") or request.user.role in [
        "professional",
        "reception",
    ]:
        raise PermissionDenied
    return tenant


class SettingsForm(forms.ModelForm):
    class Meta:
        model = BeautySettings
        fields = ["booking_assistant", "recovery_enabled"]
        labels = {
            "booking_assistant": "Recepcionista com IA no WhatsApp da empresa",
            "recovery_enabled": "Oferecer vagas canceladas a clientes autorizados da lista de espera",
        }


class ResourceForm(forms.ModelForm):
    class Meta:
        model = SalonResource
        fields = ["unit", "name", "kind"]
        labels = {"unit": "Unidade", "name": "Nome do recurso", "kind": "Tipo"}

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unit"].queryset = Unit.objects.filter(tenant=tenant, active=True)


class StageForm(forms.Form):
    service = forms.ModelChoiceField(Service.objects.none(), label="Serviço")

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["service"].queryset = Service.objects.filter(
            tenant=tenant, active=True
        )


class StageRowForm(forms.Form):
    name = forms.CharField(max_length=120, label="Etapa")
    minutes = forms.IntegerField(min_value=1, max_value=600, label="Duração em minutos")
    professional_required = forms.BooleanField(
        required=False, initial=True, label="Ocupa o profissional"
    )
    resource = forms.ModelChoiceField(
        SalonResource.objects.none(),
        required=False,
        label="Cadeira ou lavatório",
        empty_label="Sem recurso",
    )

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["resource"].queryset = SalonResource.objects.filter(
            tenant=tenant, active=True
        ).select_related("unit")


StageRows = forms.formset_factory(StageRowForm, extra=5, max_num=12, validate_max=True)


@login_required
@never_cache
def dashboard(request):
    tenant = manager(request)
    config, _ = BeautySettings.objects.get_or_create(tenant=tenant)
    action = request.POST.get("action") if request.method == "POST" else ""
    settings_form = SettingsForm(
        request.POST if action == "settings" else None, instance=config
    )
    resource_form = ResourceForm(
        request.POST if action == "resource" else None, tenant=tenant
    )
    stage_form = StageForm(request.POST if action == "stages" else None, tenant=tenant)
    stage_rows = StageRows(
        request.POST if action == "stages" else None,
        prefix="steps",
        form_kwargs={"tenant": tenant},
    )
    if action == "settings" and settings_form.is_valid():
        from communications.models import ChatbotFlow

        config = settings_form.save()
        if config.booking_assistant:
            from communications.tenant_flow import company_graph

            ChatbotFlow.objects.get_or_create(
                tenant=tenant, defaults={"enabled": True, "graph": company_graph()}
            )
        messages.success(
            request,
            "Preferências salvas. A IA exige fluxo ativo, integração de IA e WhatsApp da empresa conectado.",
        )
        return redirect("beauty-intelligence")
    if action == "resource" and resource_form.is_valid():
        row = resource_form.save(commit=False)
        row.tenant = tenant
        row.save()
        messages.success(request, "Recurso cadastrado.")
        return redirect("beauty-intelligence")
    if action == "stages" and stage_form.is_valid() and stage_rows.is_valid():
        try:
            configure_stages(
                tenant,
                stage_form.cleaned_data["service"],
                [row for row in stage_rows.cleaned_data if row],
            )
            messages.success(
                request,
                "Etapas salvas. Uma pausa sem profissional libera a agenda dele, mantendo o recurso reservado.",
            )
            return redirect("beauty-intelligence")
        except ValidationError as exc:
            stage_form.add_error(None, exc)
    offers = (
        RecoveryOffer.objects.filter(tenant=tenant)
        .select_related("appointment__customer", "appointment__service")
        .order_by("-created_at")
    )
    accepted = offers.filter(status="accepted")
    # Money actually registered, excluding voided receipts; never use booking list prices as cash.
    received = BarberCommandPayment.objects.filter(
        tenant=tenant,
        voided_at__isnull=True,
        command__status="closed",
        command__appointment__in=accepted.values("appointment_id"),
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    return render(
        request,
        "barber/intelligence.html",
        {
            "tenant": tenant,
            "settings_form": settings_form,
            "resource_form": resource_form,
            "stage_form": stage_form,
            "stage_rows": stage_rows,
            "resources": SalonResource.objects.filter(tenant=tenant),
            "services": Service.objects.filter(tenant=tenant, stages__isnull=False)
            .distinct()
            .prefetch_related("stages"),
            "offers": offers[:100],
            "accepted_count": accepted.count(),
            "received": received,
            "returned_count": accepted.filter(appointment__status="completed")
            .values("appointment__customer_id")
            .distinct()
            .count(),
        },
    )


@never_cache
def recovery_accept(request, token):
    offer = get_object_or_404(
        RecoveryOffer.objects.select_related(
            "tenant", "appointment__service", "appointment__professional"
        ),
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
    )
    error = ""
    if request.method == "POST":
        from .recovery import accept_offer

        try:
            offer = accept_offer(token)
        except ValidationError as exc:
            error = " ".join(exc.messages)
    return render(
        request, "barber/recovery_accept.html", {"offer": offer, "error": error}
    )
