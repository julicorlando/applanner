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
    if request.user.role in {'professional','healthcare'}:
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


def _safe_reverse(name, args):
    from django.urls import NoReverseMatch, reverse
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return ""


def _whatsapp(phone):
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) < 10:
        return ""
    return "https://wa.me/" + (digits if digits.startswith("55") and len(digits) >= 12 else "55" + digits)


def _reception_reminders(request, tenant, unit, tz, today, raw):
    """What the reception must not forget: who arrives in the next hour and who still has to confirm tomorrow."""
    if request.user.role in {"professional", "healthcare"}:
        return {}
    now = timezone.now()
    base = Appointment.objects.filter(tenant=tenant, unit=unit).select_related("customer", "professional", "service")
    if raw.isdigit():
        base = base.filter(professional_id=int(raw))
    day_end = datetime.combine(today + timedelta(days=1), time.min, tz)
    coming = list(base.filter(status__in=["pending", "confirmed"], starts_at__gte=now - timedelta(minutes=10),
                              starts_at__lt=day_end).order_by("starts_at")[:60])
    tomorrow = datetime.combine(today + timedelta(days=1), time.min, tz)
    to_confirm = list(base.filter(status="pending", starts_at__gte=tomorrow, starts_at__lt=tomorrow + timedelta(days=1))
                      .order_by("starts_at")[:40])

    def item(row):
        start = row.starts_at.astimezone(tz)
        return {"id": row.pk, "start": start, "minutes": int((row.starts_at - now).total_seconds() // 60),
                "patient": row.customer_display_name, "professional": row.professional.name if row.professional_id else "",
                "service": row.service.name, "status": row.status, "status_label": row.get_status_display(),
                "whatsapp": _whatsapp(getattr(row.customer, "phone", "")),
                "url": _safe_reverse("portal-resource-edit", ["agenda", "agendamentos", row.pk])}

    soon = [item(row) for row in coming if row.starts_at <= now + timedelta(minutes=60)]
    alarms = [{"id": row.pk, "at": row.starts_at.isoformat(), "patient": row.customer_display_name,
               "professional": row.professional.name if row.professional_id else "", "service": row.service.name,
               "time": row.starts_at.astimezone(tz).strftime("%H:%M"), "status": row.get_status_display()} for row in coming]
    return {"soon": soon, "confirm": [item(row) for row in to_confirm], "alarms": alarms}


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
        if request.user.role in {'professional','healthcare'}:
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
    grid = None
    if mode != 'month':
        from . import calendar_grid
        if mode == 'week':
            # Saturday and Sunday only appear when something happens or can be booked on them.
            columns = [c for c in columns if c["day"].weekday() < 5 or c["rows"] or c["blocks"] or c["windows"] or c["today"]]
        first_hour, last_hour = calendar_grid.hour_range(columns, tz)
        grid = {"labels": calendar_grid.build(columns, tz, first_hour, last_hour), "first_hour": first_hour,
                "slots": (last_hour - first_hour) * 4, "now": calendar_grid.now_line(tz, first_hour, last_hour)}
        # A day with appointments side by side gets a wider column, so each one stays readable.
        widths = []
        for column in columns:
            lanes = min(max([ev["lanes"] for ev in column.get("events", [])] or [1]), 4)
            widths.append(f"minmax({130 * lanes}px,{lanes}fr)")
        grid["template"] = "58px " + " ".join(widths)
    services = {}
    for row in rows:
        if not arena and row.service_id and row.service_id not in services:
            from .calendar_grid import colour
            services[row.service_id] = {"name": row.service.name, "colour": colour(row.service_id)}
    focus = [row for row in rows if row.starts_at.astimezone(tz).date() == day]
    stats = {
        "scheduled": sum(1 for row in focus if row.status not in {"cancelled", "no_show"}),
        "done": sum(1 for row in focus if row.status == "completed"),
        "cancelled": sum(1 for row in focus if row.status == "cancelled"),
        "missed": sum(1 for row in focus if row.status == "no_show"),
    }
    waiting = []
    if not arena:
        now_start = datetime.combine(today, time.min, tz)
        waiting_rows = Appointment.objects.filter(
            tenant=tenant, unit=unit, starts_at__gte=now_start, starts_at__lt=now_start + timedelta(days=1),
            status__in=["waiting", "in_progress"],
        ).select_related("customer", "professional", "service").order_by("starts_at")
        if request.user.role in {'professional', 'healthcare'}:
            waiting_rows = waiting_rows.filter(professional__user=request.user)
        elif raw.isdigit():
            waiting_rows = waiting_rows.filter(professional_id=int(raw))
        waiting = list(waiting_rows[:20])
    reminders = _reception_reminders(request, tenant, unit, tz, today, raw) if not arena else {}
    selected = next((r for r in all_resources if str(r.pk) == raw), None)
    return render(
        request,
        "portal/calendar.html",
        {
            "grid": grid,
            "reminders": reminders,
            "modes": [("day", "Dia"), ("week", "Semana"), ("month", "Mês")],
            "weekday_names": ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"],
            "services": list(services.values()),
            "stats": stats,
            "waiting": waiting,
            "selected_resource": selected,
            "day_windows": windows.get(day, []),
            "waitlist_url": _safe_reverse("portal-resource-list", ["relacionamento", "espera"])
            if not arena and request.user.role not in {'professional', 'healthcare'} and ("relacionamento", "espera") in {
                (m["slug"], r["slug"]) for m in available_modules(request.user, tenant) for r in m["resources"]} else "",
            "report_url": _safe_reverse("operation-performance", [])
            if request.user.role in {"owner", "tenant-admin", "manager"} else "",
            "tenant": tenant,
            "unit": unit,
            "arena": arena,
            "professional_mode": request.user.role in {'professional','healthcare'},
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
            "can_create_appointment": not arena and request.user.role not in {'professional','healthcare'}
            and _role_resource_write(request.user, "agenda", "agendamentos"),
            "can_move": not arena and request.user.role not in {'professional','healthcare'}
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
        or request.user.role in {'professional','healthcare'}
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
