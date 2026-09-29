from django.db.models.signals import post_save,pre_save
from django.dispatch import receiver
from django.utils import timezone

from applanner.transactional_email import queue_email

from .models import Appointment


@receiver(pre_save,sender=Appointment)
def remember_confirmation_state(sender,instance,**kwargs):
    instance._previous_status=(sender.objects.filter(pk=instance.pk).values_list("status",flat=True).first()
        if instance.pk else None)


@receiver(post_save,sender=Appointment)
def notify_confirmed_appointment(sender,instance,created,**kwargs):
    if instance.status!=Appointment.Status.CONFIRMED or (
        not created and getattr(instance,"_previous_status",None)==Appointment.Status.CONFIRMED
    ):
        return
    if not instance.customer.email:
        return
    queue_email(instance.tenant,instance.customer.email,"booking_confirmation",{
        "nome":instance.customer.name,
        "empresa":instance.tenant.name,
        "servico":instance.service.name,
        "profissional":instance.professional.name if instance.professional_id else "A definir",
        "data_hora":timezone.localtime(instance.starts_at).strftime("%d/%m/%Y às %H:%M"),
    },customer=instance.customer)


@receiver(post_save,sender=Appointment)
def close_finished_appointment_conversation(sender,instance,**kwargs):
    if instance.status in {Appointment.Status.COMPLETED,Appointment.Status.CANCELLED,Appointment.Status.NO_SHOW}:
        from communications.models import WhatsAppConversation
        WhatsAppConversation.objects.filter(appointment=instance).update(status=WhatsAppConversation.Status.CLOSED)


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
