from decimal import Decimal
from datetime import timedelta
from secrets import token_hex

from django.db import transaction
from django.utils import timezone

from core.crypto import decrypt_json, decrypt_text, encrypt_json, encrypt_text
from .mercadopago import MercadoPagoProvider
from .models import (
    PaymentGateway,
    CheckoutSession,
    Payment,
    PixCharge,
    Subscription,
    TenantPaymentConnection,
    TenantRecurringSubscription,
)


def configure_mercadopago_gateway(*,environment,public_key,access_token,webhook_secret,webhook_url):
    if environment not in {PaymentGateway.Environment.SANDBOX,PaymentGateway.Environment.PRODUCTION}:
        raise ValueError("Ambiente inválido.")
    if not webhook_url.startswith("https://"):
        raise ValueError("O webhook precisa usar HTTPS.")
    if environment==PaymentGateway.Environment.SANDBOX and not access_token.startswith(("TEST-","APP_USR-")):
        raise ValueError("Use uma credencial de teste válida no ambiente de testes.")
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
    PaymentGateway.objects.filter(provider="mercadopago").exclude(pk=gateway.pk).update(active=False)
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
        raise RuntimeError("provedor de cobrança da plataforma não está configurado.")

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
    subscription.provider_environment=gateway.environment
    subscription.provider_plan_id=""
    checkout_url=remote.get("init_point") or ""
    subscription.provider_checkout_url=checkout_url if checkout_url.startswith("https://") else ""
    subscription.save(update_fields=["provider_subscription_id","provider_environment","provider_plan_id","provider_checkout_url","updated_at"])
    return remote


@transaction.atomic
def create_platform_pix_charge(*,subscription,payer_email):
    """One-off Pix for the current billing cycle; never authorizes recurring charges."""
    subscription=Subscription.objects.select_for_update().select_related("plan","tenant").get(pk=subscription.pk)
    from .access import eligible_for_payment
    if not eligible_for_payment(subscription):
        raise ValueError("Não há cobrança pendente para esta assinatura.")
    if subscription.provider_subscription_id:
        raise ValueError("Há um pagamento por cartão iniciado. Solicite ajuda ao suporte para mudar para Pix.")
    previous=PixCharge.objects.select_related("payment").filter(
        subscription=subscription,payment__status=Payment.Status.PENDING,
        expires_at__gt=timezone.now(),
    ).order_by("-created_at").first()
    if previous:
        return previous
    gateway=PaymentGateway.objects.filter(
        provider="mercadopago",active=True,last_test_status=PaymentGateway.TestStatus.VALIDATED,
    ).first()
    if not gateway:
        raise RuntimeError("provedor de cobrança da plataforma não está configurado.")
    amount=subscription.contracted_price
    if amount is None:
        months={"monthly":1,"quarterly":3,"semiannual":6,"annual":12}[subscription.billing_cycle]
        amount=getattr(subscription.plan,{"monthly":"monthly_price","quarterly":"quarterly_price","semiannual":"semiannual_price","annual":"annual_price"}[subscription.billing_cycle]) or subscription.plan.monthly_price*months
    amount=Decimal(str(amount)).quantize(Decimal("0.01"))
    if amount<=0:
        raise ValueError("Valor da assinatura inválido.")
    public_id=token_hex(16)
    expiry=timezone.now()+timedelta(hours=24)
    checkout=CheckoutSession.objects.create(
        public_id=public_id,tenant=subscription.tenant,plan=subscription.plan,
        billing_cycle=subscription.billing_cycle,subtotal=amount,total=amount,
        status=CheckoutSession.Status.AWAITING_PAYMENT,
        idempotency_key="subscription-pix-"+public_id,expires_at=expiry,
    )
    reference="subscription-pix-"+public_id
    from .breakdown import subscription_charge_breakdown
    payment=Payment.objects.create(
        tenant=subscription.tenant,subscription=subscription,purpose="subscription",
        reference_id=subscription.pk,provider="mercadopago",environment=gateway.environment,
        provider_reference=reference,idempotency_key="subscription-pix-"+public_id,
        amount=amount,status=Payment.Status.PENDING,due_at=expiry,
        metadata={
            "method":"pix","checkout_session_id":checkout.pk,
            "breakdown":subscription_charge_breakdown(subscription),
        },
    )
    remote=platform_provider(gateway).create_pix_order(
        amount=amount,external_reference=reference,payer_email=payer_email,
        expiration_hours=24,idempotency_key="subscription-pix-"+public_id,
    )
    qr=remote.get("qr_code") or ""
    qr_base64=remote.get("qr_code_base64") or ""
    if not remote.get("order_id") or not (qr or qr_base64):
        raise RuntimeError("provedor de cobrança não retornou o código Pix. Tente novamente.")
    ticket_url=remote.get("ticket_url") or ""
    if ticket_url and not ticket_url.startswith("https://"):
        ticket_url=""
    payment.provider_status=remote.get("status") or "pending"
    payment.provider_payment_id=remote.get("payment_id") or ""
    payment.save(update_fields=["provider_status","provider_payment_id","updated_at"])
    return PixCharge.objects.create(
        public_id=public_id,tenant=subscription.tenant,subscription=subscription,
        checkout_session=checkout,payment=payment,provider_order_id=remote["order_id"],
        provider_payment_id=remote.get("payment_id") or "",amount=amount,
        qr_code=qr,qr_code_base64=qr_base64,ticket_url=ticket_url,
        status="pending",expires_at=expiry,
    )


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
            "display_name":"provedor de cobrança",
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


def connected_tenant_gateway(tenant,provider="mercadopago"):
    connection=TenantPaymentConnection.objects.filter(
        tenant=tenant,
        provider=provider,
        status=TenantPaymentConnection.Status.CONNECTED,
    ).order_by("-environment").first()
    if not connection:
        raise RuntimeError("Nenhum provedor de pagamento conectado.")
    return connection


def has_connected_tenant_gateway(tenant):
    try:
        return bool(connected_tenant_gateway(tenant))
    except RuntimeError:
        return False


def _tenant_tx_status(value):
    from .models import TenantPaymentTransaction
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


def create_tenant_pix(*,tenant,reference_type,reference_id,amount,payer_email,expiration_minutes=10):
    from secrets import token_hex
    from django.db import IntegrityError
    from .models import TenantPaymentTransaction

    connection=connected_tenant_gateway(tenant)
    amount=Decimal(str(amount)).quantize(Decimal("0.01"))
    if amount<=0:
        raise ValueError("Valor da cobrança inválido.")
    if "@" not in payer_email:
        raise ValueError("Informe um e-mail válido para o Pix.")

    base_idempotency=(
        "pix-"+__import__("hashlib").sha256(
            f"{tenant.pk}|{reference_type}|{reference_id}|{amount}".encode()
        ).hexdigest()[:64]
    )
    attempts=TenantPaymentTransaction.objects.filter(tenant=tenant,
        reference_type=reference_type,reference_id=reference_id,gross_amount=amount,method="pix").order_by("-created_at")
    existing=attempts.first()
    if existing and existing.status in {
        TenantPaymentTransaction.Status.CREATED,
        TenantPaymentTransaction.Status.PENDING,
        TenantPaymentTransaction.Status.PAID,
    }:
        return existing
    idempotency=f"{base_idempotency[:75]}-{attempts.count()}"

    external=f"{reference_type[:12].upper()}-{reference_id}-{token_hex(4).upper()}"
    expires_at=timezone.now()+__import__("datetime").timedelta(minutes=max(1,int(expiration_minutes)))

    try:
        with transaction.atomic():
            tx=TenantPaymentTransaction.objects.create(
                tenant=tenant,
                connection=connection,
                reference_type=reference_type,
                reference_id=reference_id,
                external_reference=external,
                method="pix",
                gross_amount=amount,
                net_amount=amount,
                status=TenantPaymentTransaction.Status.CREATED,
                expires_at=expires_at,
                idempotency_key=idempotency,
            )
    except IntegrityError:
        return TenantPaymentTransaction.objects.get(tenant=tenant,idempotency_key=idempotency)

    try:
        remote=tenant_provider(connection).create_pix_order(
            amount=amount,
            external_reference=external,
            payer_email=payer_email,
            expiration_hours=max(1,(max(1,int(expiration_minutes))+59)//60),
            idempotency_key=idempotency,
        )
        tx.provider_transaction_id=remote["order_id"]
        tx.status=_tenant_tx_status(remote["status"])
        tx.pix_qr_code=remote.get("qr_code_base64") or ""
        tx.pix_copy_paste=remote.get("qr_code") or ""
        tx.checkout_url=remote.get("ticket_url") or ""
        tx.save(update_fields=[
            "provider_transaction_id","status","pix_qr_code",
            "pix_copy_paste","checkout_url","updated_at",
        ])
        return tx
    except Exception:
        TenantPaymentTransaction.objects.filter(pk=tx.pk).update(
            status=TenantPaymentTransaction.Status.FAILED,
            updated_at=timezone.now(),
        )
        raise


def create_tenant_card_payment(
    *,tenant,reference_type,reference_id,amount,payer_email,card_token,
    payment_method_id,attempt_id,installments=1,issuer_id="",
    identification=None,notification_url=""
):
    import hashlib
    from secrets import token_hex
    from .models import TenantPaymentTransaction

    connection=connected_tenant_gateway(tenant)
    amount=Decimal(str(amount)).quantize(Decimal("0.01"))
    if amount<=0:
        raise ValueError("Valor da cobrança inválido.")
    if not card_token or not payment_method_id or not attempt_id:
        raise ValueError("Dados tokenizados do cartão incompletos.")

    idempotency="card-"+hashlib.sha256(
        f"{tenant.pk}|{reference_type}|{reference_id}|{amount}|{attempt_id}".encode()
    ).hexdigest()[:64]
    existing=TenantPaymentTransaction.objects.filter(
        tenant=tenant,idempotency_key=idempotency
    ).first()
    if existing:
        return existing

    external=f"{reference_type[:10].upper()}-CARD-{reference_id}-{token_hex(4).upper()}"
    with transaction.atomic():
        tx=TenantPaymentTransaction.objects.create(
            tenant=tenant,
            connection=connection,
            reference_type=reference_type,
            reference_id=reference_id,
            external_reference=external,
            method="card",
            gross_amount=amount,
            net_amount=amount,
            status=TenantPaymentTransaction.Status.CREATED,
            idempotency_key=idempotency,
        )

    try:
        remote=tenant_provider(connection).create_tokenized_card_payment(
            amount=amount,
            token=card_token,
            payment_method_id=payment_method_id,
            payer_email=payer_email,
            external_reference=external,
            installments=installments,
            issuer_id=issuer_id,
            identification=identification,
            notification_url=notification_url,
            description=f"ApPlanner {reference_type} #{reference_id}",
            idempotency_key=idempotency,
        )
        tx.provider_transaction_id=remote["id"]
        tx.status=_tenant_tx_status(remote["status"])
        tx.fee_amount=remote["fee_amount"]
        tx.net_amount=remote["net_received_amount"]
        tx.save(update_fields=[
            "provider_transaction_id","status","fee_amount","net_amount","updated_at"
        ])
        return tx
    except Exception:
        TenantPaymentTransaction.objects.filter(pk=tx.pk).update(
            status=TenantPaymentTransaction.Status.FAILED,
            updated_at=timezone.now(),
        )
        raise


def create_tenant_recurring_subscription(
    *,tenant,reference_type,reference_id,amount,payer_email,back_url,cycle_months=1
):
    import hashlib
    from .models import TenantRecurringSubscription

    connection=connected_tenant_gateway(tenant)
    amount=Decimal(str(amount)).quantize(Decimal("0.01"))
    cycle_months=max(1,min(12,int(cycle_months)))
    idempotency="recurring-"+hashlib.sha256(
        f"{tenant.pk}|{reference_type}|{reference_id}|{amount}|{cycle_months}".encode()
    ).hexdigest()[:64]
    existing=TenantRecurringSubscription.objects.filter(
        tenant=tenant,idempotency_key=idempotency
    ).first()
    if existing:
        return existing

    external=f"{reference_type[:12].upper()}-{reference_id}-{hashlib.sha256(idempotency.encode()).hexdigest()[:8].upper()}"
    remote=tenant_provider(connection).create_subscription(
        reason=f"ApPlanner — {reference_type}",
        external_reference=external,
        payer_email=payer_email,
        back_url=back_url,
        amount=amount,
        frequency=cycle_months,
        idempotency_key=idempotency,
    )
    return TenantRecurringSubscription.objects.create(
        tenant=tenant,
        connection=connection,
        reference_type=reference_type,
        reference_id=reference_id,
        external_reference=external,
        provider_subscription_id=remote["reference"],
        amount=amount,
        cycle_months=cycle_months,
        status=TenantRecurringSubscription.Status.PENDING,
        checkout_url=remote.get("init_point") or "",
        idempotency_key=idempotency,
    )
