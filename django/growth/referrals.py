import secrets
from decimal import Decimal

from django.conf import settings
from django.core.signing import dumps
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from applanner.transactional_email import queue_email
from billing.models import Payment,Subscription
from billing.payment_services import platform_provider
from core.crypto import encrypt_text
from engagement.models import ReferralProfile
from scheduling.models import Professional

from .models import PlatformReferral,ReferralCampaign,ReferralPaymentCredit


def active_referral_campaign():
    now=timezone.now()
    return (
        ReferralCampaign.objects.filter(active=True)
        .filter(models.Q(starts_at__isnull=True)|models.Q(starts_at__lte=now))
        .filter(models.Q(ends_at__isnull=True)|models.Q(ends_at__gte=now))
        .order_by("-created_at").first()
    )


def referral_profile(user):
    profile=ReferralProfile.objects.filter(user=user,active=True).first()
    if profile:
        return profile
    while True:
        code=secrets.token_urlsafe(9).replace("-","").replace("_","")[:12].upper()
        if not ReferralProfile.objects.filter(referral_code=code).exists():
            return ReferralProfile.objects.create(user=user,referral_code=code,active=True)


def register_signup_referral(*,code,referred_tenant):
    campaign=active_referral_campaign()
    if not campaign or not code:
        return None
    profile=ReferralProfile.objects.select_related("user","user__tenant").filter(
        referral_code=code,active=True,
    ).first()
    if not profile or profile.user.tenant_id==referred_tenant.pk:
        return None
    professional=Professional.objects.filter(user=profile.user,active=True).first()
    referral,_=PlatformReferral.objects.get_or_create(
        referred_tenant=referred_tenant,
        defaults={
            "campaign":campaign,"referrer_user":profile.user,
            "referrer_tenant":profile.user.tenant,
            "referrer_professional":professional,
            "code_snapshot":profile.referral_code,
            "professional_reward_amount":campaign.professional_reward_amount if professional else Decimal("0"),
        },
    )
    return referral


def _cycle_months(cycle):
    return {"monthly":1,"quarterly":3,"semiannual":6,"annual":12}.get(cycle,1)


def _apply_company_discount(referral):
    subscription=(
        Subscription.objects.select_for_update()
        .filter(tenant=referral.referrer_tenant,status__in=[Subscription.Status.TRIAL,Subscription.Status.ACTIVE])
        .order_by("-started_at").first()
    )
    if not subscription:
        return Decimal("0")
    months=_cycle_months(subscription.billing_cycle)
    current=Decimal(subscription.contracted_price or 0).quantize(Decimal("0.01"))
    monthly=(current/Decimal(months)).quantize(Decimal("0.01"))
    campaign=referral.campaign
    if campaign.company_reward_type==ReferralCampaign.RewardType.PERCENT:
        monthly_discount=(monthly*campaign.company_reward_value/Decimal("100")).quantize(Decimal("0.01"))
    else:
        monthly_discount=Decimal(campaign.company_reward_value).quantize(Decimal("0.01"))
    monthly_discount=min(monthly_discount,monthly)
    cycle_discount=(monthly_discount*months).quantize(Decimal("0.01"))
    new_total=max(Decimal("0"),current-cycle_discount)

    if subscription.provider_subscription_id:
        from billing.module_services import _gateway_for
        gateway=_gateway_for(subscription)
        if gateway:
            platform_provider(gateway).update_subscription_amount(
                subscription.provider_subscription_id,new_total
            )
    subscription.contracted_price=new_total
    if subscription.base_contracted_price is not None:
        subscription.base_contracted_price=max(
            Decimal("0"),Decimal(subscription.base_contracted_price)-cycle_discount
        )
    subscription.save(update_fields=["contracted_price","base_contracted_price","updated_at"])
    return monthly_discount


@transaction.atomic
def process_referral_payment(payment):
    payment=Payment.objects.select_for_update().select_related("tenant").get(pk=payment.pk)
    if payment.status!=Payment.Status.PAID or payment.purpose!="subscription":
        return None
    referral=PlatformReferral.objects.select_for_update().select_related(
        "campaign","referrer_user","referrer_tenant","referrer_professional","referred_tenant",
    ).filter(referred_tenant=payment.tenant).first()
    if not referral or referral.status!=PlatformReferral.Status.PENDING:
        return referral
    _,created=ReferralPaymentCredit.objects.get_or_create(referral=referral,payment=payment)
    if not created:
        return referral
    referral.payment_count=referral.payment_credits.count()
    if referral.payment_count<max(2,referral.campaign.payment_threshold):
        referral.save(update_fields=["payment_count","updated_at"])
        return referral

    referral.qualified_at=timezone.now()
    if referral.referrer_professional_id:
        referral.professional_reward_amount=referral.campaign.professional_reward_amount
        referral.status=PlatformReferral.Status.AWAITING_PIX
        referral.pix_requested_at=timezone.now()
        token=dumps({"referral":referral.pk},salt="platform-referral-pix",compress=True)
        base=(settings.PUBLIC_BASE_URL or "").rstrip("/")
        url=base+reverse("referral-pix",args=[token])
        queue_email(
            referral.referrer_tenant or referral.referred_tenant,
            referral.referrer_user.email,
            "referral_pix_request",
            {
                "nome":referral.referrer_professional.name,
                "empresa_indicada":referral.referred_tenant.name,
                "url_pix":url,
            },
        )
    elif referral.referrer_tenant_id:
        referral.company_discount_amount=_apply_company_discount(referral)
        referral.status=PlatformReferral.Status.QUALIFIED
    else:
        referral.status=PlatformReferral.Status.CANCELLED
    referral.save()
    return referral


def save_referral_pix(*,referral,pix_key):
    value=(pix_key or "").strip()
    if len(value)<3 or len(value)>190:
        raise ValueError("Informe uma chave Pix válida.")
    referral.pix_key_encrypted=encrypt_text(value)
    referral.status=PlatformReferral.Status.READY
    referral.save(update_fields=["pix_key_encrypted","status","updated_at"])
    return referral


# Local import avoids loading django.db.models before app setup in tooling.
from django.db import models
