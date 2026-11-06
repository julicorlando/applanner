from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from .models import (
    Appointment,
    Professional,
    ProfessionalAvailability,
    ProfessionalBreak,
    ProfessionalTimeOff,
    Service,
    TenantScheduleSettings,
)


class AvailabilityService:
    def settings(self,tenant,unit=None):
        settings_obj,_=TenantScheduleSettings.objects.get_or_create(tenant=tenant)
        if unit and unit.tenant_id==tenant.pk:
            from copy import copy
            from core.unit_settings import AGENDA_FIELDS
            settings_obj=copy(settings_obj)
            for key,value in (unit.schedule_overrides or {}).items():
                if key in AGENDA_FIELDS:
                    setattr(settings_obj,key,value)
        return settings_obj

    def service(self,tenant,service_id):
        return Service.objects.filter(pk=service_id,tenant=tenant,active=True).first()

    def professional_offers(self,tenant,professional_id,service_id):
        professional=Professional.objects.filter(pk=professional_id,tenant=tenant,active=True).first()
        if not professional:
            return False
        service=self.service(tenant,service_id)
        if not service or service.unit_id not in (None,professional.unit_id):
            return False
        if not professional.services_restricted and not professional.services.exists():
            return True
        return professional.services.filter(pk=service_id,tenant=tenant,active=True).exists()

    def is_available(self,tenant,professional,start,end,exclude_appointment_id=None,public_rules=True,service=None):
        tz=ZoneInfo(tenant.timezone or "America/Recife")
        start=start.astimezone(tz)
        end=end.astimezone(tz)
        if start.date()!=end.date() or end<=start:
            return False

        if professional.unit_id:
            hours=professional.unit.business_hours.filter(weekday=start.isoweekday(),active=True).first()
            if hours and (hours.closed or not hours.opens_at or not hours.closes_at
                          or start.time()<hours.opens_at or end.time()>hours.closes_at):
                return False
        schedule=self.settings(tenant,unit=professional.unit)
        now=timezone.now().astimezone(tz)
        if public_rules:
            if start < now + timedelta(minutes=schedule.minimum_notice_minutes):
                return False
            if start > now + timedelta(days=schedule.maximum_days_ahead):
                return False

        availability=ProfessionalAvailability.objects.filter(
            tenant=tenant,
            professional=professional,
            weekday=start.isoweekday(),
            active=True,
        ).first()
        if not availability:
            return False

        available_start=datetime.combine(start.date(),availability.start_time,tzinfo=tz)
        available_end=datetime.combine(start.date(),availability.end_time,tzinfo=tz)
        if start < available_start or end > available_end:
            return False

        if ProfessionalBreak.objects.filter(
            tenant=tenant,
            professional=professional,
            weekday=start.isoweekday(),
            active=True,
            start_time__lt=end.timetz().replace(tzinfo=None),
            end_time__gt=start.timetz().replace(tzinfo=None),
        ).exists():
            return False

        if ProfessionalTimeOff.objects.filter(
            tenant=tenant,
            professional=professional,
            status=ProfessionalTimeOff.Status.ACTIVE,
            starts_at__lt=end,
            ends_at__gt=start,
        ).exists():
            return False

        from barber.models import StageReservation
        from barber.stages import intervals, resources_free
        spans=[(start,end)]
        if service is not None:
            if service.tenant_id!=tenant.pk:
                return False
            stages=intervals(service,start)
            if stages:
                if stages[-1][2]!=end or not resources_free(tenant,service,professional,start,exclude=exclude_appointment_id):
                    return False
                spans=[(begin,stop) for stage,begin,stop in stages if stage.professional_required]
        for begin,stop in spans:
            busy_start=begin-timedelta(minutes=schedule.buffer_minutes)
            busy_end=stop+timedelta(minutes=schedule.buffer_minutes)
            conflicts=Appointment.objects.filter(tenant=tenant,professional=professional,
                starts_at__lt=busy_end,ends_at__gt=busy_start,
                stage_reservations__isnull=True).exclude(status__in=['cancelled','no_show'])
            staged=StageReservation.objects.filter(tenant=tenant,professional=professional,
                starts_at__lt=busy_end,ends_at__gt=busy_start).exclude(appointment__status__in=['cancelled','no_show'])
            if exclude_appointment_id:
                conflicts=conflicts.exclude(pk=exclude_appointment_id)
                staged=staged.exclude(appointment_id=exclude_appointment_id)
            if conflicts.exists() or staged.exists():
                return False
        return True

    def slots(self,tenant,service_id,professional_id,day,public_rules=True,limit=96):
        service=self.service(tenant,service_id)
        if not service or not self.professional_offers(tenant,professional_id,service_id):
            return []

        professional=Professional.objects.filter(pk=professional_id,tenant=tenant,active=True).first()
        if not professional:
            return []

        availability=ProfessionalAvailability.objects.filter(
            tenant=tenant,
            professional=professional,
            weekday=day.isoweekday(),
            active=True,
        ).first()
        if not availability:
            return []

        schedule=self.settings(tenant,unit=professional.unit)
        tz=ZoneInfo(tenant.timezone or "America/Recife")
        cursor=datetime.combine(day,availability.start_time,tzinfo=tz)
        finish=datetime.combine(day,availability.end_time,tzinfo=tz)
        duration=timedelta(minutes=service.duration_minutes)
        step=timedelta(minutes=max(5,schedule.slot_interval_minutes))
        slots=[]

        while cursor+duration<=finish:
            end=cursor+duration
            if self.is_available(tenant,professional,cursor,end,public_rules=public_rules,service=service):
                slots.append({
                    "value":cursor.isoformat(),
                    "label":cursor.strftime("%H:%M"),
                })
            cursor+=step
            if len(slots)>=limit:
                break
        return slots
