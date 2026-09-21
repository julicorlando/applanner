from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from communications.models import Notification
from .models import Appointment, AppointmentReminderLog, TenantScheduleSettings


def _queue_reminder(appointment,key,channel,destination):
    log,created=AppointmentReminderLog.objects.get_or_create(
        tenant=appointment.tenant,
        appointment=appointment,
        reminder_key=key,
        channel=channel,
        defaults={"status":AppointmentReminderLog.Status.QUEUED},
    )
    if not created:
        return False

    Notification.objects.create(
        tenant=appointment.tenant,
        customer=appointment.customer,
        channel=channel,
        destination=destination,
        template_key=f"appointment_{key}",
        payload={
            "subject":"Lembrete de agendamento",
            "text":(
                f"Olá, {appointment.customer.name}. "
                f"Seu agendamento está marcado para "
                f"{timezone.localtime(appointment.starts_at).strftime('%d/%m/%Y às %H:%M')}."
            ),
            "appointment_id":appointment.pk,
        },
        status=Notification.Status.QUEUED,
    )
    return True


@shared_task
def queue_appointment_reminders():
    now=timezone.now()
    window_start=now+timedelta(hours=1,minutes=50)
    window_end=now+timedelta(hours=24,minutes=10)

    appointments=(
        Appointment.objects
        .filter(
            status__in=[Appointment.Status.PENDING,Appointment.Status.CONFIRMED],
            starts_at__gte=window_start,
            starts_at__lte=window_end,
        )
        .select_related("tenant","customer")
    )

    queued=0
    for appointment in appointments:
        settings_obj,_=TenantScheduleSettings.objects.get_or_create(tenant=appointment.tenant)
        delta=appointment.starts_at-now

        if settings_obj.reminder_24h_enabled and timedelta(hours=23,minutes=50)<=delta<=timedelta(hours=24,minutes=10):
            if appointment.customer.email:
                with transaction.atomic():
                    queued+=int(_queue_reminder(appointment,"24h",Notification.Channel.EMAIL,appointment.customer.email))

        if settings_obj.reminder_2h_enabled and timedelta(hours=1,minutes=50)<=delta<=timedelta(hours=2,minutes=10):
            if appointment.customer.email:
                with transaction.atomic():
                    queued+=int(_queue_reminder(appointment,"2h",Notification.Channel.EMAIL,appointment.customer.email))

    return queued
