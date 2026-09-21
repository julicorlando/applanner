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
