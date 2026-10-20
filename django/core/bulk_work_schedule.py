"""Add recurring workdays in one transaction without replacing existing records."""
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from scheduling.models import Professional, ProfessionalAvailability, ProfessionalBreak

from .portal import PORTAL_MODULES, _require_module_access, _require_tenant, _role_resource_write
from .unit_scope import selected_unit

WEEKDAYS = [(1, "Segunda-feira"), (2, "Terça-feira"), (3, "Quarta-feira"),
            (4, "Quinta-feira"), (5, "Sexta-feira"), (6, "Sábado"), (7, "Domingo")]


class BulkWorkScheduleForm(forms.Form):
    professionals = forms.ModelMultipleChoiceField(
        label="Profissionais", queryset=Professional.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        help_text="Selecione até 50 profissionais da unidade atual.")
    weekdays = forms.TypedMultipleChoiceField(
        label="Dias da semana", choices=WEEKDAYS, coerce=int,
        widget=forms.CheckboxSelectMultiple, initial=[1, 2, 3, 4, 5])
    start_time = forms.TimeField(label="Entrada", widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    end_time = forms.TimeField(label="Saída", widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    break_start = forms.TimeField(
        label="Início do intervalo (opcional)", required=False,
        widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    break_end = forms.TimeField(
        label="Fim do intervalo (opcional)", required=False,
        widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))

    def __init__(self, *args, tenant, unit, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["professionals"].queryset = Professional.objects.filter(
            tenant=tenant, unit=unit, active=True).order_by("name", "pk")

    def clean_professionals(self):
        value = self.cleaned_data["professionals"]
        if len(value) > 50:
            raise forms.ValidationError("Selecione até 50 profissionais por vez.")
        return value

    def clean(self):
        data = super().clean()
        start, end = data.get("start_time"), data.get("end_time")
        pause_start, pause_end = data.get("break_start"), data.get("break_end")
        if start and end and end <= start:
            self.add_error("end_time", "A saída deve ser depois da entrada, no mesmo dia.")
        if bool(pause_start) != bool(pause_end):
            self.add_error("break_end", "Preencha o início e o fim do intervalo, ou deixe ambos vazios.")
        elif pause_start and pause_end:
            if pause_end <= pause_start:
                self.add_error("break_end", "O fim do intervalo deve ser depois do início.")
            elif start and end and not (start < pause_start < pause_end < end):
                self.add_error("break_start", "O intervalo deve ficar dentro do expediente, com atendimento antes e depois.")
        return data


def create_work_schedules(*, tenant, unit, data):
    """Identical submissions are harmless; any conflict rolls back the whole batch."""
    ids = sorted(professional.pk for professional in data["professionals"])
    days = sorted(set(data["weekdays"]))
    start, end = data["start_time"], data["end_time"]
    pause_start, pause_end = data.get("break_start"), data.get("break_end")
    with transaction.atomic():
        professionals = list(Professional.objects.select_for_update().filter(
            tenant=tenant, unit=unit, active=True, pk__in=ids).order_by("pk"))
        if len(professionals) != len(ids) or not ids:
            raise ValidationError("A equipe mudou. Atualize a página e selecione os profissionais novamente.")
        schedules = {(row.professional_id, row.weekday): row for row in
                     ProfessionalAvailability.objects.select_for_update().filter(
                         professional_id__in=ids, weekday__in=days)}
        breaks = {}
        for row in ProfessionalBreak.objects.select_for_update().filter(
                professional_id__in=ids, weekday__in=days, active=True):
            breaks.setdefault((row.professional_id, row.weekday), []).append(row)
        new_schedules, new_breaks = [], []
        for professional in professionals:
            for day in days:
                key = (professional.pk, day)
                existing = schedules.get(key)
                label = f"{professional.name} · {dict(WEEKDAYS)[day]}"
                if existing and (existing.tenant_id != tenant.pk or not existing.active or
                                 existing.start_time != start or existing.end_time != end):
                    raise ValidationError(
                        f"{label}: já existe outro expediente. Edite esse cadastro individualmente; nenhum horário foi substituído.")
                day_breaks = breaks.get(key, [])
                for pause in day_breaks:
                    if pause.tenant_id != tenant.pk or pause.start_time < start or pause.end_time > end:
                        raise ValidationError(f"{label}: há um intervalo incompatível com o expediente informado.")
                    if pause_start and pause.start_time < pause_end and pause.end_time > pause_start:
                        if pause.start_time != pause_start or pause.end_time != pause_end:
                            raise ValidationError(f"{label}: o intervalo informado sobrepõe outro intervalo existente.")
                if not existing:
                    new_schedules.append(ProfessionalAvailability(
                        tenant=tenant, professional=professional, weekday=day,
                        start_time=start, end_time=end, active=True))
                if pause_start and not any(
                        pause.start_time == pause_start and pause.end_time == pause_end for pause in day_breaks):
                    new_breaks.append(ProfessionalBreak(
                        tenant=tenant, professional=professional, weekday=day,
                        start_time=pause_start, end_time=pause_end, label="Intervalo", active=True))
        for row in new_schedules + new_breaks:
            row.full_clean()
            row.save()
    return len(new_schedules), len(new_breaks)


@login_required
@require_http_methods(["GET", "POST"])
def bulk_work_schedule(request):
    if request.user.role == "professional":
        raise PermissionDenied
    tenant = _require_tenant(request)
    if tenant is None:
        return redirect("portal-home")
    _require_module_access(request.user, PORTAL_MODULES["agenda"], tenant, "agenda", "expedientes")
    if not _role_resource_write(request.user, "agenda", "expedientes"):
        raise PermissionDenied
    unit = selected_unit(request, tenant)
    if unit is None:
        messages.info(request, "Cadastre uma unidade antes de definir os expedientes.")
        return redirect("portal-setup")
    form = BulkWorkScheduleForm(
        request.POST if request.method == "POST" else None, tenant=tenant, unit=unit)
    if request.method == "POST" and form.is_valid():
        try:
            schedules, breaks = create_work_schedules(tenant=tenant, unit=unit, data=form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        except IntegrityError:
            form.add_error(None, "Os horários foram alterados por outra pessoa. Atualize a página e tente novamente.")
        else:
            messages.success(request,
                f"{schedules} expediente(s) e {breaks} intervalo(s) cadastrados. Horários já existentes foram preservados.")
            return redirect(reverse("portal-resource-list", args=["agenda", "expedientes"]) +
                            "?" + urlencode({"unit": unit.pk}))
    return render(request, "portal/bulk_work_schedule.html",
                  {"tenant": tenant, "selected_unit": unit, "form": form,
                   "units": tenant.units.filter(active=True).order_by("-is_primary", "name")})
