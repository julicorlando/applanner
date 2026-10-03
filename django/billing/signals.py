from django.db import transaction
from django.db.models.signals import post_delete,post_save
from django.dispatch import receiver

from tenants.models import Unit
from .models import Payment


def _queue(instance):
    tenant_id=instance.tenant_id
    transaction.on_commit(
        lambda: __import__("billing.tasks",fromlist=["sync_per_unit_addon_pricing_task"])
        .sync_per_unit_addon_pricing_task.delay(tenant_id)
    )


@receiver(post_save,sender=Unit)
def unit_saved(sender,instance,**kwargs):
    _queue(instance)


@receiver(post_delete,sender=Unit)
def unit_deleted(sender,instance,**kwargs):
    _queue(instance)


@receiver(post_save,sender=Payment)
def subscription_payment_saved(sender,instance,**kwargs):
    if instance.status!=Payment.Status.PAID or instance.purpose!="subscription" or not instance.tenant_id:
        return
    tenant_id=instance.tenant_id
    transaction.on_commit(
        lambda: __import__("engagement.tasks",fromlist=["qualify_referral_rewards_task"])
        .qualify_referral_rewards_task.delay(tenant_id)
    )
