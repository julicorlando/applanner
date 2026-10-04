"""Verify platform Pix orders using the authenticated provider API."""
from decimal import Decimal, InvalidOperation
from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.utils import timezone
from .access import paid_access_until
from .models import CheckoutSession, Payment, PaymentGateway, PixCharge, Subscription
from .payment_services import platform_provider


def reconcile_pix_charge(charge_id, *, gateway=None, provider=None, order=None):
    charge = PixCharge.objects.select_related('payment').get(pk=charge_id)
    if gateway is None:
        gateway = PaymentGateway.objects.filter(provider='mercadopago', environment=charge.payment.environment,
            last_test_status='validated').first()
    if not gateway or gateway.environment != charge.payment.environment:
        raise ValueError('A conexão do ambiente desta cobrança Pix está indisponível.')
    provider = provider or platform_provider(gateway)
    order = order if order is not None else provider.get_order(charge.provider_order_id)
    with transaction.atomic():
        # Same lock order as charge creation and payment-method changes.
        subscription = Subscription.objects.select_for_update().get(pk=charge.subscription_id)
        payment = Payment.objects.select_for_update().get(pk=charge.payment_id)
        charge = PixCharge.objects.select_for_update().get(pk=charge_id)
        if payment.status == Payment.Status.PAID and charge.status == 'paid':
            return True
        if payment.status in {Payment.Status.CANCELLED, Payment.Status.REFUNDED, Payment.Status.PARTIALLY_REFUNDED}:
            return False
        if str(order.get('id') or '') != charge.provider_order_id:
            raise ValueError('Pedido Pix não corresponde à cobrança registrada: identificador do pedido divergente.')
        if order.get('external_reference') != payment.provider_reference:
            raise ValueError('Pedido Pix não corresponde à cobrança registrada: referência da cobrança divergente.')
        # Orders API identifies the country, while Payments API and some
        # notification representations supply currency_id. Brazil Orders use BRL.
        currency = order.get('currency_id')
        country = order.get('country_code')
        if (currency and currency != 'BRL') or (country and country != 'BR'):
            raise ValueError('Pedido Pix não corresponde à cobrança registrada: moeda ou país divergente.')
        if not currency and country != 'BR':
            raise ValueError('Não foi possível validar a moeda do Pix: país e moeda não informados pelo provedor.')
        rows = (order.get('transactions') or {}).get('payments') or []
        paid_rows = [row for row in rows if row.get('status') in {'approved', 'processed'} and
            (row.get('payment_method') or {}).get('id') == 'pix']
        if order.get('status') != 'processed' or not paid_rows:
            return False
        try:
            paid_amount = Decimal(str(order.get('total_paid_amount') or '0'))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError('Valor do Pix informado pelo provedor é inválido.') from exc
        if not paid_amount.is_finite() or paid_amount != payment.amount:
            raise ValueError('Valor do Pix confirmado difere da cobrança.')
        paid_at = timezone.now()
        # Calculate coverage before recording the new payment; retries must not extend it.
        already_paid = payment.status == Payment.Status.PAID
        prior_coverage = paid_access_until(subscription)
        cycle_start = max(paid_at, subscription.trial_ends_at or paid_at, prior_coverage or paid_at)
        months = {'monthly': 1, 'quarterly': 3, 'semiannual': 6, 'annual': 12}[subscription.billing_cycle]
        payment.status = Payment.Status.PAID
        payment.paid_at = payment.paid_at or paid_at
        payment.provider_status = 'processed'
        payment.provider_payment_id = str(paid_rows[0].get('id') or payment.provider_payment_id)
        payment.save(update_fields=['status', 'paid_at', 'provider_status', 'provider_payment_id', 'updated_at'])
        charge.status = 'paid'
        charge.paid_at = charge.paid_at or paid_at
        charge.save(update_fields=['status', 'paid_at', 'updated_at'])
        CheckoutSession.objects.filter(pk=charge.checkout_session_id).update(status=CheckoutSession.Status.PAID, updated_at=paid_at)
        if subscription.status in {Subscription.Status.TRIAL, Subscription.Status.PAST_DUE, Subscription.Status.ACTIVE}:
            subscription.status = Subscription.Status.ACTIVE
            subscription.next_billing_at = prior_coverage if already_paid else cycle_start + relativedelta(months=months)
            subscription.save(update_fields=['status', 'next_billing_at', 'updated_at'])
        return True
