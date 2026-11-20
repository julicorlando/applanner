"""Fast public discovery followed by the canonical availability check."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.db.models import Q
from django.utils import timezone
from .availability import AvailabilityService
from .models import (
    Appointment,
    Professional,
    ProfessionalAvailability,
    ProfessionalBreak,
    ProfessionalTimeOff,
    Service,
)


def today_slot(tenant, unit):
    if not tenant.public_booking_enabled:
        return None
    tz = ZoneInfo(tenant.timezone or "America/Recife")
    now = timezone.now().astimezone(tz)
    day = now.date()
    from billing.segment_access import segment_enabled

    if segment_enabled(tenant, "arena"):
        from arena.models import Court
        from arena.services import ArenaReservationService

        engine = ArenaReservationService()
        for court in Court.objects.filter(
            tenant=tenant, unit=unit, active=True
        ).order_by("pk"):
            slots = engine.slots(tenant, court, day, court.minimum_minutes, limit=1)
            if slots:
                return {"label": slots[0]["label"], "resource": court.name}
        return None
    engine = AvailabilityService()
    settings = engine.settings(tenant, unit)
    earliest = now + timedelta(minutes=settings.minimum_notice_minutes)
    if earliest.date() != day:
        return None
    start = datetime.combine(day, time.min, tz)
    end = start + timedelta(days=1)
    services = list(
        Service.objects.filter(tenant=tenant, active=True)
        .filter(Q(unit=unit) | Q(unit__isnull=True))
        .order_by("duration_minutes", "pk")
    )
    professionals = list(
        Professional.objects.filter(tenant=tenant, unit=unit, active=True)
        .prefetch_related("services")
        .order_by("pk")
    )
    ids = [p.pk for p in professionals]
    schedules = {}
    for row in ProfessionalAvailability.objects.filter(
        tenant=tenant, professional_id__in=ids, active=True, weekday=day.isoweekday()
    ).order_by("pk"):
        schedules.setdefault(row.professional_id, row)
    breaks = list(
        ProfessionalBreak.objects.filter(
            tenant=tenant,
            professional_id__in=ids,
            active=True,
            weekday=day.isoweekday(),
        )
    )
    off = list(
        ProfessionalTimeOff.objects.filter(
            tenant=tenant,
            professional_id__in=ids,
            status="active",
            starts_at__lt=end,
            ends_at__gt=start,
        )
    )
    buffer = timedelta(minutes=settings.buffer_minutes)
    busy = list(
        Appointment.objects.filter(
            tenant=tenant,
            professional_id__in=ids,
            starts_at__lt=end + buffer,
            ends_at__gt=start - buffer,
        ).exclude(status__in=["cancelled", "no_show"])
    )
    hours = unit.business_hours.filter(active=True, weekday=day.isoweekday()).first()
    if hours and (hours.closed or not hours.opens_at or not hours.closes_at):
        return None
    candidates = []
    for pro in professionals:
        availability = schedules.get(pro.pk)
        if not availability:
            continue
        linked = list(pro.services.all())
        eligible = {
            row.pk for row in linked if row.active and row.tenant_id == tenant.pk
        }
        for service in services:
            if (pro.services_restricted or linked) and service.pk not in eligible:
                continue
            duration = timedelta(minutes=service.duration_minutes)
            cursor = datetime.combine(day, availability.start_time, tz)
            finish = datetime.combine(day, availability.end_time, tz)
            step = timedelta(minutes=max(5, settings.slot_interval_minutes))
            while cursor + duration <= finish:
                stop = cursor + duration
                valid = cursor >= earliest
                if hours and (
                    cursor.time() < hours.opens_at or stop.time() > hours.closes_at
                ):
                    valid = False
                if any(
                    row.professional_id == pro.pk
                    and row.start_time < stop.time()
                    and row.end_time > cursor.time()
                    for row in breaks
                ):
                    valid = False
                if any(
                    row.professional_id == pro.pk
                    and row.starts_at < stop
                    and row.ends_at > cursor
                    for row in off
                ):
                    valid = False
                if any(
                    row.professional_id == pro.pk
                    and row.starts_at < stop + buffer
                    and row.ends_at > cursor - buffer
                    for row in busy
                ):
                    valid = False
                if valid:
                    candidates.append((cursor, stop, pro, service))
                cursor += step
    for cursor, stop, pro, service in sorted(candidates, key=lambda row: row[0]):
        # Revalidate live rules and eligibility; discovery never books a slot.
        if engine.professional_offers(
            tenant, pro.pk, service.pk
        ) and engine.is_available(tenant, pro, cursor, stop, public_rules=True):
            return {"label": cursor.strftime("%H:%M"), "resource": service.name}
    return None
