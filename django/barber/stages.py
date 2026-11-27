"""One canonical appointment; professional released only in configured pauses."""

from datetime import timedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from scheduling.models import Appointment, Service
from .models import ServiceStage, StageReservation

INACTIVE = ["cancelled", "no_show"]


def intervals(service, start):
    cursor = start
    result = []
    for stage in service.stages.select_related("resource").all():
        if stage.tenant_id != service.tenant_id or stage.minutes < 1:
            raise ValidationError("Etapas inválidas.")
        stop = cursor + timedelta(minutes=stage.minutes)
        result.append((stage, cursor, stop))
        cursor = stop
    if result and cursor != start + timedelta(minutes=service.duration_minutes):
        raise ValidationError("A soma das etapas deve ser igual à duração do serviço.")
    return result


def resources_free(tenant, service, professional, start, unit_id=None, exclude=None):
    for stage, begin, stop in intervals(service, start):
        if stage.resource_id:
            resource = stage.resource
            if (
                not resource.active
                or resource.tenant_id != tenant.pk
                or resource.unit_id != (unit_id or professional.unit_id)
            ):
                return False
            busy = StageReservation.objects.filter(
                tenant=tenant, resource=resource, starts_at__lt=stop, ends_at__gt=begin
            ).exclude(appointment__status__in=INACTIVE)
            if exclude:
                busy = busy.exclude(appointment_id=exclude)
            if busy.exists():
                return False
    return True


@transaction.atomic
def configure_stages(tenant, service, rows):
    if service.tenant_id != tenant.pk:
        raise ValidationError("Serviço de outra empresa.")
    if service.unit_id:
        from tenants.models import Unit

        Unit.objects.select_for_update().get(pk=service.unit_id, tenant=tenant)
    Service.objects.select_for_update().get(pk=service.pk, tenant=tenant)
    from django.utils import timezone

    if (
        Appointment.objects.filter(
            tenant=tenant, service=service, ends_at__gt=timezone.now()
        )
        .exclude(status__in=INACTIVE)
        .exists()
    ):
        raise ValidationError(
            "Encerre os agendamentos futuros antes de alterar as etapas."
        )
    if not rows:
        service.stages.all().delete()
        return
    if (
        len(rows) > 12
        or sum(row["minutes"] for row in rows) != service.duration_minutes
    ):
        raise ValidationError(
            "Cadastre até 12 etapas cuja soma seja a duração do serviço."
        )
    if not any(row["professional_required"] for row in rows):
        raise ValidationError("Ao menos uma etapa precisa de profissional.")
    for row in rows:
        resource = row.get("resource")
        if (
            row["minutes"] < 1
            or resource
            and (resource.tenant_id != tenant.pk or resource.unit_id != service.unit_id)
        ):
            raise ValidationError("Recurso de outra unidade ou duração inválida.")
    service.stages.all().delete()
    ServiceStage.objects.bulk_create(
        [
            ServiceStage(tenant=tenant, service=service, position=i, **row)
            for i, row in enumerate(rows)
        ]
    )


def snapshot(appointment):
    rows = intervals(appointment.service, appointment.starts_at)
    if rows and appointment.ends_at != rows[-1][2]:
        raise ValidationError(
            "O atendimento precisa ter a duração completa das etapas."
        )
    StageReservation.objects.bulk_create(
        [
            StageReservation(
                tenant=appointment.tenant,
                appointment=appointment,
                name=stage.name,
                starts_at=start,
                ends_at=end,
                professional=appointment.professional
                if stage.professional_required
                else None,
                resource=stage.resource,
            )
            for stage, start, end in rows
        ]
    )
