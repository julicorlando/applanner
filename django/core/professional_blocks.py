from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from zoneinfo import ZoneInfo
from scheduling.models import Appointment, Professional, ProfessionalTimeOff
from tenants.models import Unit
from .audit import append_audit


class BlockForm(forms.Form):
    starts_at = forms.DateTimeField(
        label="Início", widget=forms.DateTimeInput(attrs={"type": "datetime-local"})
    )
    ends_at = forms.DateTimeField(
        label="Fim", widget=forms.DateTimeInput(attrs={"type": "datetime-local"})
    )
    reason = forms.CharField(label="Motivo", max_length=255)

    def clean(self):
        data = super().clean()
        start, end = data.get("starts_at"), data.get("ends_at")
        if start and end and (end <= start or start < timezone.now()):
            raise ValidationError("Escolha um período futuro com fim após o início.")
        return data


def valid_block_form(form, tenant):
    with timezone.override(ZoneInfo(tenant.timezone or "America/Recife")):
        return form.is_valid()


@login_required
def blocks(request):
    if request.user.role != "professional" or not request.user.tenant_id:
        raise PermissionDenied
    professional = get_object_or_404(
        Professional, tenant_id=request.user.tenant_id, user=request.user, active=True
    )
    form = BlockForm(
        request.POST
        if request.method == "POST" and request.POST.get("action") != "cancel"
        else None
    )
    if request.method == "POST":
        try:
            with transaction.atomic():
                # Booking locks the unit before the professional; keep that order.
                if professional.unit_id:
                    Unit.objects.select_for_update().get(
                        pk=professional.unit_id, tenant=professional.tenant
                    )
                Professional.objects.select_for_update().get(
                    pk=professional.pk, tenant=professional.tenant
                )
                if request.POST.get("action") == "cancel":
                    row = get_object_or_404(
                        ProfessionalTimeOff.objects.select_for_update(),
                        pk=request.POST.get("block"),
                        tenant=professional.tenant,
                        professional=professional,
                    )
                    row.status = "cancelled"
                    row.save(update_fields=["status", "updated_at"])
                    append_audit(
                        tenant=professional.tenant,
                        user=request.user,
                        request=request,
                        action="PROFESSIONAL_BLOCK_CANCELLED",
                        entity_type="ProfessionalTimeOff",
                        entity_id=row.pk,
                    )
                elif valid_block_form(form, professional.tenant):
                    start, end = (
                        form.cleaned_data["starts_at"],
                        form.cleaned_data["ends_at"],
                    )
                    if Appointment.objects.filter(
                        tenant=professional.tenant,
                        professional=professional,
                        starts_at__lt=end,
                        ends_at__gt=start,
                        status__in=["pending", "confirmed", "waiting", "in_progress"],
                    ).exists():
                        raise ValidationError(
                            "Há um agendamento nesse período. Solicite o remanejamento à gestão antes de bloquear."
                        )
                    if ProfessionalTimeOff.objects.filter(
                        tenant=professional.tenant,
                        professional=professional,
                        status="active",
                        starts_at__lt=end,
                        ends_at__gt=start,
                    ).exists():
                        raise ValidationError("Esse período já está bloqueado.")
                    row = ProfessionalTimeOff.objects.create(
                        tenant=professional.tenant,
                        professional=professional,
                        type="personal",
                        created_by=request.user,
                        **form.cleaned_data,
                    )
                    append_audit(
                        tenant=professional.tenant,
                        user=request.user,
                        request=request,
                        action="PROFESSIONAL_BLOCK_CREATED",
                        entity_type="ProfessionalTimeOff",
                        entity_id=row.pk,
                        after={"starts_at": start, "ends_at": end},
                    )
                else:
                    return render(
                        request,
                        "portal/professional_blocks.html",
                        {
                            "professional": professional,
                            "form": form,
                            "blocks": ProfessionalTimeOff.objects.filter(
                                professional=professional,
                                tenant=professional.tenant,
                                status="active",
                            ),
                        },
                    )
            messages.success(request, "Sua disponibilidade foi atualizada.")
            return redirect("professional-blocks")
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(
        request,
        "portal/professional_blocks.html",
        {
            "professional": professional,
            "form": form,
            "blocks": ProfessionalTimeOff.objects.filter(
                professional=professional,
                tenant=professional.tenant,
                status="active",
                ends_at__gte=timezone.now(),
            ).order_by("starts_at"),
        },
    )
