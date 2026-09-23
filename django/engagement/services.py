from datetime import timedelta
from calendar import monthrange
from decimal import Decimal, ROUND_DOWN

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    CustomerPackage, CustomerPackageUsage, LoyaltyAccount, LoyaltyReward,
    LoyaltyTransaction, TenantLoyaltySettings,
)


@transaction.atomic
def consume_package_credit(*,customer_package,service,appointment=None,user=None,credits=1):
    package=(
        CustomerPackage.objects.select_for_update()
        .select_related("package","tenant","customer")
        .get(pk=customer_package.pk)
    )
    if package.status!=CustomerPackage.Status.ACTIVE:
        raise ValidationError("Pacote indisponível.")
    if package.expires_at and package.expires_at<=timezone.now():
        package.status=CustomerPackage.Status.EXPIRED
        package.save(update_fields=["status","updated_at"])
        raise ValidationError("Pacote expirado.")

    item=package.package.items.filter(service=service).first()
    if not item:
        raise ValidationError("Serviço não faz parte do pacote.")
    used=sum(package.usages.filter(service=service).values_list("credits_used",flat=True))
    if used+credits>item.credits:
        raise ValidationError("Créditos insuficientes para este serviço.")

    usage=CustomerPackageUsage.objects.create(
        customer_package=package,tenant=package.tenant,service=service,
        appointment=appointment,credits_used=credits,used_by=user,
    )
    total_credits=sum(package.package.items.values_list("credits",flat=True))
    total_used=sum(package.usages.values_list("credits_used",flat=True))
    if total_used>=total_credits:
        package.status=CustomerPackage.Status.EXHAUSTED
        package.save(update_fields=["status","updated_at"])
    return usage


@transaction.atomic
def earn_points(*,tenant,customer,amount,source_type="",source_id=None,user=None,note=""):
    settings_obj,_=TenantLoyaltySettings.objects.get_or_create(tenant=tenant)
    if not settings_obj.enabled:
        return 0
    points=int((Decimal(str(amount))*settings_obj.points_per_currency).to_integral_value(rounding=ROUND_DOWN))
    if points<=0:
        return 0

    account,_=LoyaltyAccount.objects.select_for_update().get_or_create(
        tenant=tenant,customer=customer,defaults={"points":0}
    )
    tx,created=LoyaltyTransaction.objects.get_or_create(
        tenant=tenant,customer=customer,type=LoyaltyTransaction.Type.EARN,
        source_type=source_type,source_id=source_id,
        defaults={"points":points,"note":note[:255],"user":user},
    )
    if not created:
        return 0
    account.points+=points
    account.save(update_fields=["points","updated_at"])
    return points


@transaction.atomic
def issue_reward(*,tenant,customer,user=None):
    settings_obj,_=TenantLoyaltySettings.objects.get_or_create(tenant=tenant)
    account=LoyaltyAccount.objects.select_for_update().get(tenant=tenant,customer=customer)
    if account.points<settings_obj.reward_points:
        raise ValidationError("Pontos insuficientes.")
    account.points-=settings_obj.reward_points
    account.save(update_fields=["points","updated_at"])
    LoyaltyTransaction.objects.create(
        tenant=tenant,customer=customer,type=LoyaltyTransaction.Type.REDEEM,
        points=-settings_obj.reward_points,note="Emissão de recompensa",user=user,
    )
    return LoyaltyReward.objects.create(
        tenant=tenant,customer=customer,points_spent=settings_obj.reward_points,
        reward_value=settings_obj.reward_value,issued_at=timezone.now(),
    )


@transaction.atomic
def purchase_package(*,tenant,customer,package,amount=None,external_reference=""):
    if package.tenant_id!=tenant.id or not package.active:
        raise ValidationError("Pacote indisponível.")
    purchased=timezone.now()
    return CustomerPackage.objects.create(
        tenant=tenant,customer=customer,package=package,purchased_at=purchased,
        expires_at=purchased+timedelta(days=package.validity_days) if package.validity_days else None,
        status=CustomerPackage.Status.ACTIVE,
        purchase_amount=Decimal(str(amount if amount is not None else package.price)),
        external_reference=external_reference[:190],
    )


@transaction.atomic
def create_membership(*,tenant,customer,package,cycle,amount=None,start_date=None,payer_email="",back_url="",online_payment=False):
    from .models import CustomerMembership
    if package.tenant_id!=tenant.id or not package.active or not package.recurring:
        raise ValidationError("Pacote recorrente indisponível.")
    if cycle not in {value for value,_ in CustomerMembership.Cycle.choices}:
        raise ValidationError("Ciclo inválido.")
    start=start_date or timezone.localdate()
    next_due=advance_months(start,3 if cycle==CustomerMembership.Cycle.QUARTERLY else 1)
    membership=CustomerMembership.objects.create(
        tenant=tenant,customer=customer,package=package,cycle=cycle,
        recurring_amount=Decimal(str(amount if amount is not None else package.price)),
        status=CustomerMembership.Status.ACTIVE,started_at=start,next_due_at=next_due,
    )
    if online_payment:
        if not payer_email or not back_url:
            raise ValidationError("E-mail e URL de retorno são obrigatórios para recorrência online.")
        from billing.payment_services import create_tenant_recurring_subscription
        recurring=create_tenant_recurring_subscription(
            tenant=tenant,reference_type="customer_membership",reference_id=membership.pk,
            amount=membership.recurring_amount,payer_email=payer_email,back_url=back_url,
            cycle_months=3 if cycle==CustomerMembership.Cycle.QUARTERLY else 1,
        )
        membership.billing_mode="provider"
        membership.provider_status=recurring.status
        membership.provider_subscription_id=recurring.provider_subscription_id
        membership.provider_checkout_url=recurring.checkout_url
        membership.save(update_fields=[
            "billing_mode","provider_status","provider_subscription_id",
            "provider_checkout_url","updated_at",
        ])
    return membership


def advance_months(value,months):
    target=(value.year*12+value.month-1)+months
    year,month=divmod(target,12)
    month+=1
    return value.replace(year=year,month=month,day=min(value.day,monthrange(year,month)[1]))


@transaction.atomic
def complete_referral(*,referral,user=None):
    from .models import LoyaltyReferral
    referral=LoyaltyReferral.objects.select_for_update().select_related("tenant","referrer").get(pk=referral.pk)
    if referral.status==LoyaltyReferral.Status.COMPLETED:
        return referral
    if referral.status!=LoyaltyReferral.Status.PENDING:
        raise ValidationError("Indicação não está pendente.")
    referral.status=LoyaltyReferral.Status.COMPLETED
    referral.completed_at=timezone.now()
    referral.save(update_fields=["status","completed_at","updated_at"])
    if referral.reward_points>0:
        account,_=LoyaltyAccount.objects.select_for_update().get_or_create(
            tenant=referral.tenant,customer=referral.referrer,defaults={"points":0}
        )
        LoyaltyTransaction.objects.create(
            tenant=referral.tenant,customer=referral.referrer,type=LoyaltyTransaction.Type.EARN,
            points=referral.reward_points,source_type="referral",source_id=referral.pk,
            note="Bonificação por indicação",user=user,
        )
        account.points+=referral.reward_points
        account.save(update_fields=["points","updated_at"])
    return referral


@transaction.atomic
def redeem_reward(*,reward,user=None):
    reward=LoyaltyReward.objects.select_for_update().get(pk=reward.pk)
    if reward.status!=LoyaltyReward.Status.AVAILABLE:
        raise ValidationError("Recompensa não está disponível.")
    reward.status=LoyaltyReward.Status.REDEEMED
    reward.redeemed_at=timezone.now()
    reward.redeemed_by=user
    reward.save(update_fields=["status","redeemed_at","redeemed_by"])
    return reward


@transaction.atomic
def match_waitlist(*,entry,user=None):
    from .models import WaitlistEntry
    entry=WaitlistEntry.objects.select_for_update().get(pk=entry.pk)
    if entry.status!=WaitlistEntry.Status.WAITING:
        raise ValidationError("Entrada não está aguardando.")
    entry.status=WaitlistEntry.Status.MATCHED
    entry.last_notified_at=timezone.now()
    entry.save(update_fields=["status","last_notified_at","updated_at"])
    return entry
