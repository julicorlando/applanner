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
    definition = forms.CharField(
        required=False,
        label="Etapas: nome | minutos | profissional sim/não | ID do recurso (opcional)",
        widget=forms.Textarea(
            attrs={
                "rows": 6,
                "placeholder": "Aplicação | 20 | sim | 1\nPausa | 30 | não | 1\nFinalização | 20 | sim | 2",
            }
        ),
    )

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields["service"].queryset = Service.objects.filter(
            tenant=tenant, active=True
        )

    def clean_definition(self):
        rows = []
        for line in self.cleaned_data["definition"].splitlines():
            if not line.strip():
                continue
            parts = [v.strip() for v in line.split("|")]
            try:
                if (
                    len(parts) not in (3, 4)
                    or parts[2].lower() not in ["sim", "não", "nao"]
                    or not 1 <= len(parts[0]) <= 120
                ):
                    raise ValueError
                resource = (
                    SalonResource.objects.get(
                        pk=int(parts[3]), tenant=self.tenant, active=True
                    )
                    if len(parts) == 4 and parts[3]
                    else None
                )
                minutes = int(parts[1])
                if not 1 <= minutes <= 600:
                    raise ValueError
                rows.append(
                    {
                        "name": parts[0],
                        "minutes": minutes,
                        "professional_required": parts[2].lower() == "sim",
                        "resource": resource,
                    }
                )
            except (ValueError, SalonResource.DoesNotExist):
                raise forms.ValidationError(
                    "Confira as etapas e os IDs dos recursos da sua empresa."
                ) from None
        return rows


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
    if action == "stages" and stage_form.is_valid():
        try:
            configure_stages(
                tenant,
                stage_form.cleaned_data["service"],
                stage_form.cleaned_data["definition"],
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
