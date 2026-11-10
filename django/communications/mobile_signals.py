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


from django.db.models.signals import pre_save
from .mobile_delivery import arena_event
from .platform_events import install

install()


@receiver(pre_save, sender="arena.Reservation")
def remember_arena_push_state(sender, instance, **kwargs):
    instance._push_arena_previous = sender.objects.filter(pk=instance.pk).values(
        "status", "starts_at", "court_id").first() if instance.pk else None


@receiver(post_save, sender="arena.Reservation")
def notify_arena_device(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    current = {key: getattr(instance, key) for key in ("status", "starts_at", "court_id")}
    if created or getattr(instance, "_push_arena_previous", None) != current:
        arena_event(instance, created=created)
