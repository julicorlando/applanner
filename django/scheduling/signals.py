from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Appointment


@receiver(post_save, sender=Appointment)
def start_return_intelligence(sender, instance, created, **kwargs):
    if not created or instance.status == Appointment.Status.CANCELLED:
        return
    from engagement.models import BehaviorEvent, BehaviorProfile, BehaviorServiceProfile

    _, first = BehaviorProfile.objects.get_or_create(tenant_id=instance.tenant_id, customer_id=instance.customer_id)
    BehaviorServiceProfile.objects.get_or_create(tenant_id=instance.tenant_id,
        customer_id=instance.customer_id, service_id=instance.service_id)
    if first:
        BehaviorEvent.objects.create(tenant_id=instance.tenant_id, customer_id=instance.customer_id,
            event_type="first_appointment", payload={"appointment_id": instance.pk})
