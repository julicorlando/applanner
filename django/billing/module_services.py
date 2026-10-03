import hashlib
import logging
import secrets
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    CheckoutSession, ModuleRequest, Payment, PaymentGateway, PixCharge, Subscription,
    SubscriptionModuleAdjustment, TenantModule, TenantModuleAddon,
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


def module_monthly_price(module,tenant):
    base=Decimal(module.addon_monthly_price or Decimal("0.00")).quantize(Decimal("0.01"))
    if module.per_unit_billing:
        units=max(tenant.units.filter(active=True).count(),1)
        return (base*units).quantize(Decimal("0.01"))
    return base


def invalidate_pending_subscription_charges(subscription):
    pending=Payment.objects.filter(
        subscription=subscription,purpose="subscription",status=Payment.Status.PENDING,
    )
    payment_ids=list(pending.values_list("pk",flat=True))
    if payment_ids:
        PixCharge.objects.filter(payment_id__in=payment_ids,status="pending").update(
            status="cancelled",updated_at=timezone.now()
        )
        CheckoutSession.objects.filter(
            pix_charges__payment_id__in=payment_ids,
            status__in=[CheckoutSession.Status.STARTED,CheckoutSession.Status.AWAITING_PAYMENT],
        ).update(status=CheckoutSession.Status.ABANDONED,updated_at=timezone.now())
        pending.update(
            status=Payment.Status.CANCELLED,
            provider_status="superseded_by_subscription_amount_change",
            updated_at=timezone.now(),
        )


def request_module(*,tenant,module,user,note=""):
    if not module.active or not module.addon_sellable or module.addon_monthly_price is None:
        raise ValidationError("Este módulo não está disponível para contratação avulsa.")
    from .entitlements import module_enabled
    repeatable=module.slug=="professional-extra"
    if not repeatable and module_enabled(tenant,module.slug):
        raise ValidationError("Este módulo já está habilitado.")
    pending_statuses=[
        ModuleRequest.Status.PENDING,ModuleRequest.Status.APPROVED,
        ModuleRequest.Status.AWAITING_PAYMENT,ModuleRequest.Status.PAYMENT_FAILED,
    ]
    if not repeatable:
        pending_statuses.append(ModuleRequest.Status.ACTIVE)
    existing=ModuleRequest.objects.filter(
        tenant=tenant,module=module,status__in=pending_statuses,
    ).order_by("-created_at").first()
    if existing:
        return existing
    return ModuleRequest.objects.create(
        public_id=secrets.token_hex(16),tenant=tenant,module=module,requested_by=user,
        quoted_monthly_price=module_monthly_price(module,tenant),
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
        raise ValidationError("A conexão provedor de cobrança da assinatura não está disponível. Confira o ambiente e as credenciais.")
    return gateway


@transaction.atomic
def activate_module_request(*,module_request,user):
    row=ModuleRequest.objects.select_for_update().select_related("tenant","module").get(pk=module_request.pk)
    if row.status not in {ModuleRequest.Status.APPROVED,ModuleRequest.Status.PAYMENT_FAILED}:
        raise ValidationError("A solicitação precisa estar aprovada.")
    subscription=_subscription(row.tenant)
    if not subscription:
        raise ValidationError("A empresa não possui assinatura válida.")

    repeatable=row.module.slug=="professional-extra"
    existing_addon=TenantModuleAddon.objects.select_for_update().filter(
        tenant=row.tenant,module=row.module,status=TenantModuleAddon.Status.ACTIVE
    ).first()
    if existing_addon and not repeatable:
        raise ValidationError("Este módulo adicional já está ativo para a empresa.")

    quoted=Decimal(row.quoted_monthly_price or Decimal("0.00")).quantize(Decimal("0.01"))
    if repeatable:
        quoted=Decimal(row.module.addon_monthly_price or Decimal("0.00")).quantize(Decimal("0.01"))
        if quoted<=0:
            raise ValidationError(
                "Defina no Master o valor mensal de '+1 profissional extra' antes de aprovar."
            )
        if row.quoted_monthly_price!=quoted:
            row.quoted_monthly_price=quoted
            row.save(update_fields=["quoted_monthly_price","updated_at"])

    months=_cycle_months(subscription.billing_cycle)
    monthly_before=_merged_monthly(row.tenant)
    previous=Decimal(subscription.contracted_price or Decimal("0.00")).quantize(Decimal("0.01"))
    base=subscription.base_contracted_price
    if base is None:
        base=previous-monthly_before*months
    new_monthly=(monthly_before+quoted).quantize(Decimal("0.01"))
    new_total=(previous+quoted*months).quantize(Decimal("0.01"))
    key=hashlib.sha256(
        f"add|{row.tenant_id}|{subscription.pk}|{row.pk}|{new_total}".encode()
    ).hexdigest()
    adjustment,_=SubscriptionModuleAdjustment.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "public_id":secrets.token_hex(16),"tenant":row.tenant,
            "subscription":subscription,"module_request":row,"action":SubscriptionModuleAdjustment.Action.ADD,
            "previous_amount":previous,"new_amount":new_total,
            "addon_monthly_price":quoted,"created_by":user,
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
            if repeatable and existing_addon:
                components=list(existing_addon.pricing_components or [])
                components.append(str(quoted))
                existing_addon.quantity=max(int(existing_addon.quantity or 1),1)+1
                existing_addon.pricing_components=components
                existing_addon.monthly_price=(
                    Decimal(existing_addon.monthly_price or 0)+quoted
                ).quantize(Decimal("0.01"))
                existing_addon.module_request=row
                existing_addon.provider="mercadopago" if gateway else ""
                existing_addon.provider_reference=subscription.provider_subscription_id if gateway else ""
                existing_addon.next_billing_at=subscription.next_billing_at
                existing_addon.save(update_fields=[
                    "quantity","pricing_components","monthly_price","module_request","provider",
                    "provider_reference","next_billing_at","updated_at",
                ])
                addon=existing_addon
            else:
                addon,_=TenantModuleAddon.objects.update_or_create(
                    tenant=row.tenant,module=row.module,
                    defaults={
                        "module_request":row,"monthly_price":quoted,
                        "quantity":1,
                        "pricing_components":[str(quoted)] if repeatable else [],
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
            invalidate_pending_subscription_charges(subscription)
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

    repeatable=addon.module.slug=="professional-extra"
    if repeatable:
        quantity=max(int(addon.quantity or 1),1)
        components=[Decimal(str(value)).quantize(Decimal("0.01")) for value in (addon.pricing_components or [])]
        removal_price=components[-1] if components else (
            Decimal(addon.monthly_price or 0)/Decimal(quantity)
        ).quantize(Decimal("0.01"))
        remaining_price=(Decimal(addon.monthly_price or 0)-removal_price).quantize(Decimal("0.01"))
        monthly_after=(monthly_before-removal_price).quantize(Decimal("0.01"))
    else:
        removal_price=Decimal(addon.monthly_price or 0).quantize(Decimal("0.01"))
        remaining_price=Decimal("0.00")
        monthly_after=_merged_monthly(addon.tenant,exclude_addon_id=addon.pk)

    new_total=(previous-removal_price*months).quantize(Decimal("0.01"))
    key=hashlib.sha256(
        f"remove|{addon.tenant_id}|{subscription.pk}|{addon.pk}|{addon.quantity}|{new_total}".encode()
    ).hexdigest()
    adjustment,_=SubscriptionModuleAdjustment.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "public_id":secrets.token_hex(16),"tenant":addon.tenant,
            "subscription":subscription,"module_addon":addon,
            "module_request":addon.module_request,
            "action":SubscriptionModuleAdjustment.Action.REMOVE,
            "previous_amount":previous,"new_amount":new_total,
            "addon_monthly_price":removal_price,"created_by":user,
        },
    )
    if adjustment.status==SubscriptionModuleAdjustment.Status.APPLIED:
        return adjustment

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

        if repeatable and addon.module_request_id:
            ModuleRequest.objects.filter(
                pk=addon.module_request_id,status=ModuleRequest.Status.ACTIVE
            ).update(status=ModuleRequest.Status.CANCELLED,updated_at=timezone.now())

        if repeatable and addon.quantity>1:
            components=list(addon.pricing_components or [])
            if components:
                components.pop()
            addon.quantity-=1
            addon.pricing_components=components
            addon.monthly_price=remaining_price
            replacement_request=ModuleRequest.objects.filter(
                tenant=addon.tenant,module=addon.module,status=ModuleRequest.Status.ACTIVE
            ).order_by("-created_at").first()
            addon.module_request=replacement_request
            addon.save(update_fields=[
                "quantity","pricing_components","monthly_price","module_request","updated_at"
            ])
        else:
            addon.status=TenantModuleAddon.Status.CANCELLED
            addon.cancelled_at=timezone.now()
            addon.quantity=0 if repeatable else addon.quantity
            addon.pricing_components=[] if repeatable else addon.pricing_components
            addon.monthly_price=remaining_price if repeatable else addon.monthly_price
            addon.save(update_fields=[
                "status","cancelled_at","quantity","pricing_components","monthly_price","updated_at"
            ])
            TenantModule.objects.filter(tenant=addon.tenant,module=addon.module).delete()
            if not repeatable and addon.module_request_id:
                ModuleRequest.objects.filter(
                    pk=addon.module_request_id,status=ModuleRequest.Status.ACTIVE
                ).update(status=ModuleRequest.Status.CANCELLED,updated_at=timezone.now())

        subscription.addon_contracted_price=(monthly_after*months).quantize(Decimal("0.01"))
        subscription.contracted_price=new_total
        subscription.base_contracted_price=base
        subscription.save(update_fields=[
            "base_contracted_price","addon_contracted_price","contracted_price","updated_at"
        ])
        invalidate_pending_subscription_charges(subscription)
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



@transaction.atomic
def sync_per_unit_addon_pricing(tenant_id):
    from tenants.models import Tenant
    tenant=Tenant.objects.select_for_update().get(pk=tenant_id)
    subscription=_subscription(tenant)
    if not subscription:
        return None
    addons=list(
        TenantModuleAddon.objects.select_for_update().select_related("module").filter(
            tenant=tenant,status=TenantModuleAddon.Status.ACTIVE,
            billing_mode=TenantModuleAddon.BillingMode.MERGED,
            module__per_unit_billing=True,
        )
    )
    if not addons:
        return subscription

    months=_cycle_months(subscription.billing_cycle)
    previous=Decimal(subscription.contracted_price or Decimal("0.00")).quantize(Decimal("0.01"))
    delta_monthly=Decimal("0.00")
    changed=[]
    for addon in addons:
        target=module_monthly_price(addon.module,tenant)
        current=Decimal(addon.monthly_price or Decimal("0.00")).quantize(Decimal("0.01"))
        if target!=current:
            delta_monthly+=target-current
            changed.append((addon,target))
    if not changed:
        return subscription

    new_total=(previous+delta_monthly*months).quantize(Decimal("0.01"))
    gateway=_gateway_for(subscription)
    if gateway:
        platform_provider(gateway).update_subscription_amount(
            subscription.provider_subscription_id,new_total
        )
    for addon,target in changed:
        addon.monthly_price=target
        addon.save(update_fields=["monthly_price","updated_at"])
        if addon.module_request_id:
            ModuleRequest.objects.filter(pk=addon.module_request_id).update(
                quoted_monthly_price=target,updated_at=timezone.now()
            )
    subscription.addon_contracted_price=(
        Decimal(subscription.addon_contracted_price or Decimal("0.00"))+
        delta_monthly*months
    ).quantize(Decimal("0.01"))
    subscription.contracted_price=new_total
    subscription.save(update_fields=["addon_contracted_price","contracted_price","updated_at"])
    invalidate_pending_subscription_charges(subscription)
    return subscription
