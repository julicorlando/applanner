import hashlib
import secrets
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from applanner.transactional_email import queue_email
from core.crypto import encrypt_text
from billing.models import Payment,Subscription
from billing.module_services import invalidate_pending_subscription_charges
from billing.payment_services import platform_provider
from .models import (
    ReferralIncentiveCampaign,ReferralProfile,ReferralReward,ReferralVisit,
)


def active_referral_campaign():
    now=timezone.now()
    return (
        ReferralIncentiveCampaign.objects.filter(active=True)
        .filter(Q(starts_at__isnull=True)|Q(starts_at__lte=now))
        .filter(Q(ends_at__isnull=True)|Q(ends_at__gte=now))
        .order_by("-created_at").first()
    )


def ensure_referral_profile(user):
    profile=getattr(user,"referral_profile",None)
    if profile:
        return profile
    while True:
        code=secrets.token_urlsafe(8).replace("-","").replace("_","")[:12].upper()
        if not ReferralProfile.objects.filter(referral_code=code).exists():
            return ReferralProfile.objects.create(user=user,referral_code=code,active=True)


def referral_redirect(request,code):
    campaign=active_referral_campaign()
    profile=get_object_or_404(
        ReferralProfile.objects.select_related("user"),referral_code=code,active=True
    )
    user=profile.user
    company_roles={"owner","manager","tenant-admin","barber-manager","arena-manager","auto-manager"}
    allowed=bool(
        campaign and user.tenant_id and (
            (user.role=="professional" and campaign.professional_referrals_enabled)
            or (user.role in company_roles and campaign.company_referrals_enabled)
        )
    )
    if not allowed:
        messages.info(request,"Esta campanha de indicação não está ativa.")
        return redirect("home")

    request.session["referral_code"]=profile.referral_code
    request.session["referral_campaign_id"]=campaign.pk
    request.session["referral_user_id"]=user.pk
    context=request.session.get("acquisition_context") or {}
    request.session["acquisition_context"]={
        **context,"source":"referral","medium":"referral","campaign":campaign.name[:120],
    }

    token=secrets.token_urlsafe(24)
    ReferralVisit.objects.create(
        referrer_user=user,
        visit_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        ip_hash=hashlib.sha256((request.META.get("REMOTE_ADDR") or "").encode()).hexdigest()
            if request.META.get("REMOTE_ADDR") else "",
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:500],
        clicked_at=timezone.now(),
    )
    return redirect("billing-plans")


def create_referral_reward_from_signup(request,tenant):
    campaign_id=request.session.get("referral_campaign_id")
    referrer_id=request.session.get("referral_user_id")
    if not campaign_id or not referrer_id:
        return None
    campaign=ReferralIncentiveCampaign.objects.filter(pk=campaign_id,active=True).first()
    if not campaign:
        return None
    from accounts.models import User
    referrer=User.objects.filter(pk=referrer_id,is_active=True).first()
    if not referrer or not referrer.tenant_id or referrer.tenant_id==tenant.pk:
        return None
    kind=(
        ReferralReward.ReferrerKind.PROFESSIONAL
        if referrer.role=="professional" else ReferralReward.ReferrerKind.COMPANY
    )
    if kind==ReferralReward.ReferrerKind.PROFESSIONAL and not campaign.professional_referrals_enabled:
        return None
    if kind==ReferralReward.ReferrerKind.COMPANY and not campaign.company_referrals_enabled:
        return None
    reward,_=ReferralReward.objects.get_or_create(
        campaign=campaign,referred_tenant=tenant,
        defaults={"referrer_user":referrer,"referrer_kind":kind},
    )
    visit=ReferralVisit.objects.filter(
        referrer_user=referrer,converted_tenant__isnull=True
    ).order_by("-clicked_at").first()
    if visit:
        visit.converted_tenant=tenant
        visit.converted_at=timezone.now()
        visit.save(update_fields=["converted_tenant","converted_at"])
    return reward


def _reward_amount(campaign,payment_amount):
    if campaign.reward_type==ReferralIncentiveCampaign.RewardType.PERCENT:
        return (Decimal(payment_amount or 0)*campaign.reward_value/Decimal("100")).quantize(Decimal("0.01"))
    return Decimal(campaign.reward_value or 0).quantize(Decimal("0.01"))


def _apply_company_discount(reward):
    referrer=reward.referrer_user
    subscription=(
        Subscription.objects.filter(
            tenant_id=referrer.tenant_id,
            status__in=[Subscription.Status.TRIAL,Subscription.Status.ACTIVE,Subscription.Status.PAST_DUE],
        ).order_by("-started_at").first()
    )
    if not subscription:
        return False
    previous=Decimal(subscription.contracted_price or 0).quantize(Decimal("0.01"))
    new_total=max(Decimal("0.00"),previous-reward.reward_amount).quantize(Decimal("0.01"))
    if new_total==previous:
        return False
    if subscription.provider_subscription_id:
        from billing.models import PaymentGateway
        gateway=PaymentGateway.objects.filter(
            provider="mercadopago",active=True,
            last_test_status=PaymentGateway.TestStatus.VALIDATED,
        )
        if subscription.provider_environment:
            gateway=gateway.filter(environment=subscription.provider_environment)
        gateway=gateway.first()
        if gateway:
            platform_provider(gateway).update_subscription_amount(
                subscription.provider_subscription_id,new_total
            )
    subscription.contracted_price=new_total
    if subscription.base_contracted_price is not None:
        subscription.base_contracted_price=max(
            Decimal("0.00"),Decimal(subscription.base_contracted_price)-reward.reward_amount
        ).quantize(Decimal("0.01"))
    subscription.save(update_fields=["contracted_price","base_contracted_price","updated_at"])
    invalidate_pending_subscription_charges(subscription)
    reward.status=ReferralReward.Status.APPLIED
    reward.applied_at=timezone.now()
    reward.save(update_fields=["status","applied_at","updated_at"])
    return True


def qualify_referral_rewards_for_tenant(tenant_id):
    paid=list(
        Payment.objects.filter(
            tenant_id=tenant_id,purpose="subscription",status=Payment.Status.PAID
        ).order_by("paid_at","pk")
    )
    rewards=ReferralReward.objects.select_related(
        "campaign","referrer_user","referred_tenant"
    ).filter(referred_tenant_id=tenant_id,status=ReferralReward.Status.PENDING)
    for reward in rewards:
        campaign=reward.campaign
        count=len(paid)
        reward.qualified_payment_count=count
        reward.save(update_fields=["qualified_payment_count","updated_at"])
        required=2
        if count<required:
            continue
        qualifying_payment=paid[min(required-1,len(paid)-1)]
        reward.reward_amount=_reward_amount(campaign,qualifying_payment.amount)
        reward.earned_at=timezone.now()
        reward.status=ReferralReward.Status.ELIGIBLE
        reward.save(update_fields=["reward_amount","earned_at","status","updated_at"])

        if reward.referrer_kind==ReferralReward.ReferrerKind.COMPANY:
            try:
                _apply_company_discount(reward)
            except Exception:
                # Keep it eligible so the Master can retry/inspect without losing the reward.
                continue
        else:
            reward.status=ReferralReward.Status.PIX_REQUIRED
            reward.pix_requested_at=timezone.now()
            reward.save(update_fields=["status","pix_requested_at","updated_at"])
            user=reward.referrer_user
            if user.email:
                from django.conf import settings
                base=settings.PUBLIC_BASE_URL.rstrip("/")
                queue_email(
                    user.tenant,user.email,"referral_pix_request",
                    {
                        "nome":user.first_name or user.email.split("@")[0],
                        "empresa_indicada":reward.referred_tenant.name,
                        "valor":f"{reward.reward_amount:.2f}",
                        "url_pix":base+"/app/profissional/indicacoes/",
                    },
                )
    return len(paid)


def finalize_company_referral_discounts(tenant_id):
    rewards=list(
        ReferralReward.objects.select_related("referrer_user","campaign").filter(
            referrer_kind=ReferralReward.ReferrerKind.COMPANY,
            status=ReferralReward.Status.APPLIED,
            referrer_user__tenant_id=tenant_id,
        )
    )
    if not rewards:
        return 0
    subscription=(
        Subscription.objects.filter(
            tenant_id=tenant_id,
            status__in=[Subscription.Status.TRIAL,Subscription.Status.ACTIVE,Subscription.Status.PAST_DUE],
        ).order_by("-started_at").first()
    )
    if not subscription:
        return 0
    restored=sum((row.reward_amount for row in rewards),Decimal("0.00")).quantize(Decimal("0.01"))
    new_total=(Decimal(subscription.contracted_price or 0)+restored).quantize(Decimal("0.01"))
    if subscription.provider_subscription_id:
        from billing.models import PaymentGateway
        gateway=PaymentGateway.objects.filter(
            provider="mercadopago",active=True,
            last_test_status=PaymentGateway.TestStatus.VALIDATED,
        )
        if subscription.provider_environment:
            gateway=gateway.filter(environment=subscription.provider_environment)
        gateway=gateway.first()
        if gateway:
            platform_provider(gateway).update_subscription_amount(
                subscription.provider_subscription_id,new_total
            )
    subscription.contracted_price=new_total
    if subscription.base_contracted_price is not None:
        subscription.base_contracted_price=(
            Decimal(subscription.base_contracted_price)+restored
        ).quantize(Decimal("0.01"))
    subscription.save(update_fields=["contracted_price","base_contracted_price","updated_at"])
    now=timezone.now()
    ReferralReward.objects.filter(pk__in=[row.pk for row in rewards]).update(
        status=ReferralReward.Status.PAID,paid_at=now,updated_at=now
    )
    return len(rewards)


@login_required
def referrals(request):
    user=request.user
    if not user.tenant_id:
        raise PermissionDenied
    campaign=active_referral_campaign()
    kind=(
        ReferralReward.ReferrerKind.PROFESSIONAL
        if user.role=="professional" else ReferralReward.ReferrerKind.COMPANY
    )
    company_roles={"owner","manager","tenant-admin","barber-manager","arena-manager","auto-manager"}
    allowed=bool(
        campaign and (
            (kind==ReferralReward.ReferrerKind.PROFESSIONAL and campaign.professional_referrals_enabled)
            or (kind==ReferralReward.ReferrerKind.COMPANY and user.role in company_roles and campaign.company_referrals_enabled)
        )
    )
    profile=ensure_referral_profile(user) if allowed else None
    rewards=ReferralReward.objects.filter(referrer_user=user).select_related(
        "campaign","referred_tenant"
    ).order_by("-created_at")

    if request.method=="POST":
        reward=get_object_or_404(
            rewards,pk=request.POST.get("reward"),status=ReferralReward.Status.PIX_REQUIRED
        )
        pix=(request.POST.get("pix_key") or "").strip()
        if len(pix)<3:
            messages.error(request,"Informe uma chave Pix válida.")
        else:
            reward.pix_key_encrypted=encrypt_text(pix)
            reward.pix_key_last4=pix[-4:]
            reward.pix_received_at=timezone.now()
            reward.status=ReferralReward.Status.READY
            reward.save(update_fields=[
                "pix_key_encrypted","pix_key_last4","pix_received_at","status","updated_at"
            ])
            messages.success(request,"Chave Pix enviada ao ApPlanner. A recompensa ficará disponível para conferência do Master.")
        return redirect("engagement-referrals")

    from django.conf import settings
    referral_url=(
        settings.PUBLIC_BASE_URL.rstrip("/")+"/indique/"+profile.referral_code+"/"
        if profile else ""
    )
    return render(request,"engagement/referrals.html",{
        "campaign":campaign,"profile":profile,"referral_url":referral_url,
        "rewards":rewards,"kind":kind,"allowed":allowed,
    })
