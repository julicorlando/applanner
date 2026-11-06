from celery import shared_task
from django.utils import timezone

from communications.models import Notification

from .models import CRMEvent


@shared_task
def process_auto_crm(limit=200):
    events=(
        CRMEvent.objects
        .filter(status=CRMEvent.Status.PENDING,due_at__lte=timezone.localdate())
        .select_related("tenant","customer","vehicle")
        .order_by("due_at")[:limit]
    )
    count=0
    for event in events:
        destination=event.customer.phone or event.customer.email
        channel=Notification.Channel.WHATSAPP if event.customer.phone else Notification.Channel.EMAIL
        if not destination:
            event.status=CRMEvent.Status.DONE
            event.save(update_fields=["status","updated_at"])
            continue
        Notification.objects.create(
            tenant=event.tenant,
            customer=event.customer,
            channel=channel,
            destination=destination,
            payload={
                "subject":"Lembrete automotivo",
                "text":f"Olá {event.customer.name}, há um retorno recomendado para o veículo {event.vehicle.plate}.",
            },
        )
        event.status=CRMEvent.Status.NOTIFIED
        event.channel=channel
        event.notified_at=timezone.now()
        event.save(update_fields=["status","channel","notified_at","updated_at"])
        count+=1
    return count
