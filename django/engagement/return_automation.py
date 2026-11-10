"""Opt-in campaigns for customers due to return, dispatched through their company."""
from datetime import timedelta
from django.db import transaction
from django.conf import settings
from django.utils import timezone
from billing.entitlements import active_subscription,module_enabled
from communications.models import Notification, TenantWhatsAppConnection
from scheduling.models import Appointment
from .models import ReturnMessagingSettings, BehaviorProfile, CustomerContactThrottle


def eligible(customer,tenant,now=None):
    now=now or timezone.now()
    if not customer.active or not customer.consent_marketing or customer.tenant_id!=tenant.pk:
        return False
    if not Appointment.objects.filter(tenant=tenant,customer=customer,status='completed').exists():
        return False
    return not Appointment.objects.filter(tenant=tenant,customer=customer,starts_at__gte=now,
        status__in=['pending','confirmed','waiting','in_progress']).exists()


@transaction.atomic
def queue_return_campaign(tenant):
    config=ReturnMessagingSettings.objects.select_for_update().filter(tenant=tenant,enabled=True).first()
    from billing.access import current_subscription,subscription_allows_access
    if getattr(settings,'SUBSCRIPTION_ACCESS_ENFORCED',True) and not subscription_allows_access(current_subscription(tenant)):
        return 0
    if not config or tenant.deleted_at or tenant.archived_at:
        return 0
    if active_subscription(tenant) and (not module_enabled(tenant,'behavior') or not module_enabled(tenant,'whatsapp')):
        return 0
    if not TenantWhatsAppConnection.objects.filter(tenant=tenant,enabled=True).exists():
        return 0
    now=timezone.now()
    notices=Notification.objects.filter(tenant=tenant,template_key='return_invitation')
    used=notices.filter(created_at__gt=now-timedelta(hours=24)).exclude(status='skipped').count()
    quota=max(0,min(100,config.daily_limit)-used)
    count=0
    for profile in BehaviorProfile.objects.filter(tenant=tenant,next_expected_date__lte=timezone.localdate(),
        customer__active=True,customer__consent_marketing=True).select_related('customer').order_by('next_expected_date','pk')[:300]:
        customer=profile.customer
        if count>=quota:break
        if not eligible(customer,tenant,now):continue
        if CustomerContactThrottle.objects.filter(tenant=tenant,customer=customer,
            last_contact_at__gt=now-timedelta(days=max(1,config.cooldown_days))).exists():continue
        if notices.filter(payload__customer_id=customer.pk,status='queued').exists():continue
        if notices.filter(payload__customer_id=customer.pk,created_at__gt=now-timedelta(days=max(1,config.cooldown_days))).exists():continue
        Notification.objects.create(tenant=tenant,channel='whatsapp',destination=customer.phone,
            template_key='return_invitation',customer=customer,payload={'customer_id':customer.pk})
        count+=1
    return count


def deliver_return_invitation(notification):
    from scheduling.models import Customer
    from .contacting import send_return_invitation,contact_blocked
    customer=Customer.objects.filter(pk=notification.payload.get('customer_id'),tenant_id=notification.tenant_id).first()
    config=ReturnMessagingSettings.objects.filter(tenant_id=notification.tenant_id,enabled=True).first()
    profile=BehaviorProfile.objects.filter(tenant_id=notification.tenant_id,customer=customer,
        next_expected_date__lte=timezone.localdate()).first() if customer else None
    from billing.access import current_subscription,subscription_allows_access
    access_blocked=getattr(settings,'SUBSCRIPTION_ACCESS_ENFORCED',True) and not subscription_allows_access(current_subscription(notification.tenant))
    recently_contacted=bool(config and customer and CustomerContactThrottle.objects.filter(tenant_id=notification.tenant_id,customer=customer,last_contact_at__gt=timezone.now()-timedelta(days=max(1,config.cooldown_days))).exists())
    if access_blocked or notification.tenant.deleted_at or notification.tenant.archived_at or recently_contacted or not config or not profile or not eligible(customer,notification.tenant) or contact_blocked(notification.tenant,customer):
        notification.status='skipped';notification.save(update_fields=['status']);return ''
    conversation=send_return_invitation(tenant=notification.tenant,customer=customer,user=None)
    return conversation.messages.filter(direction='out').latest('pk').provider_message_id
