"""Change future subscription payments without removing paid access."""
from django.db import transaction
from django.utils import timezone

from .access import paid_access_until
from .models import Payment, PaymentGateway, PixCharge, Subscription, SubscriptionHistory
from .payment_services import platform_provider


@transaction.atomic
def change_payment_method(*,tenant_id,method,expected_version):
    if method not in Subscription.PaymentMethod.values:
        raise ValueError("Escolha cartão ou Pix.")
    subscription=Subscription.objects.select_for_update().filter(tenant_id=tenant_id).order_by("-started_at","-pk").first()
    if not subscription or subscription.status not in {"trial","active","past_due"}:
        raise ValueError("Esta assinatura não permite alterar a forma de pagamento. Contate o suporte.")
    if expected_version!=subscription.payment_method_version:
        raise ValueError("A forma de pagamento foi atualizada. Recarregue a página antes de continuar.")
    if method==subscription.payment_method and not (method=="pix" and subscription.provider_subscription_id):
        return subscription
    if method=="card" and PixCharge.objects.filter(subscription=subscription,payment__status=Payment.Status.PENDING,
            expires_at__gt=timezone.now()).exists():
        raise ValueError("Existe um Pix pendente. Conclua o pagamento ou aguarde sua expiração antes de mudar para cartão.")
    previous=subscription.payment_method or ("card" if subscription.provider_subscription_id else "não definida")
    if method=="pix" and subscription.provider_subscription_id:
        gateways=PaymentGateway.objects.filter(provider="mercadopago",last_test_status="validated")
        gateways=gateways.filter(environment=subscription.provider_environment) if subscription.provider_environment else gateways.filter(active=True)
        gateway=gateways.first()
        if not gateway:
            raise ValueError("A conexão de cobrança está indisponível. A forma de pagamento foi mantida; contate o suporte.")
        provider=platform_provider(gateway)
        remote=provider.get_subscription(subscription.provider_subscription_id)
        if remote.get("status") not in {"canceled","cancelled"}:
            remote=provider.cancel_subscription(subscription.provider_subscription_id)
        if remote.get("status") not in {"canceled","cancelled"}:
            raise ValueError("O provedor não confirmou o encerramento da cobrança automática. A forma de pagamento foi mantida.")
        # Persist the paid boundary before detaching the old card authorization.
        covered_until=paid_access_until(subscription)
        if covered_until:
            subscription.next_billing_at=covered_until
        subscription.provider_subscription_id=""
        subscription.provider_checkout_url=""
        subscription.provider_environment=""
        subscription.provider_plan_id=""
    subscription.payment_method=method
    subscription.payment_method_version+=1
    subscription.save(update_fields=["payment_method","payment_method_version","next_billing_at",
        "provider_subscription_id","provider_checkout_url","provider_environment","provider_plan_id","updated_at"])
    SubscriptionHistory.objects.create(tenant_id=tenant_id,subscription=subscription,from_plan=subscription.plan,
        to_plan=subscription.plan,from_status=subscription.status,to_status=subscription.status,
        reason=f"Forma de pagamento alterada de {previous} para {method}")
    return subscription
