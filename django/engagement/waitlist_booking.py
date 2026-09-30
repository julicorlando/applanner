"""Convert a waiting customer into a scheduled or immediate professional visit."""
import hashlib
import secrets
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from core.crypto import encrypt_text

from billing.segment_access import require_feature
from scheduling.availability import AvailabilityService
from scheduling.models import (
    Appointment,Professional,ProfessionalBreak,ProfessionalTimeOff,
)
from .models import WaitlistEntry


def _instant_available(tenant,professional,start,end,availability):
    settings_obj=availability.settings(tenant)
    start_with_buffer=start-timedelta(minutes=settings_obj.buffer_minutes)
    end_with_buffer=end+timedelta(minutes=settings_obj.buffer_minutes)
    if Appointment.objects.filter(tenant=tenant,professional=professional,
            starts_at__lt=end_with_buffer,ends_at__gt=start_with_buffer).exclude(
            status__in=[Appointment.Status.CANCELLED,Appointment.Status.NO_SHOW]).exists():
        return False
    if ProfessionalTimeOff.objects.filter(tenant=tenant,professional=professional,
            status=ProfessionalTimeOff.Status.ACTIVE,starts_at__lt=end,ends_at__gt=start).exists():
        return False
    local=start.astimezone(ZoneInfo(tenant.timezone or "America/Recife"))
    local_end=end.astimezone(local.tzinfo)
    if local.date()!=local_end.date():
        return False
    return not ProfessionalBreak.objects.filter(
        tenant=tenant,professional=professional,weekday=local.isoweekday(),active=True,
        start_time__lt=local_end.time(),end_time__gt=local.time(),
    ).exists()


@transaction.atomic
def book_waitlist_for_professional(*,entry_id,professional,user,instant=False,starts_at=None):
    tenant=professional.tenant
    if user.role!="professional" or user.pk!=professional.user_id or user.tenant_id!=tenant.pk:
        raise ValidationError("Somente o profissional vinculado pode atender esta lista de espera.")
    if tenant.status not in ("active","trial") or tenant.deleted_at:
        raise ValidationError("A empresa não está habilitada para novos atendimentos.")
    require_feature(tenant,"waitlist")
    professional=Professional.objects.select_for_update().get(pk=professional.pk,tenant=tenant,user=user,active=True)
    entry=WaitlistEntry.objects.select_for_update().select_related("service","customer").get(pk=entry_id,tenant=tenant)
    if entry.status not in (WaitlistEntry.Status.WAITING,WaitlistEntry.Status.MATCHED) or entry.appointment_id:
        raise ValidationError("Este cliente já saiu da lista de espera.")
    if entry.professional_id and entry.professional_id!=professional.pk:
        raise ValidationError("O cliente escolheu outro profissional.")
    if not entry.service.active or not entry.customer.active:
        raise ValidationError("O serviço ou o cliente não está ativo.")
    if not entry.service.duration_minutes:
        raise ValidationError("O serviço precisa ter duração definida.")
    availability=AvailabilityService()
    if not availability.professional_offers(tenant,professional.pk,entry.service_id):
        raise ValidationError("Este profissional não oferece o serviço solicitado.")
    now=timezone.now()
    if instant:
        start=now
    else:
        if not starts_at or timezone.is_naive(starts_at):
            raise ValidationError("Selecione um horário disponível.")
        start=starts_at.astimezone(ZoneInfo(tenant.timezone or "America/Recife"))
        if start<now or start>now+timedelta(days=90):
            raise ValidationError("Escolha um horário futuro nos próximos 90 dias.")
    end=start+timedelta(minutes=entry.service.duration_minutes)
    if instant:
        if not _instant_available(tenant,professional,start,end,availability):
            raise ValidationError("Profissional ocupado, em intervalo ou afastado neste momento.")
    else:
        choices=availability.slots(tenant,entry.service_id,professional.pk,start.date(),public_rules=False)
        if not any(datetime.fromisoformat(slot["value"])==start for slot in choices):
            raise ValidationError("Este horário não está mais disponível. Escolha outro.")
    token=secrets.token_urlsafe(32)
    appointment=Appointment.objects.create(
        tenant=tenant,customer=entry.customer,professional=professional,service=entry.service,
        starts_at=start,ends_at=end,service_price_snapshot=entry.service.price,
        status=Appointment.Status.IN_PROGRESS if instant else Appointment.Status.CONFIRMED,
        source=Appointment.Source.WALK_IN if instant else Appointment.Source.INTERNAL,
        checked_in_at=now if instant else None,service_started_at=now if instant else None,
        created_by=user,notes=f"Lista de espera #{entry.pk}"+(f" — {entry.notes}" if entry.notes else ""),
        customer_manage_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        customer_manage_token_encrypted=encrypt_text(token),
    )
    entry.status=WaitlistEntry.Status.BOOKED
    entry.professional=professional
    entry.appointment=appointment
    entry.save(update_fields=["status","professional","appointment","updated_at"])
    return appointment
