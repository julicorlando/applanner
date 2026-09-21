from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.crypto import decrypt_json, decrypt_text, encrypt_json, encrypt_text
from .mercadopago import MercadoPagoProvider
from .models import (
    PaymentGateway,
    Subscription,
    TenantPaymentConnection,
    TenantRecurringSubscription,
)


def configure_mercadopago_gateway(*,environment,public_key,access_token,webhook_secret,webhook_url):
    if environment not in {PaymentGateway.Environment.SANDBOX,PaymentGateway.Environment.PRODUCTION}:
        raise ValueError("Ambiente inválido.")
    if not webhook_url.startswith("https://"):
        raise ValueError("O webhook precisa usar HTTPS.")
    if environment==PaymentGateway.Environment.SANDBOX and not access_token.startswith("TEST-"):
        raise ValueError("Use credencial TEST- no ambiente sandbox.")
    if environment==PaymentGateway.Environment.PRODUCTION and access_token.startswith("TEST-"):
        raise ValueError("Credencial TEST- não pode ser usada em produção.")
    if len(webhook_secret)<16:
        raise ValueError("Segredo de webhook inválido.")

    identity=MercadoPagoProvider(access_token).test_connection()
    gateway,_=PaymentGateway.objects.update_or_create(
        provider="mercadopago",
        environment=environment,
        defaults={
            "public_key":public_key.strip(),
            "access_token_encrypted":encrypt_text(access_token),
            "webhook_secret_encrypted":encrypt_text(webhook_secret),
            "webhook_url":webhook_url,
            "active":True,
            "last_tested_at":timezone.now(),
            "last_test_status":PaymentGateway.TestStatus.VALIDATED,
        },
    )
    if environment==PaymentGateway.Environment.PRODUCTION:
        PaymentGateway.objects.filter(
            provider="mercadopago",
            environment=PaymentGateway.Environment.SANDBOX,
        ).update(active=False)
    return gateway,identity


def platform_provider(gateway):
    return MercadoPagoProvider(decrypt_text(gateway.access_token_encrypted))


def platform_webhook_secret(gateway):
    return decrypt_text(gateway.webhook_secret_encrypted)


def create_platform_subscription(*,subscription,payer_email,back_url,idempotency_key):
    gateway=PaymentGateway.objects.filter(
        provider="mercadopago",active=True,last_test_status=PaymentGateway.TestStatus.VALIDATED
    ).order_by("-environment").first()
    if not gateway:
        raise RuntimeError("Mercado Pago da plataforma não está configurado.")

    amount=subscription.contracted_price or subscription.plan.monthly_price
    if subscription.billing_cycle==Subscription.BillingCycle.QUARTERLY:
        amount=subscription.plan.quarterly_price or amount
    elif subscription.billing_cycle==Subscription.BillingCycle.SEMIANNUAL:
        amount=subscription.plan.semiannual_price or amount
    elif subscription.billing_cycle==Subscription.BillingCycle.ANNUAL:
        amount=subscription.plan.annual_price or amount

    frequency={
        Subscription.BillingCycle.MONTHLY:1,
        Subscription.BillingCycle.QUARTERLY:3,
        Subscription.BillingCycle.SEMIANNUAL:6,
        Subscription.BillingCycle.ANNUAL:12,
    }[subscription.billing_cycle]

    remote=platform_provider(gateway).create_subscription(
        reason=f"ApPlanner — {subscription.plan.name}",
        external_reference=f"subscription:{subscription.pk}",
        payer_email=payer_email,
        back_url=back_url,
        amount=Decimal(str(amount)),
        frequency=frequency,
        trial_days=subscription.trial_days_snapshot or 0,
        idempotency_key=idempotency_key,
    )
    subscription.provider_subscription_id=remote["reference"]
    subscription.provider_plan_id=""
    subscription.save(update_fields=["provider_subscription_id","provider_plan_id","updated_at"])
    return remote


@transaction.atomic
def configure_tenant_mercadopago(*,tenant,environment,access_token,webhook_secret,public_key,created_by=None):
    if environment not in {PaymentGateway.Environment.SANDBOX,PaymentGateway.Environment.PRODUCTION}:
        raise ValueError("Ambiente inválido.")
    if environment==PaymentGateway.Environment.SANDBOX and not access_token.startswith("TEST-"):
        raise ValueError("Use credencial TEST- no sandbox.")
    if environment==PaymentGateway.Environment.PRODUCTION and access_token.startswith("TEST-"):
        raise ValueError("Credencial TEST- não pode ser usada em produção.")
    if len(webhook_secret)<16:
        raise ValueError("Segredo de webhook inválido.")

    identity=MercadoPagoProvider(access_token).test_connection()
    connection,_=TenantPaymentConnection.objects.update_or_create(
        tenant=tenant,
        provider="mercadopago",
        environment=environment,
        defaults={
            "display_name":"Mercado Pago",
            "credentials_encrypted":encrypt_json({
                "access_token":access_token,
                "webhook_secret":webhook_secret,
            }),
            "metadata":{
                "user_id":identity.get("id"),
                "nickname":identity.get("nickname"),
                "public_key":public_key.strip(),
            },
            "status":TenantPaymentConnection.Status.CONNECTED,
            "last_tested_at":timezone.now(),
            "last_sync_at":timezone.now(),
            "last_error_code":"",
            "created_by":created_by,
        },
    )
    return connection,identity


def tenant_provider(connection):
    credentials=decrypt_json(connection.credentials_encrypted)
    return MercadoPagoProvider(credentials["access_token"])


def tenant_webhook_secret(connection):
    return decrypt_json(connection.credentials_encrypted)["webhook_secret"]


@transaction.atomic
def cancel_tenant_recurring_subscription(recurring):
    recurring=TenantRecurringSubscription.objects.select_for_update().select_related("connection").get(pk=recurring.pk)
    if recurring.status==TenantRecurringSubscription.Status.CANCELLED:
        return recurring
    if recurring.provider_subscription_id:
        tenant_provider(recurring.connection).cancel_subscription(recurring.provider_subscription_id)
    recurring.status=TenantRecurringSubscription.Status.CANCELLED
    recurring.save(update_fields=["status","updated_at"])
    return recurring
