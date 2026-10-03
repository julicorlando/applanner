import hashlib
import logging
import secrets
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    ModuleRequest, PaymentGateway, Subscription, SubscriptionModuleAdjustment,
    TenantModule, TenantModuleAddon,
)
from .payment_services import platform_provider

logger=logging.getLogger(__name__)


def _cycle_months(cycle):
    return {
        Subscription.BillingCycle.MONTHLY:1,
        Subscription.BillingCycle.QUARTERLY:3,
        Subscription.BillingCycle.SEMIANNUAL:6,
        Subscription.BillingCycle.ANNUAL:12,
    }.get(cycle,1)


def _subscription(tenant):
    return (
        Subscription.objects.filter(
            tenant=tenant,
            status__in=[
                Subscription.Status.TRIAL,Subscription.Status.ACTIVE,
                Subscription.Status.PAST_DUE,
            ],
        ).select_for_update().select_related("plan").order_by("-started_at").first()
    )


def _merged_monthly(tenant,exclude_addon_id=None):
    qs=TenantModuleAddon.objects.filter(
        tenant=tenant,status=TenantModuleAddon.Status.ACTIVE,
        billing_mode=TenantModuleAddon.BillingMode.MERGED,
    )
    if exclude_addon_id:
        qs=qs.exclude(pk=exclude_addon_id)
    return sum((row.monthly_price for row in qs),Decimal("0.00"))


def request_module(*,tenant,module,user,note=""):
    if not module.active or not module.addon_sellable or module.addon_monthly_price is None:
        raise ValidationError("Este módulo não está disponível para contratação avulsa.")
    from .entitlements import module_enabled
    if module_enabled(tenant,module.slug):
        raise ValidationError("Este módulo já está habilitado.")
    existing=ModuleRequest.objects.filter(
        tenant=tenant,module=module,
        status__in=[
            ModuleRequest.Status.PENDING,ModuleRequest.Status.APPROVED,
            ModuleRequest.Status.AWAITING_PAYMENT,ModuleRequest.Status.ACTIVE,
            ModuleRequest.Status.PAYMENT_FAILED,
        ],
    ).order_by("-created_at").first()
    if existing:
        return existing
    return ModuleRequest.objects.create(
        public_id=secrets.token_hex(16),tenant=tenant,module=module,requested_by=user,
        quoted_monthly_price=module.addon_monthly_price,
        tenant_note=(note or "")[:500],status=ModuleRequest.Status.PENDING,
    )


@transaction.atomic
def review_module_request(*,module_request,user,approved=True,note=""):
    row=ModuleRequest.objects.select_for_update().select_related("tenant","module").get(pk=module_request.pk)
    if row.status not in {ModuleRequest.Status.PENDING,ModuleRequest.Status.PAYMENT_FAILED}:
        raise ValidationError("Esta solicitação não está pendente de análise.")
    row.status=ModuleRequest.Status.APPROVED if approved else ModuleRequest.Status.REJECTED
    row.master_note=(note or "")[:500]
    row.reviewed_by=user
    row.reviewed_at=timezone.now()
    row.save(update_fields=["status","master_note","reviewed_by","reviewed_at","updated_at"])
    return row


def _gateway_for(subscription):
    if not subscription.provider_subscription_id:
        return None
    gateways=PaymentGateway.objects.filter(
        provider="mercadopago",last_test_status=PaymentGateway.TestStatus.VALIDATED,
    )
    if subscription.provider_environment:
        gateway=gateways.filter(environment=subscription.provider_environment).first()
    else:
        gateway=gateways.filter(active=True).order_by("-environment").first()
    if not gateway:
        raise ValidationError("A conexão Mercado Pago da assinatura não está disponível. Confira o ambiente e as credenciais.")
    return gateway


@transaction.atomic
def activate_module_request(*,module_request,user):
    row=ModuleRequest.objects.select_for_update().select_related("tenant","module").get(pk=module_request.pk)
    if row.status not in {ModuleRequest.Status.APPROVED,ModuleRequest.Status.PAYMENT_FAILED}:
        raise ValidationError("A solicitação precisa estar aprovada.")
    subscription=_subscription(row.tenant)
    if not subscription:
        raise ValidationError("A empresa não possui assinatura válida.")
    if TenantModuleAddon.objects.filter(tenant=row.tenant,module=row.module,
                                       status=TenantModuleAddon.Status.ACTIVE).exists():
        raise ValidationError("Este módulo adicional já está ativo para a empresa.")

    months=_cycle_months(subscription.billing_cycle)
    monthly_before=_merged_monthly(row.tenant)
    previous=Decimal(subscription.contracted_price or Decimal("0.00")).quantize(Decimal("0.01"))
    base=subscription.base_contracted_price
    if base is None:
        base=previous-monthly_before*months
    quantity=max(0,row.tenant.units.filter(active=True).count()-1) if row.module.slug=="multiunit" else 1
    module_monthly=(row.quoted_monthly_price*quantity).quantize(Decimal("0.01"))
    new_monthly=(monthly_before+module_monthly).quantize(Decimal("0.01"))
    new_total=(previous+module_monthly*months).quantize(Decimal("0.01"))
    key=hashlib.sha256(
        f"add|{row.tenant_id}|{subscription.pk}|{row.pk}|{new_total}".encode()
    ).hexdigest()
    adjustment,_=SubscriptionModuleAdjustment.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "public_id":secrets.token_hex(16),"tenant":row.tenant,
            "subscription":subscription,"module_request":row,"action":SubscriptionModuleAdjustment.Action.ADD,
            "previous_amount":previous,"new_amount":new_total,
            "addon_monthly_price":row.quoted_monthly_price,"created_by":user,
        },
    )
    if adjustment.status==SubscriptionModuleAdjustment.Status.APPLIED:
        return adjustment

    gateway=None
    provider_changed=False
    try:
        gateway=_gateway_for(subscription)
        if gateway:
            platform_provider(gateway).update_subscription_amount(
                subscription.provider_subscription_id,new_total
            )
            provider_changed=True
            adjustment.provider="mercadopago"
            adjustment.provider_reference=subscription.provider_subscription_id

        with transaction.atomic():
            addon,_=TenantModuleAddon.objects.update_or_create(
                tenant=row.tenant,module=row.module,
                defaults={
                    "module_request":row,"monthly_price":module_monthly,
                    "unit_price":row.quoted_monthly_price,"quantity":quantity,
                    "status":TenantModuleAddon.Status.ACTIVE,
                    "billing_mode":TenantModuleAddon.BillingMode.MERGED,
                    "provider":"mercadopago" if gateway else "",
                    "provider_reference":subscription.provider_subscription_id if gateway else "",
                    "started_at":timezone.now(),"next_billing_at":subscription.next_billing_at,
                    "cancelled_at":None,
                },
            )
            TenantModule.objects.update_or_create(
                tenant=row.tenant,module=row.module,defaults={"enabled":True}
            )
            row.status=ModuleRequest.Status.ACTIVE
            row.provider_reference=subscription.provider_subscription_id if gateway else ""
            row.save(update_fields=["status","provider_reference","updated_at"])
            subscription.base_contracted_price=base
            subscription.addon_contracted_price=(new_monthly*months).quantize(Decimal("0.01"))
            subscription.contracted_price=new_total
            subscription.save(update_fields=[
                "base_contracted_price","addon_contracted_price","contracted_price","updated_at"
            ])
            adjustment.module_addon=addon
            adjustment.status=SubscriptionModuleAdjustment.Status.APPLIED
            adjustment.applied_at=timezone.now()
            adjustment.error_code=""
            adjustment.save()
        return adjustment
    except Exception as exc:
        logger.exception("Falha ao ativar módulo adicional para assinatura %s",subscription.pk)
        if provider_changed and gateway:
            try:
                platform_provider(gateway).update_subscription_amount(
                    subscription.provider_subscription_id,previous
                )
            except Exception:
                adjustment.status=SubscriptionModuleAdjustment.Status.SYNC_REQUIRED
            else:
                adjustment.status=SubscriptionModuleAdjustment.Status.FAILED
        else:
            adjustment.status=SubscriptionModuleAdjustment.Status.FAILED
        adjustment.error_code=f"{exc.__class__.__name__}: {exc}"[:120]
        adjustment.save(update_fields=["status","error_code","updated_at"])
        row.status=ModuleRequest.Status.PAYMENT_FAILED
        row.save(update_fields=["status","updated_at"])
        return adjustment


@transaction.atomic
def sync_multiunit_addon(*,tenant,user=None):
    """Atualiza imediatamente a mensalidade do módulo Multiunidade conforme unidades adicionais ativas."""
    addon=(
        TenantModuleAddon.objects.select_for_update().select_related("module","tenant")
        .filter(tenant=tenant,module__slug="multiunit",status=TenantModuleAddon.Status.ACTIVE)
        .first()
    )
    if not addon:
        return None
    subscription=_subscription(tenant)
    if not subscription:
        raise ValidationError("Assinatura válida não encontrada para recalcular o Multiunidade.")

    quantity=max(0,tenant.units.filter(active=True).count()-1)
    unit_price=Decimal(addon.unit_price if addon.unit_price is not None else addon.module.addon_monthly_price or 0)
    new_monthly=(unit_price*quantity).quantize(Decimal("0.01"))
    old_monthly=Decimal(addon.monthly_price or 0).quantize(Decimal("0.01"))
    addon.unit_price=unit_price
    addon.quantity=quantity
    if new_monthly==old_monthly:
        addon.save(update_fields=["unit_price","quantity","updated_at"])
        return addon

    months=_cycle_months(subscription.billing_cycle)
    previous=Decimal(subscription.contracted_price or 0).quantize(Decimal("0.01"))
    new_total=(previous+(new_monthly-old_monthly)*months).quantize(Decimal("0.01"))
    gateway=_gateway_for(subscription)
    if gateway:
        platform_provider(gateway).update_subscription_amount(
            subscription.provider_subscription_id,new_total
        )

    addon.monthly_price=new_monthly
    addon.provider="mercadopago" if gateway else addon.provider
    addon.provider_reference=subscription.provider_subscription_id if gateway else addon.provider_reference
    addon.save(update_fields=[
        "unit_price","quantity","monthly_price","provider","provider_reference","updated_at",
    ])

    monthly_after=_merged_monthly(tenant)
    base=subscription.base_contracted_price
    if base is None:
        base=(previous-old_monthly*months).quantize(Decimal("0.01"))
    subscription.base_contracted_price=base
    subscription.addon_contracted_price=(monthly_after*months).quantize(Decimal("0.01"))
    subscription.contracted_price=new_total
    subscription.save(update_fields=[
        "base_contracted_price","addon_contracted_price","contracted_price","updated_at",
    ])
    return addon


@transaction.atomic
def cancel_module_addon(*,addon,user):
    addon=TenantModuleAddon.objects.select_for_update().select_related("tenant","module").get(pk=addon.pk)
    if addon.status!=TenantModuleAddon.Status.ACTIVE:
        raise ValidationError("Módulo adicional não está ativo.")
    subscription=_subscription(addon.tenant)
    if not subscription:
        raise ValidationError("Assinatura não encontrada.")
    months=_cycle_months(subscription.billing_cycle)
    monthly_before=_merged_monthly(addon.tenant)
    previous=Decimal(subscription.contracted_price or Decimal("0.00")).quantize(Decimal("0.01"))
    base=subscription.base_contracted_price
    if base is None:
        base=previous-monthly_before*months
    monthly_after=_merged_monthly(addon.tenant,exclude_addon_id=addon.pk)
    new_total=(previous-addon.monthly_price*months).quantize(Decimal("0.01"))
    key=hashlib.sha256(
        f"remove|{addon.tenant_id}|{subscription.pk}|{addon.pk}|{new_total}".encode()
    ).hexdigest()
    adjustment,_=SubscriptionModuleAdjustment.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "public_id":secrets.token_hex(16),"tenant":addon.tenant,
            "subscription":subscription,"module_addon":addon,
            "module_request":addon.module_request,
            "action":SubscriptionModuleAdjustment.Action.REMOVE,
            "previous_amount":previous,"new_amount":new_total,
            "addon_monthly_price":addon.monthly_price,"created_by":user,
        },
    )
    gateway=_gateway_for(subscription)
    provider_changed=False
    try:
        if gateway:
            platform_provider(gateway).update_subscription_amount(
                subscription.provider_subscription_id,new_total
            )
            provider_changed=True
            adjustment.provider="mercadopago"
            adjustment.provider_reference=subscription.provider_subscription_id

        addon.status=TenantModuleAddon.Status.CANCELLED
        addon.cancelled_at=timezone.now()
        addon.save(update_fields=["status","cancelled_at","updated_at"])
        TenantModule.objects.filter(tenant=addon.tenant,module=addon.module).delete()
        if addon.module_request_id:
            ModuleRequest.objects.filter(pk=addon.module_request_id).update(
                status=ModuleRequest.Status.CANCELLED,updated_at=timezone.now()
            )
        subscription.addon_contracted_price=(monthly_after*months).quantize(Decimal("0.01"))
        subscription.contracted_price=new_total
        subscription.base_contracted_price=base
        subscription.save(update_fields=[
            "base_contracted_price","addon_contracted_price","contracted_price","updated_at"
        ])
        adjustment.status=SubscriptionModuleAdjustment.Status.APPLIED
        adjustment.applied_at=timezone.now()
        adjustment.save()
        return adjustment
    except Exception as exc:
        if provider_changed and gateway:
            try:
                platform_provider(gateway).update_subscription_amount(
                    subscription.provider_subscription_id,previous
                )
            except Exception:
                adjustment.status=SubscriptionModuleAdjustment.Status.SYNC_REQUIRED
            else:
                adjustment.status=SubscriptionModuleAdjustment.Status.FAILED
        else:
            adjustment.status=SubscriptionModuleAdjustment.Status.FAILED
        adjustment.error_code=exc.__class__.__name__[:120]
        adjustment.save(update_fields=["status","error_code","updated_at"])
        raise
