import secrets
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone
from billing.entitlements import module_enabled
from finance.advanced_services import consume_material
from finance.material_portal import ConsumptionForm
from scheduling.models import Appointment
from .work_notes import authorized_appointment


@login_required
def materials(request, pk):
    appointment = authorized_appointment(request, pk)
    if not (
        module_enabled(appointment.tenant, "stock")
        or module_enabled(appointment.tenant, "products")
    ):
        raise PermissionDenied
    form = ConsumptionForm(
        request.POST or None,
        tenant=appointment.tenant,
        initial={"key": secrets.token_urlsafe(24)},
    )
    form.fields["product"].queryset = form.fields["product"].queryset.filter(
        Q(unit=appointment.unit) | Q(unit__isnull=True)
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                locked = Appointment.objects.select_for_update().get(
                    pk=appointment.pk, tenant=appointment.tenant
                )
                if (
                    locked.status
                    not in {"pending", "confirmed", "waiting", "in_progress"}
                    or locked.starts_at > timezone.now()
                ):
                    raise ValidationError(
                        "Registre o uso durante um atendimento aberto, após o início previsto."
                    )
                data = form.cleaned_data
                consume_material(
                    tenant=locked.tenant,
                    product_id=data["product"].pk,
                    quantity=data["quantity"],
                    user=request.user,
                    key=data["key"],
                    appointment=locked,
                    note=data["note"],
                )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(
                request,
                "Uso interno registrado. O cliente não será cobrado por este insumo.",
            )
            return redirect("professional-materials", pk=appointment.pk)
    return render(
        request,
        "portal/professional_materials.html",
        {
            "appointment": appointment,
            "form": form,
            "rows": appointment.material_consumptions.select_related(
                "product"
            ).order_by("-created_at"),
        },
    )
