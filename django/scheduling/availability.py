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
    def settings(self,tenant):
        settings_obj,_=TenantScheduleSettings.objects.get_or_create(tenant=tenant)
        return settings_obj

    def service(self,tenant,service_id):
        return Service.objects.filter(pk=service_id,tenant=tenant,active=True).first()

    def professional_offers(self,tenant,professional_id,service_id):
        professional=Professional.objects.filter(pk=professional_id,tenant=tenant,active=True).first()
        if not professional:
            return False
        if not professional.services.exists():
            return True
        return professional.services.filter(pk=service_id,tenant=tenant,active=True).exists()

    def is_available(self,tenant,professional,start,end,exclude_appointment_id=None,public_rules=True):
        tz=ZoneInfo(tenant.timezone or "America/Recife")
        start=start.astimezone(tz)
        end=end.astimezone(tz)
        if start.date()!=end.date() or end<=start:
            return False

        schedule=self.settings(tenant)
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

        busy_start=start-timedelta(minutes=schedule.buffer_minutes)
        busy_end=end+timedelta(minutes=schedule.buffer_minutes)
        conflicts=Appointment.objects.filter(
            tenant=tenant,
            professional=professional,
            starts_at__lt=busy_end,
            ends_at__gt=busy_start,
        ).exclude(status__in=[Appointment.Status.CANCELLED,Appointment.Status.NO_SHOW])
        if exclude_appointment_id:
            conflicts=conflicts.exclude(pk=exclude_appointment_id)
        return not conflicts.exists()

    def slots(self,tenant,service_id,professional_id,day,public_rules=True):
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

        schedule=self.settings(tenant)
        tz=ZoneInfo(tenant.timezone or "America/Recife")
        cursor=datetime.combine(day,availability.start_time,tzinfo=tz)
        finish=datetime.combine(day,availability.end_time,tzinfo=tz)
        duration=timedelta(minutes=service.duration_minutes)
        step=timedelta(minutes=max(5,schedule.slot_interval_minutes))
        slots=[]

        while cursor+duration<=finish:
            end=cursor+duration
            if self.is_available(tenant,professional,cursor,end,public_rules=public_rules):
                slots.append({
                    "value":cursor.isoformat(),
                    "label":cursor.strftime("%H:%M"),
                })
            cursor+=step
            if len(slots)>=96:
                break
        return slots
