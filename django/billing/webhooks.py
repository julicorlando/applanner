import hashlib
import json
from decimal import Decimal

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from tenants.models import Tenant
from .mercadopago import MercadoPagoProvider
from .models import (
    Payment,
    PaymentGateway,
    Subscription,
    TenantPaymentConnection,
    TenantPaymentTransaction,
    TenantPaymentWebhookEvent,
    TenantRecurringSubscription,
    WebhookEvent,
)
from .payment_services import (
    platform_provider,
    platform_webhook_secret,
    tenant_provider,
    tenant_webhook_secret,
)


def _payment_status(value):
    return {
        "approved":Payment.Status.PAID,
        "authorized":Payment.Status.PAID,
        "pending":Payment.Status.PENDING,
        "in_process":Payment.Status.PENDING,
        "rejected":Payment.Status.FAILED,
        "cancelled":Payment.Status.CANCELLED,
        "refunded":Payment.Status.REFUNDED,
        "charged_back":Payment.Status.REFUNDED,
    }.get(str(value or "").lower(),Payment.Status.PENDING)


def _tenant_status(value):
    return {
        "approved":TenantPaymentTransaction.Status.PAID,
        "authorized":TenantPaymentTransaction.Status.PAID,
        "processed":TenantPaymentTransaction.Status.PAID,
        "pending":TenantPaymentTransaction.Status.PENDING,
        "in_process":TenantPaymentTransaction.Status.PENDING,
        "rejected":TenantPaymentTransaction.Status.FAILED,
        "cancelled":TenantPaymentTransaction.Status.CANCELLED,
        "refunded":TenantPaymentTransaction.Status.REFUNDED,
        "charged_back":TenantPaymentTransaction.Status.REFUNDED,
    }.get(str(value or "").lower(),TenantPaymentTransaction.Status.PENDING)


def _subscription_status(value):
    return {
        "authorized":Subscription.Status.ACTIVE,
        "pending":Subscription.Status.TRIAL,
        "paused":Subscription.Status.SUSPENDED,
        "cancelled":Subscription.Status.CANCELLED,
    }.get(str(value or "").lower(),Subscription.Status.PAST_DUE)


def _recurring_status(value):
    return {
        "authorized":TenantRecurringSubscription.Status.AUTHORIZED,
        "pending":TenantRecurringSubscription.Status.PENDING,
        "paused":TenantRecurringSubscription.Status.PAUSED,
        "cancelled":TenantRecurringSubscription.Status.CANCELLED,
    }.get(str(value or "").lower(),TenantRecurringSubscription.Status.ERROR)


def _payload(request):
    try:
        data=json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError,json.JSONDecodeError):
        data={}
    return data if isinstance(data,dict) else {}


def _resource_id(request,data):
    return str(
        request.GET.get("data.id")
        or request.GET.get("data_id")
        or (data.get("data") or {}).get("id")
        or ""
    )


def _event_key(request,data,resource_id):
    raw=str(data.get("id") or request.headers.get("X-Request-Id") or "")
    kind=str(data.get("type") or data.get("action") or "event")
    return f"{kind}:{raw or resource_id}"[:190]


@transaction.atomic
def _record_event(*,event_key,resource_type,resource_id,valid,payload,raw_body):
    digest=hashlib.sha256(raw_body).hexdigest()
    event,created=WebhookEvent.objects.get_or_create(
        provider="mercadopago",
        event_id=event_key,
        defaults={
            "resource_type":resource_type[:60],
            "resource_id":resource_id[:190],
            "signature_valid":valid,
            "payload_hash":digest,
            "payload":payload,
            "status":WebhookEvent.Status.RECEIVED if valid else WebhookEvent.Status.REJECTED,
        },
    )
    return event,created


def _verify(provider_secret,request,resource_id):
    return MercadoPagoProvider.valid_webhook_signature(
        request.headers.get("X-Signature",""),
        request.headers.get("X-Request-Id",""),
        resource_id,
        provider_secret,
    )


def _reconcile_platform(event,gateway,data,resource_id):
    provider=platform_provider(gateway)
    kind=str(data.get("type") or "")
    action=str(data.get("action") or "")

    if kind=="payment" or action.startswith("payment."):
        remote=provider.get_payment(resource_id)
        external=str(remote.get("external_reference") or "")
        payment=Payment.objects.filter(
            provider="mercadopago",provider_payment_id=resource_id
        ).first()
        if payment is None and external:
            payment=Payment.objects.filter(
                provider="mercadopago",provider_reference=external
            ).order_by("-id").first()
        if payment:
            payment.provider_payment_id=resource_id
            payment.provider_status=str(remote.get("status") or "")
            payment.status=_payment_status(payment.provider_status)
            if remote.get("transaction_amount") is not None:
                payment.amount=Decimal(str(remote["transaction_amount"]))
            if payment.status==Payment.Status.PAID:
                payment.paid_at=payment.paid_at or timezone.now()
                if payment.subscription_id:
                    Subscription.objects.filter(pk=payment.subscription_id).update(
                        status=Subscription.Status.ACTIVE,
                        updated_at=timezone.now(),
                    )
            payment.metadata={**payment.metadata,"mercadopago":remote}
            payment.save()

    elif "preapproval" in kind or "preapproval" in action or "subscription" in kind:
        remote=provider.get_subscription(resource_id)
        subscription=Subscription.objects.filter(
            provider_subscription_id=resource_id
        ).first()
        if subscription:
            subscription.status=_subscription_status(remote.get("status"))
            subscription.save(update_fields=["status","updated_at"])

    event.status=WebhookEvent.Status.PROCESSED
    event.processed_at=timezone.now()
    event.error_message=""
    event.save(update_fields=["status","processed_at","error_message"])


@csrf_exempt
def mercadopago_platform_webhook(request):
    if request.method!="POST":
        return JsonResponse({"detail":"Method not allowed"},status=405)

    data=_payload(request)
    resource_id=_resource_id(request,data)
    live_mode=bool(data.get("live_mode"))
    environment=PaymentGateway.Environment.PRODUCTION if live_mode else PaymentGateway.Environment.SANDBOX
    gateway=PaymentGateway.objects.filter(
        provider="mercadopago",environment=environment,active=True
    ).first()
    if not gateway or not resource_id:
        return JsonResponse({"detail":"Webhook não configurado."},status=404)

    valid=_verify(platform_webhook_secret(gateway),request,resource_id)
    event_key=_event_key(request,data,resource_id)
    event,created=_record_event(
        event_key=event_key,
        resource_type=str(data.get("type") or data.get("action") or ""),
        resource_id=resource_id,
        valid=valid,
        payload=data,
        raw_body=request.body,
    )
    if not valid:
        return JsonResponse({"detail":"Assinatura inválida."},status=401)
    if not created and event.status==WebhookEvent.Status.PROCESSED:
        return JsonResponse({"ok":True,"duplicate":True})

    try:
        _reconcile_platform(event,gateway,data,resource_id)
    except Exception as exc:
        event.status=WebhookEvent.Status.FAILED
        event.error_message=str(exc)[:500]
        event.save(update_fields=["status","error_message"])
        return JsonResponse({"detail":"Falha temporária."},status=500)
    return JsonResponse({"ok":True})


@csrf_exempt
def mercadopago_tenant_webhook(request,slug):
    if request.method!="POST":
        return JsonResponse({"detail":"Method not allowed"},status=405)
    tenant=Tenant.objects.filter(public_slug=slug).first()
    if not tenant:
        return JsonResponse({"detail":"Tenant não encontrado."},status=404)

    data=_payload(request)
    resource_id=_resource_id(request,data)
    environment=PaymentGateway.Environment.PRODUCTION if bool(data.get("live_mode")) else PaymentGateway.Environment.SANDBOX
    connection=TenantPaymentConnection.objects.filter(
        tenant=tenant,
        provider="mercadopago",
        environment=environment,
        status=TenantPaymentConnection.Status.CONNECTED,
    ).first()
    if not connection or not resource_id:
        return JsonResponse({"detail":"Integração não encontrada."},status=404)

    event_key=_event_key(request,data,resource_id)
    payload_hash=hashlib.sha256(request.body).hexdigest()
    valid=_verify(tenant_webhook_secret(connection),request,resource_id)
    event,created=TenantPaymentWebhookEvent.objects.get_or_create(
        connection=connection,
        event_id=event_key,
        defaults={
            "tenant":tenant,
            "provider":"mercadopago",
            "payload_hash":payload_hash,
            "signature_valid":valid,
            "status":(
                TenantPaymentWebhookEvent.Status.RECEIVED
                if valid else TenantPaymentWebhookEvent.Status.FAILED
            ),
            "error_code":"" if valid else "invalid_signature",
        },
    )
    if not valid:
        return JsonResponse({"detail":"Assinatura inválida."},status=401)
    if not created and event.status==TenantPaymentWebhookEvent.Status.PROCESSED:
        return JsonResponse({"ok":True,"duplicate":True})

    provider=tenant_provider(connection)
    kind=str(data.get("type") or "")
    action=str(data.get("action") or "")

    try:
        if kind=="payment" or action.startswith("payment."):
            remote=provider.get_payment(resource_id)
            external=str(remote.get("external_reference") or "")
            tx=TenantPaymentTransaction.objects.filter(
                tenant=tenant,connection=connection,provider_transaction_id=resource_id
            ).first()
            if tx is None and external:
                tx=TenantPaymentTransaction.objects.filter(
                    tenant=tenant,connection=connection,external_reference=external
                ).first()
            if tx:
                tx.provider_transaction_id=resource_id
                tx.status=_tenant_status(remote.get("status"))
                fee=sum(
                    Decimal(str(item.get("amount") or 0))
                    for item in remote.get("fee_details",[])
                    if isinstance(item,dict)
                )
                tx.fee_amount=fee
                tx.net_amount=Decimal(str(
                    (remote.get("transaction_details") or {}).get("net_received_amount")
                    or (tx.gross_amount-fee)
                ))
                if tx.status==TenantPaymentTransaction.Status.PAID:
                    tx.paid_at=tx.paid_at or timezone.now()
                    tx.reconciled_at=tx.reconciled_at or timezone.now()
                tx.save(update_fields=[
                    "provider_transaction_id","status","fee_amount","net_amount",
                    "paid_at","reconciled_at","updated_at",
                ])
            else:
                event.status=TenantPaymentWebhookEvent.Status.IGNORED
                event.error_code="transaction_not_found"
        elif "preapproval" in kind or "preapproval" in action or "subscription" in kind:
            remote=provider.get_subscription(resource_id)
            recurring=TenantRecurringSubscription.objects.filter(
                tenant=tenant,connection=connection,provider_subscription_id=resource_id
            ).first()
            if recurring:
                recurring.status=_recurring_status(remote.get("status"))
                recurring.save(update_fields=["status","updated_at"])
            else:
                event.status=TenantPaymentWebhookEvent.Status.IGNORED
                event.error_code="subscription_not_found"
        else:
            event.status=TenantPaymentWebhookEvent.Status.IGNORED
            event.error_code="unsupported_event"

        connection.last_sync_at=timezone.now()
        connection.last_error_code=""
        connection.save(update_fields=["last_sync_at","last_error_code","updated_at"])

        if event.status==TenantPaymentWebhookEvent.Status.RECEIVED:
            event.status=TenantPaymentWebhookEvent.Status.PROCESSED
        event.processed_at=timezone.now()
        event.save(update_fields=["status","processed_at","error_code"])
    except Exception as exc:
        event.status=TenantPaymentWebhookEvent.Status.FAILED
        event.error_code=exc.__class__.__name__[:80]
        event.processed_at=timezone.now()
        event.save(update_fields=["status","error_code","processed_at"])
        connection.last_error_code=event.error_code
        connection.save(update_fields=["last_error_code","updated_at"])
        return JsonResponse({"detail":"Falha temporária."},status=500)

    return JsonResponse({"ok":True})
