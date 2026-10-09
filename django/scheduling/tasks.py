from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from communications.models import Notification
from .models import Appointment, AppointmentReminderLog


def _dispatch_notification(pk):
    from communications.tasks import send_notification
    try:
        send_notification.delay(pk)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Não foi possível despachar o lembrete %s; a fila periódica tentará novamente.",pk)


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

    link=""
    if appointment.customer_manage_token_encrypted:
        from core.crypto import decrypt_text
        token=decrypt_text(appointment.customer_manage_token_encrypted)
        link=f" Para reagendar ou cancelar: {settings.PUBLIC_BASE_URL.rstrip('/')}{reverse('public-appointment-page',args=[token])}"
    notification=Notification.objects.create(
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
                f"{timezone.localtime(appointment.starts_at).strftime('%d/%m/%Y às %H:%M')}.{link}"
            ),
            "appointment_id":appointment.pk,
        },
        status=Notification.Status.QUEUED,
    )
    transaction.on_commit(lambda pk=notification.pk: _dispatch_notification(pk))
    return True


@shared_task
def queue_appointment_reminders():
    now=timezone.now()
    window_start=now+timedelta(hours=2)
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
        from .availability import AvailabilityService
        settings_obj=AvailabilityService().settings(appointment.tenant,unit=appointment.unit)
        delta=appointment.starts_at-now

        if settings_obj.reminder_24h_enabled and timedelta(hours=23,minutes=50)<=delta<=timedelta(hours=24,minutes=10):
            if appointment.customer.email:
                with transaction.atomic():
                    queued+=int(_queue_reminder(appointment,"24h",Notification.Channel.EMAIL,appointment.customer.email))

        if settings_obj.reminder_2h_enabled and timedelta(hours=2)<=delta<=timedelta(hours=3):
            if appointment.customer.email:
                with transaction.atomic():
                    queued+=int(_queue_reminder(appointment,"2h",Notification.Channel.EMAIL,appointment.customer.email))
            if appointment.customer.phone:
                # Email and WhatsApp have independent deduplication keys.
                with transaction.atomic():
                    log,created=AppointmentReminderLog.objects.get_or_create(tenant=appointment.tenant,
                        appointment=appointment,reminder_key="2h",channel=AppointmentReminderLog.Channel.WHATSAPP,
                        defaults={"status":AppointmentReminderLog.Status.QUEUED})
                    if created:
                        from communications.tenant_whatsapp import queue_appointment_whatsapp
                        notification=queue_appointment_whatsapp(appointment,"reminder")
                        if notification:
                            transaction.on_commit(lambda pk=notification.pk: _dispatch_notification(pk))
                            queued+=1
                        else:
                            log.delete()

    return queued
