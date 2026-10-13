from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import UserNotification
from .mobile_models import PushSubscription
from .mobile_delivery import queue_push


@receiver(post_save, sender=UserNotification)
def notify_user_device(sender, instance, created, **kwargs):
    if not created:
        return
    url = (
        instance.action_url
        if instance.action_url.startswith("/")
        and not instance.action_url.startswith("//")
        else "/"
    )
    for subscription in PushSubscription.objects.filter(
        user_id=instance.user_id, active=True
    ):
        queue_push(
            subscription,
            f"user-notification:{instance.pk}",
            {
                "title": "ApPlanner",
                "body": "Você tem uma nova notificação. Abra o aplicativo para conferir.",
                "url": url,
                "tag": f"notice-{instance.pk}",
            },
        )
