from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect,render
from django.urls import reverse
from accounts.permissions import has_capability
from scheduling.models import TenantScheduleSettings
from scheduling.availability import AvailabilityService
from .unit_scope import selected_unit

AGENDA_FIELDS=["minimum_notice_minutes","maximum_days_ahead","slot_interval_minutes","buffer_minutes",
               "customer_can_cancel","customer_can_reschedule","cancel_notice_minutes",
               "reminder_24h_enabled","reminder_2h_enabled"]

class UnitScheduleForm(forms.ModelForm):
    class Meta:
        model=TenantScheduleSettings
        fields=AGENDA_FIELDS
        labels={"minimum_notice_minutes":"Antecedência mínima (minutos)","maximum_days_ahead":"Dias disponíveis para agendar",
                "slot_interval_minutes":"Intervalo entre horários (minutos)","buffer_minutes":"Pausa entre atendimentos (minutos)",
                "customer_can_cancel":"Cliente pode cancelar","customer_can_reschedule":"Cliente pode reagendar",
                "cancel_notice_minutes":"Antecedência para cancelar (minutos)","reminder_24h_enabled":"Lembrete de 24 horas",
                "reminder_2h_enabled":"Lembrete de 2 horas"}
    def clean_slot_interval_minutes(self):
        value=self.cleaned_data["slot_interval_minutes"]
        if value<5:
            raise forms.ValidationError("Informe pelo menos 5 minutos.")
        return value

@login_required
def unit_schedule_settings(request):
    tenant=request.user.tenant
    if not tenant or not has_capability(request.user,"agenda.manage"):
        raise PermissionDenied
    unit=selected_unit(request,tenant)
    if not unit:
        raise PermissionDenied("Cadastre uma unidade antes de configurar a agenda.")
    settings=AvailabilityService().settings(tenant,unit=unit)
    form=UnitScheduleForm(request.POST or None,instance=settings)
    if request.method=="POST" and form.is_valid():
        unit.schedule_overrides={key:form.cleaned_data[key] for key in AGENDA_FIELDS}
        unit.save(update_fields=["schedule_overrides","updated_at"])
        messages.success(request,f"Configurações da agenda de {unit.name} salvas.")
        return redirect(reverse("unit-schedule-settings")+f"?unit={unit.pk}")
    return render(request,"portal/unit_settings.html",{"tenant":tenant,"selected_unit":unit,"form":form})
