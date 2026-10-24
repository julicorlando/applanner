import json
import calendar as month_calendar
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_safe
from scheduling.models import (
    Appointment,
    AppointmentRescheduleHistory,
    Professional,
    ProfessionalTimeOff,
)
from scheduling.availability import AvailabilityService
from tenants.models import Unit
from .portal import _require_tenant, available_modules, _role_resource_write
from .unit_scope import selected_unit
from .audit import append_audit


def access(request):
    tenant = _require_tenant(request)
    if not tenant:
        raise PermissionDenied
    from billing.segment_access import segment_enabled

    arena = segment_enabled(tenant, "arena")
    if request.user.role == 'professional':
        if arena:
            raise PermissionDenied
        professional = get_object_or_404(Professional, tenant=tenant, user=request.user, active=True)
        return tenant, professional.unit, False
    routes = {
        (m["slug"], r["slug"])
        for m in available_modules(request.user, tenant)
        for r in m["resources"]
    }
    if (
        ("arena", "reservas") not in routes
        if arena
        else ("agenda", "agendamentos") not in routes
    ):
        raise PermissionDenied
    return tenant, selected_unit(request, tenant), arena


@login_required
@require_safe
def calendar(request):
    tenant, unit, arena = access(request)
    tz = ZoneInfo(tenant.timezone or "America/Recife")
    today = timezone.now().astimezone(tz).date()
    try:
        day = date.fromisoformat(request.GET.get("date") or today.isoformat())
        if not 1900 <= day.year <= 2100:
            raise ValueError
    except ValueError:
        day = today
    mode = request.GET.get('mode', 'week')
    if mode not in {'day', 'week', 'month'}:
        mode = 'week'
    if mode == 'month':
        days = [value for week in month_calendar.Calendar().monthdatescalendar(day.year, day.month) for value in week]
        first = days[0]
        month_start = day.replace(day=1)
        previous = (month_start - timedelta(days=1)).replace(day=1)
        following = (month_start + timedelta(days=32)).replace(day=1)
    else:
        first = day if mode == 'day' else day - timedelta(days=day.weekday())
        days = [first + timedelta(days=i) for i in range(1 if mode == 'day' else 7)]
        previous, following = first - timedelta(days=len(days)), first + timedelta(days=len(days))
    start = datetime.combine(first, time.min, tz)
    end = datetime.combine(days[-1] + timedelta(days=1), time.min, tz)
    if arena:
        from arena.models import Reservation, Court, CourtBlock

        resources = Court.objects.filter(tenant=tenant, unit=unit, active=True)
        rows = Reservation.objects.filter(
            tenant=tenant, court__unit=unit, ends_at__gt=start, starts_at__lt=end
        ).select_related("court", "customer")
        blocks = CourtBlock.objects.filter(tenant=tenant, court__unit=unit, status='active', starts_at__lt=end, ends_at__gt=start).select_related('court')
    else:
        resources = Professional.objects.filter(tenant=tenant, unit=unit, active=True)
        rows = Appointment.objects.filter(
            tenant=tenant, unit=unit, ends_at__gt=start, starts_at__lt=end
        ).select_related("professional", "service", "customer")
        blocks = ProfessionalTimeOff.objects.filter(
            tenant=tenant,
            professional__unit=unit,
            status="active",
            starts_at__lt=end,
            ends_at__gt=start,
        ).select_related("professional")
        if request.user.role == 'professional':
            resources = resources.filter(user=request.user)
            rows = rows.filter(professional__user=request.user)
            blocks = blocks.filter(professional__user=request.user)
    raw = request.GET.get("resource", "")
    all_resources = list(resources.order_by('name'))
    if raw.isdigit():
        resource = get_object_or_404(resources, pk=int(raw))
        resources = resources.filter(pk=resource.pk)
        rows = rows.filter(**{"court" if arena else "professional": resource})
        blocks = blocks.filter(**{'court' if arena else 'professional': resource})
    rows = list(rows.order_by("starts_at"))
    blocks = list(blocks)
    resources = list(resources.order_by('name'))
    from .calendar_windows import open_windows
    windows = open_windows(tenant, unit, resources, days, rows, blocks, tz, arena)
    columns = []
    for value in days:
        columns.append(
            {
                "day": value,
                "today": value == today,
                "outside": mode == 'month' and value.month != day.month,
                "windows": windows.get(value, []),
                "rows": [
                    row for row in rows if row.starts_at.astimezone(tz).date() == value
                ],
                "blocks": [
                    row
                    for row in blocks
                    if row.starts_at.astimezone(tz).date()
                    <= value
                    <= row.ends_at.astimezone(tz).date()
                ],
            }
        )
    return render(
        request,
        "portal/calendar.html",
        {
            "tenant": tenant,
            "unit": unit,
            "arena": arena,
            "professional_mode": request.user.role == 'professional',
            "columns": columns,
            "resources": all_resources,
            "resource": raw,
            "day": day,
            "mode": mode,
            "previous": previous,
            "next": following,
            "today": today,
            "appointment_count": len(rows),
            "window_count": sum(len(items) for items in windows.values()),
            "can_move": not arena and request.user.role != 'professional'
            and _role_resource_write(request.user, "agenda", "agendamentos"),
        },
    )


@login_required
@require_POST
def move(request, pk):
    tenant, unit, arena = access(request)
    if (
        unit is None
        or arena
        or request.user.role == 'professional'
        or not _role_resource_write(request.user, "agenda", "agendamentos")
    ):
        raise PermissionDenied
    try:
        data = (
            json.loads(request.body)
            if request.content_type == "application/json"
            else request.POST
        )
        if not hasattr(data, "get") or unit is None:
            raise ValueError
        start = datetime.fromisoformat(str(data.get("starts_at", "")))
        tz = ZoneInfo(tenant.timezone or "America/Recife")
        start = (
            start.replace(tzinfo=tz) if start.tzinfo is None else start.astimezone(tz)
        )
        if start <= timezone.now():
            raise ValidationError("Escolha um horário futuro.")
        with transaction.atomic():
            Unit.objects.select_for_update().get(pk=unit.pk, tenant=tenant, active=True)
            original = get_object_or_404(Appointment, pk=pk, tenant=tenant, unit=unit)
            professional = get_object_or_404(
                Professional.objects.select_for_update(),
                pk=original.professional_id,
                tenant=tenant,
                unit=unit,
                active=True,
            )
            row = get_object_or_404(
                Appointment.objects.select_for_update(), pk=pk, tenant=tenant, unit=unit
            )
            if row.professional_id != professional.pk:
                raise ValidationError("A agenda mudou. Atualize a tela antes de mover.")
            if row.status not in {"pending", "confirmed"}:
                raise ValidationError("Esse atendimento não pode ser movido.")
            end = start + timedelta(minutes=row.service.duration_minutes)
            if not AvailabilityService().is_available(
                tenant,
                professional,
                start,
                end,
                exclude_appointment_id=row.pk,
                public_rules=False,service=row.service,
            ):
                raise ValidationError(
                    "Horário indisponível: verifique agenda e bloqueios."
                )
            AppointmentRescheduleHistory.objects.create(
                tenant=tenant,
                appointment=row,
                old_professional=professional,
                new_professional=professional,
                old_starts_at=row.starts_at,
                old_ends_at=row.ends_at,
                new_starts_at=start,
                new_ends_at=end,
                actor_type="user",
                actor_user=request.user,
                reason="Calendário operacional",
            )
            before = {"starts_at": row.starts_at, "ends_at": row.ends_at}
            row.starts_at = start
            row.ends_at = end
            row.save(update_fields=["starts_at", "ends_at", "updated_at"])
            append_audit(
                tenant=tenant,
                user=request.user,
                request=request,
                action="CALENDAR_RESCHEDULE",
                entity_type="Appointment",
                entity_id=row.pk,
                before=before,
                after={"starts_at": start, "ends_at": end},
            )
        return JsonResponse({"detail": "Agendamento movido."})
    except (ValueError, TypeError, ValidationError) as exc:
        return JsonResponse(
            {
                "detail": " ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else "Data inválida."
            },
            status=409,
        )
