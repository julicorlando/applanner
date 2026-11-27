"""Read-only open windows; booking still validates the service and all rules."""
from datetime import datetime, timedelta

from django.utils import timezone


def subtract(windows, start, end):
    result = []
    for left, right in windows:
        if end <= left or start >= right:
            result.append((left, right))
        else:
            if left < start:
                result.append((left, start))
            if end < right:
                result.append((end, right))
    return result


def open_windows(tenant, unit, resources, days, rows, blocks, tz, arena=False):
    from scheduling.models import ProfessionalAvailability, ProfessionalBreak, TenantScheduleSettings
    from tenants.models import UnitBusinessHours
    resource_ids = [resource.pk for resource in resources]
    if not unit or not resource_ids:
        return {}
    key = 'court_id' if arena else 'professional_id'
    if arena:
        from arena.models import CourtHours, WaitlistEntry
        hours = list(CourtHours.objects.filter(tenant=tenant, court_id__in=resource_ids, active=True))
        pauses = []
        holds = list(WaitlistEntry.objects.filter(tenant=tenant, court_id__in=resource_ids, status='offered', offer_expires_at__gt=timezone.now(), offered_starts_at__isnull=False))
        buffer = 0
    else:
        hours = list(ProfessionalAvailability.objects.filter(tenant=tenant, professional_id__in=resource_ids, active=True))
        pauses = list(ProfessionalBreak.objects.filter(tenant=tenant, professional_id__in=resource_ids, active=True))
        holds = []
        settings = TenantScheduleSettings.objects.filter(tenant=tenant).first()
        buffer = (unit.schedule_overrides or {}).get('buffer_minutes', getattr(settings, 'buffer_minutes', 0))
    unit_hours = {item.weekday: item for item in UnitBusinessHours.objects.filter(tenant=tenant, unit=unit, active=True)}
    now = timezone.now().astimezone(tz)
    result = {}
    for day in days:
        result[day] = []
        business = unit_hours.get(day.isoweekday())
        if day < now.date() or (business and (business.closed or not business.opens_at or not business.closes_at)):
            continue
        for resource in resources:
            windows = [(datetime.combine(day, item.start_time, tz), datetime.combine(day, item.end_time, tz)) for item in hours if getattr(item, key) == resource.pk and item.weekday == day.isoweekday()]
            if business:
                left, right = datetime.combine(day, business.opens_at, tz), datetime.combine(day, business.closes_at, tz)
                windows = [(max(a, left, now), min(b, right)) for a, b in windows if max(a, left, now) < min(b, right)]
            else:
                windows = [(max(a, now), b) for a, b in windows if max(a, now) < b]
            for pause in pauses:
                if getattr(pause, key) == resource.pk and pause.weekday == day.isoweekday():
                    windows = subtract(windows, datetime.combine(day, pause.start_time, tz), datetime.combine(day, pause.end_time, tz))
            margin = timedelta(minutes=resource.interval_minutes if arena else buffer)
            for row in rows:
                blocking = row.status in {'pending_payment', 'confirmed', 'completed'} if arena else row.status not in {'cancelled', 'no_show'}
                if blocking and getattr(row, key) == resource.pk:
                    windows = subtract(windows, row.starts_at.astimezone(tz) - margin, row.ends_at.astimezone(tz) + margin)
            for block in blocks:
                if getattr(block, key) == resource.pk:
                    extra = margin if arena else timedelta()
                    windows = subtract(windows, block.starts_at.astimezone(tz) - extra, block.ends_at.astimezone(tz) + extra)
            for hold in holds:
                if hold.court_id == resource.pk:
                    start = hold.offered_starts_at.astimezone(tz)
                    windows = subtract(windows, start - margin, start + timedelta(minutes=hold.duration_minutes) + margin)
            for start, end in windows:
                minutes = int((end - start).total_seconds() // 60)
                if minutes < (resource.minimum_minutes if arena else 5):
                    continue
                result[day].append({'name': resource.name, 'resource': resource.pk, 'start': start, 'end': end, 'minutes': minutes})
        result[day].sort(key=lambda item: (item['start'], item['name']))
    return result
