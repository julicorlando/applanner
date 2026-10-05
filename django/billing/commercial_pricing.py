"""Catalog offers, immutable contract prices and explicitly announced renewals."""
from decimal import Decimal
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .breakdown import CYCLE_MONTHS
from .models import Subscription, SubscriptionPriceChange, Payment

CENT=Decimal('0.01')
def cycle_price(plan,cycle):
    months=CYCLE_MONTHS[cycle]
    explicit=getattr(plan,cycle+'_price',None)
    if cycle=='monthly': explicit=plan.monthly_price
    if explicit is not None: return Decimal(explicit).quantize(CENT)
    discount=Decimal(getattr(plan,cycle+'_discount',0) or 0)
    return (Decimal(plan.monthly_price)*months*(1-discount/100)).quantize(CENT)

def offer(plan,cycle,now=None):
    now=now or timezone.now()
    regular=cycle_price(plan,cycle)
    promotional=(cycle=='monthly' and plan.promotion_price is not None and plan.promotion_months>0
        and (not plan.promotion_starts_at or now>=plan.promotion_starts_at)
        and (not plan.promotion_ends_at or now<plan.promotion_ends_at))
    return {'regular':regular,'amount':plan.promotion_price if promotional else regular,
        'promotion_months':plan.promotion_months if promotional else 0,
        'saving':(Decimal(plan.monthly_price)*CYCLE_MONTHS[cycle]-regular).quantize(CENT)}

@transaction.atomic
def freeze_plan_contracts(plan):
    """Capture legacy prices before a catalog edit; never replace a saved contract."""
    for sub in Subscription.objects.select_for_update().filter(plan=plan,base_contracted_price__isnull=True):
        base=(sub.contracted_price-sub.addon_contracted_price if sub.contracted_price is not None
              else cycle_price(plan,sub.billing_cycle))
        sub.base_contracted_price=max(Decimal('0'),base)
        if sub.contracted_price is None: sub.contracted_price=base+sub.addon_contracted_price
        sub.save(update_fields=['base_contracted_price','contracted_price','updated_at'])

def notify_price_change(change):
    from accounts.models import User
    from communications.models import Notification
    from communications.models import UserNotification
    message=f'O valor base do plano será R$ {change.new_base_price:.2f} por ciclo a partir da renovação de {timezone.localtime(change.effective_at):%d/%m/%Y}. Adicionais contratados são cobrados separadamente. Confira em Plano e pagamentos.'
    users=list(User.objects.filter(tenant=change.subscription.tenant,role__in=['owner','manager'],is_active=True))
    for user in users:
        UserNotification.objects.create(tenant=change.subscription.tenant,user=user,type='subscription',title='Aviso de alteração de preço',message=message,action_url='/billing/assinatura/',severity='warning')
    for email in {user.email for user in users if user.email}:
        Notification.objects.create(tenant=change.subscription.tenant,channel='email',destination=email,template_key='subscription_price_change',payload={'subject':'ApPlanner — aviso de alteração de preço','text':message,'price_change_id':change.pk})

@transaction.atomic
def schedule_plan_renewals(plan,user,now=None):
    now=now or timezone.now(); count=0
    for sub in Subscription.objects.select_for_update().filter(plan=plan,status__in=['active','trial','past_due']).select_related('tenant').order_by('pk'):
        if sub.tenant.deleted_at or sub.tenant.archived_at: continue
        if Subscription.objects.filter(tenant=sub.tenant).order_by('-started_at','-pk').values_list('pk',flat=True).first()!=sub.pk: continue
        if sub.price_changes.filter(reason='catalog',status='pending').exists(): continue
        target=max(now+timedelta(days=30),sub.promotion_ends_at or now)
        from .access import paid_access_until
        effective=paid_access_until(sub) or sub.next_billing_at or sub.trial_ends_at or target
        if not sub.payments.filter(status='paid',purpose='subscription').exists():
            effective=max(effective,target)+relativedelta(months=CYCLE_MONTHS[sub.billing_cycle])
        while effective<target: effective+=relativedelta(months=CYCLE_MONTHS[sub.billing_cycle])
        new=cycle_price(plan,sub.billing_cycle)
        regular=sub.regular_base_price if sub.regular_base_price is not None else sub.base_contracted_price
        if regular is not None and regular==new: continue
        change=SubscriptionPriceChange.objects.create(subscription=sub,new_base_price=new,effective_at=effective,reason='catalog',created_by=user)
        notify_price_change(change)
        from core.audit import append_audit
        append_audit(tenant=sub.tenant,user=user,action='subscription.price_change_scheduled',entity_type='billing.SubscriptionPriceChange',entity_id=change.pk,before={'base':str(regular)},after={'base':str(new),'effective_at':effective.isoformat()})
        count+=1
    return count

@transaction.atomic
def prepare_price_changes(subscription,now=None):
    """Update the next unpaid cycle only after earlier cycles have been paid.

    Card recurrence is synchronized ahead of that renewal, not after charging it.
    A pending payment retains its original quote. Provider failures retain the old contract.
    """
    from .module_services import _gateway_for
    from .payment_services import platform_provider
    now=now or timezone.now()
    sub=Subscription.objects.select_for_update().select_related('plan','tenant').get(pk=subscription.pk)
    latest=Subscription.objects.filter(tenant=sub.tenant).order_by('-started_at','-pk').first()
    if latest.pk!=sub.pk or sub.status in ['cancelled','suspended'] or sub.tenant.deleted_at or sub.tenant.archived_at: return sub
    from .access import paid_access_until
    due=paid_access_until(sub) or sub.next_billing_at or now
    pending=Payment.objects.filter(subscription=sub,status='pending')
    if pending.filter(Q(pix_charges__isnull=True)|Q(pix_charges__expires_at__gt=now)).exists(): return sub
    changes=[change for change in sub.price_changes.select_for_update().filter(status='pending').order_by('effective_at','pk')
        if due>=change.effective_at or now>=change.effective_at]
    if not changes: return sub
    old=sub.base_contracted_price
    if old is None: old=(sub.contracted_price or cycle_price(sub.plan,sub.billing_cycle))-sub.addon_contracted_price
    previous=Decimal(sub.contracted_price if sub.contracted_price is not None else old+sub.addon_contracted_price)
    new_base=changes[-1].new_base_price
    new_total=(previous+new_base-old).quantize(CENT)
    if new_total<=0: raise ValueError("O total após o reajuste deve ser positivo; revise descontos contratuais ou conceda uma isenção.")
    gateway=_gateway_for(sub)
    if gateway: platform_provider(gateway).update_subscription_amount(sub.provider_subscription_id,new_total)
    try:
        with transaction.atomic():
            sub.base_contracted_price=new_base;sub.contracted_price=new_total;sub.regular_base_price=new_base
            sub.save(update_fields=['base_contracted_price','contracted_price','regular_base_price','updated_at'])
            for change in changes:
                change.status='applied';change.applied_at=now;change.save(update_fields=['status','applied_at','updated_at'])
            from core.audit import append_audit
            append_audit(tenant=sub.tenant,action='subscription.price_renewal',entity_type='billing.Subscription',entity_id=sub.pk,before={'base':str(old)},after={'base':str(new_base),'changes':[change.pk for change in changes]})
    except Exception:
        if gateway:
            try: platform_provider(gateway).update_subscription_amount(sub.provider_subscription_id,previous)
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Falha ao reverter preço no provedor da assinatura %s',sub.pk)
        raise
    return sub


def quote_payload(plan,cycle):
    selected=offer(plan,cycle)
    return {'plan':plan.pk,'cycle':cycle,'amount':str(selected['amount']),'regular':str(selected['regular']),
        'promotion_months':selected['promotion_months'],'features':plan.features}
