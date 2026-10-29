"""Dental seats reuse the existing Payment/PixCharge and subscription ledger."""
from datetime import timedelta
from decimal import Decimal,ROUND_HALF_UP
from secrets import token_hex
from dateutil.relativedelta import relativedelta
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.utils import timezone
from .models import (ModuleRequest,Subscription,Payment,PixCharge,PaymentGateway,CheckoutSession)
from .payment_services import platform_provider


def quote_initial_charge(row):
    subscription=Subscription.objects.filter(tenant=row.tenant,status__in=["active","trial","past_due"]).order_by("-started_at").first()
    if not subscription:raise ValidationError("A clínica precisa de uma assinatura válida.")
    months={"monthly":1,"quarterly":3,"semiannual":6,"annual":12}[subscription.billing_cycle]
    full=row.quoted_monthly_price*row.quantity*months
    now=timezone.now();until=subscription.next_billing_at
    if until and until>now:
        start=until-relativedelta(months=months)
        ratio=min(Decimal(1),Decimal(str((until-now).total_seconds()))/Decimal(str((until-start).total_seconds())))
        amount=(full*ratio).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)
    else:amount=full
    # MP requires a positive charge. Near a renewal, charge the full new cycle;
    # otherwise a zero fee requires explicit Master waiver rather than silent activation.
    if amount<=0:raise ValidationError("O valor proporcional exige nova cotação ou isenção expressa do Master.")
    return amount,until if until and until>now else None


def owner_access(row,user):
    if not user.is_active or user.tenant_id!=row.tenant_id or user.role not in {"owner","tenant-admin"}:
        raise PermissionDenied("Somente o responsável desta clínica pode contratar vagas.")


@transaction.atomic
def checkout_seats(*,row,user):
    row=ModuleRequest.objects.select_for_update().select_related("tenant","module").get(pk=row.pk)
    owner_access(row,user)
    if row.module.slug!="dental-professional-extra" or row.status not in {"approved","awaiting_payment","payment_failed"}:
        raise ValidationError("A solicitação precisa de aprovação do Master.")
    existing=PixCharge.objects.filter(payment__purpose="dental-seat",payment__reference_id=row.pk,
        payment__tenant=row.tenant,payment__status="pending",expires_at__gt=timezone.now()).select_related("payment").first()
    if existing:return existing
    if not row.initial_charge_amount or not row.seat_quote_expires_at or row.seat_quote_expires_at<=timezone.now():
        raise ValidationError("Cotação expirada. Solicite nova análise ao Master antes de pagar.")
    subscription=Subscription.objects.select_for_update().filter(tenant=row.tenant,status__in=["active","trial","past_due"]).order_by("-started_at").first()
    if not subscription:raise ValidationError("Assinatura indisponível.")
    gateways=PaymentGateway.objects.filter(provider="mercadopago",active=True,last_test_status="validated")
    if subscription.provider_environment:gateways=PaymentGateway.objects.filter(provider="mercadopago",environment=subscription.provider_environment,last_test_status="validated")
    gateway=gateways.first()
    if not gateway:raise ValidationError("Configure o Mercado Pago do ambiente da assinatura.")
    public=token_hex(16);reference="dental-seat-"+row.public_id
    expiry=min(timezone.now()+timedelta(hours=24),row.seat_quote_expires_at)
    session=CheckoutSession.objects.create(public_id=public,tenant=row.tenant,plan=subscription.plan,
        billing_cycle=subscription.billing_cycle,subtotal=row.initial_charge_amount,total=row.initial_charge_amount,
        status="awaiting_payment",idempotency_key=reference,expires_at=expiry)
    payment,created=Payment.objects.get_or_create(tenant=row.tenant,idempotency_key=reference,
        defaults={"subscription":subscription,"purpose":"dental-seat","reference_id":row.pk,
                  "provider":"mercadopago","environment":gateway.environment,"provider_reference":reference,
                  "amount":row.initial_charge_amount,"due_at":expiry,"metadata":{"method":"pix","quantity":row.quantity,
                  "unit_monthly":str(row.quoted_monthly_price),"proration_until":row.proration_until.isoformat() if row.proration_until else None}})
    if not created and (payment.status!="pending" or payment.amount!=row.initial_charge_amount):
        raise ValidationError("Esta cobrança já foi processada. Consulte o histórico da solicitação.")
    remote=platform_provider(gateway).create_pix_order(amount=payment.amount,external_reference=reference,
        payer_email=user.email,expiration_hours=max(1,min(24,int((expiry-timezone.now()).total_seconds()/3600))),idempotency_key=reference)
    if not remote.get("order_id") or not (remote.get("qr_code") or remote.get("qr_code_base64")):
        raise ValidationError("O provedor não retornou uma cobrança Pix válida.")
    payment.provider_status=remote.get("status") or "pending";payment.provider_payment_id=remote.get("payment_id") or ""
    payment.save(update_fields=["provider_status","provider_payment_id","updated_at"])
    row.status="awaiting_payment";row.save(update_fields=["status","updated_at"])
    return PixCharge.objects.create(public_id=public,tenant=row.tenant,subscription=subscription,checkout_session=session,
        payment=payment,provider_order_id=remote["order_id"],provider_payment_id=remote.get("payment_id") or "",
        amount=payment.amount,qr_code=remote.get("qr_code") or "",qr_code_base64=remote.get("qr_code_base64") or "",
        ticket_url=remote.get("ticket_url") if str(remote.get("ticket_url","")).startswith("https://") else "",
        expires_at=expiry,status="pending")


def finalize_seats(payment_id):
    payment=Payment.objects.select_related("tenant").get(pk=payment_id)
    if payment.purpose!="dental-seat" or payment.status!="paid":return False
    row=ModuleRequest.objects.select_related("reviewed_by").get(pk=payment.reference_id,tenant=payment.tenant)
    if row.status=="active":return True
    if not row.reviewed_by_id or not row.reviewed_by.is_superuser or not row.reviewed_by.is_active:return False
    from .module_services import activate_module_request
    adjustment=activate_module_request(module_request=row,user=row.reviewed_by,financial_payment=payment)
    return adjustment.status=="applied"


@transaction.atomic
def reconcile_dental_refund(payment_id):
    from hashlib import sha256
    from .models import TenantModuleAddon,SubscriptionModuleAdjustment
    from .module_services import _gateway_for,_cycle_months,invalidate_pending_subscription_charges
    from core.audit import append_audit
    payment=Payment.objects.select_related("tenant").get(pk=payment_id,purpose="dental-seat")
    if payment.status not in {"refunded","partially_refunded"}:return False
    row=ModuleRequest.objects.select_for_update().get(pk=payment.reference_id,tenant=payment.tenant)
    if row.status=="cancelled":return True
    if payment.status=="partially_refunded" and row.status=="active":
        addon=TenantModuleAddon.objects.select_for_update().get(tenant=row.tenant,module=row.module)
        addon.status="past_due";addon.save(update_fields=["status","updated_at"])
        if not (payment.metadata or {}).get("dental_partial_refund_review"):
            payment.metadata={**(payment.metadata or {}),"dental_partial_refund_review":True};payment.save(update_fields=["metadata","updated_at"])
            append_audit(tenant=row.tenant,user=row.reviewed_by,action="dental.partial_refund.review_required",entity_type="ModuleRequest",entity_id=row.pk,after={"payment_id":payment.pk})
        return False
    if row.status!="active":
        row.status="cancelled";row.save(update_fields=["status","updated_at"]);return True
    addon=TenantModuleAddon.objects.select_for_update().get(tenant=row.tenant,module=row.module)
    subscription=Subscription.objects.select_for_update().filter(tenant=row.tenant,status__in=["active","past_due","trial"]).order_by("-started_at").first()
    if not subscription:return False
    reduction=row.quoted_monthly_price*row.quantity
    previous=subscription.contracted_price
    new=previous-reduction*_cycle_months(subscription.billing_cycle)
    adjustment,_=SubscriptionModuleAdjustment.objects.get_or_create(idempotency_key=sha256(f"dental-refund|{payment.pk}".encode()).hexdigest(),
        defaults={"public_id":token_hex(16),"tenant":row.tenant,"subscription":subscription,"module_request":row,
                  "module_addon":addon,"action":"remove","previous_amount":previous,"new_amount":new,
                  "addon_monthly_price":reduction,"created_by":row.reviewed_by})
    try:
        if addon.quantity<row.quantity or addon.monthly_price<reduction or new<0:raise ValidationError("Capacidade financeira exige revisão manual.")
        gateway=_gateway_for(subscription)
        if gateway:platform_provider(gateway).update_subscription_amount(subscription.provider_subscription_id,new)
    except Exception as exc:
        addon.status="past_due";addon.save(update_fields=["status","updated_at"])
        adjustment.status="sync_required";adjustment.error_code=type(exc).__name__;adjustment.save(update_fields=["status","error_code","updated_at"])
        return False
    components=list(addon.pricing_components or [])
    for _ in range(row.quantity):
        match=next((i for i,v in enumerate(components) if Decimal(v)==row.quoted_monthly_price),None)
        if match is not None:components.pop(match)
    addon.quantity=max(0,addon.quantity-row.quantity);addon.monthly_price-=reduction;addon.pricing_components=components
    addon.status="active" if addon.quantity else "cancelled";addon.save(update_fields=["quantity","monthly_price","pricing_components","status","updated_at"])
    subscription.contracted_price=new
    subscription.addon_contracted_price=max(Decimal(0),subscription.addon_contracted_price-reduction*_cycle_months(subscription.billing_cycle))
    subscription.save(update_fields=["contracted_price","addon_contracted_price","updated_at"])
    invalidate_pending_subscription_charges(subscription)
    row.status="cancelled";row.save(update_fields=["status","updated_at"])
    adjustment.status="applied";adjustment.applied_at=timezone.now();adjustment.error_code="";adjustment.save(update_fields=["status","applied_at","error_code","updated_at"])
    append_audit(tenant=row.tenant,user=row.reviewed_by,action="dental.seat.refund.reconciled",entity_type="ModuleRequest",entity_id=row.pk,
        after={"payment_id":payment.pk,"quantity_removed":row.quantity,"new_subscription_amount":str(new),"legacy_professionals_preserved":True})
    return True
