from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone

from .models import MarketingDelivery, Notification


@shared_task(bind=True,max_retries=5,autoretry_for=(Exception,),retry_backoff=True,retry_jitter=True)
def send_notification(self,notification_id):
    with transaction.atomic():
        notification=Notification.objects.select_for_update().filter(pk=notification_id).first()
        if not notification or notification.status!=Notification.Status.QUEUED:
            return
        if notification.scheduled_at and notification.scheduled_at>timezone.now():
            return

        if notification.channel==Notification.Channel.EMAIL:
            subject=notification.payload.get("subject") or "ApPlanner"
            text=notification.payload.get("text") or notification.payload.get("message") or ""
            html=notification.payload.get("html")
            message=EmailMultiAlternatives(
                subject=subject,
                body=text,
                to=[notification.destination],
            )
            if html:
                message.attach_alternative(html,"text/html")
            message.send(fail_silently=False)
        else:
            raise RuntimeError(f"Canal ainda sem provider ativo: {notification.channel}")

        notification.status=Notification.Status.SENT
        notification.sent_at=timezone.now()
        notification.error_message=""
        notification.save(update_fields=["status","sent_at","error_message"])


@shared_task
def process_notification_queue(limit=100):
    ids=list(
        Notification.objects
        .filter(status=Notification.Status.QUEUED)
        .filter(scheduled_at__isnull=True)
        .order_by("created_at")
        .values_list("id",flat=True)[:limit]
    )
    scheduled_ids=list(
        Notification.objects
        .filter(status=Notification.Status.QUEUED,scheduled_at__lte=timezone.now())
        .order_by("scheduled_at")
        .values_list("id",flat=True)[:limit]
    )
    for notification_id in dict.fromkeys(ids+scheduled_ids):
        send_notification.delay(notification_id)
    return len(set(ids+scheduled_ids))


@shared_task(bind=True,max_retries=4,autoretry_for=(Exception,),retry_backoff=True)
def send_marketing_delivery(self,delivery_id):
    with transaction.atomic():
        delivery=(
            MarketingDelivery.objects
            .select_for_update()
            .select_related("campaign","lead")
            .filter(pk=delivery_id)
            .first()
        )
        if not delivery or delivery.status!=MarketingDelivery.Status.QUEUED:
            return
        if delivery.lead.status!="active" or not delivery.campaign.active:
            delivery.status=MarketingDelivery.Status.SKIPPED
            delivery.save(update_fields=["status","updated_at"])
            return

        message=EmailMultiAlternatives(
            subject=delivery.campaign.subject,
            body=delivery.campaign.body,
            to=[delivery.lead.email],
        )
        message.attach_alternative(delivery.campaign.body,"text/html")
        message.send(fail_silently=False)

        delivery.status=MarketingDelivery.Status.SENT
        delivery.sent_at=timezone.now()
        delivery.error_message=""
        delivery.save(update_fields=["status","sent_at","error_message","updated_at"])

        campaign=delivery.campaign
        campaign.sent_count=campaign.deliveries.filter(status=MarketingDelivery.Status.SENT).count()
        campaign.failed_count=campaign.deliveries.filter(status=MarketingDelivery.Status.FAILED).count()
        remaining=campaign.deliveries.filter(status=MarketingDelivery.Status.QUEUED).exists()
        if not remaining:
            campaign.status=campaign.Status.COMPLETED
            campaign.completed_at=timezone.now()
        else:
            campaign.status=campaign.Status.SENDING
        campaign.save(update_fields=["sent_count","failed_count","status","completed_at","updated_at"])


@shared_task
def process_marketing_deliveries(limit=100):
    ids=list(
        MarketingDelivery.objects
        .filter(status=MarketingDelivery.Status.QUEUED,campaign__active=True)
        .order_by("created_at")
        .values_list("id",flat=True)[:limit]
    )
    for delivery_id in ids:
        send_marketing_delivery.delay(delivery_id)
    return len(ids)
