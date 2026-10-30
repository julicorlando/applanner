from decimal import Decimal
from unittest.mock import Mock,patch

from django.test import TestCase
from django.utils import timezone

from billing.models import Payment,PaymentGateway,Plan,Subscription,WebhookEvent
from billing.webhooks import _reconcile_platform
from tenants.models import Tenant


class CardWebhookIntegrityTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name='Cartão',slug='card-webhook-integrity')
        self.plan=Plan.objects.create(name='Plano',slug='card-integrity-plan',monthly_price=99)
        self.subscription=Subscription.objects.create(tenant=self.tenant,plan=self.plan,status='past_due',
            started_at=timezone.now(),contracted_price=Decimal('99.00'),provider_environment='production')
        self.gateway=PaymentGateway.objects.create(environment='production',active=True)
        self.payment=Payment.objects.create(tenant=self.tenant,subscription=self.subscription,
            provider='mercadopago',environment='production',provider_reference=f'subscription:{self.subscription.pk}',
            provider_payment_id='card-1',amount=Decimal('99.00'),status=Payment.Status.PENDING,
            metadata={'method':'card_recurring'})
        self.event=WebhookEvent.objects.create(provider='mercadopago',event_id='card-integrity',
            resource_id='card-1',payload_hash='a'*64)
        self.remote={'id':'card-1','status':'approved','currency_id':'BRL','transaction_amount':'99.00',
            'external_reference':self.payment.provider_reference,'live_mode':True,
            'fee_details':[],'transaction_details':{'net_received_amount':'99.00'}}

    def reconcile(self,**overrides):
        provider=Mock()
        provider.get_payment.return_value={**self.remote,**overrides}
        with patch('billing.webhooks.platform_provider',return_value=provider):
            _reconcile_platform(self.event,self.gateway,{'type':'payment'},'card-1')

    def test_valid_card_payment_activates_subscription(self):
        self.reconcile()
        self.subscription.refresh_from_db();self.payment.refresh_from_db()
        self.assertEqual(self.subscription.status,Subscription.Status.ACTIVE)
        self.assertEqual(self.payment.status,Payment.Status.PAID)
        self.assertEqual(self.payment.metadata['accounting']['net_received'],'99.00')

    def test_mismatched_provider_data_never_activates_subscription(self):
        for overrides in ({'transaction_amount':'0.50'},{'currency_id':'USD'},
                          {'external_reference':'subscription:9999'},{'live_mode':False},{'id':'other-card'}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    self.reconcile(**overrides)
                self.payment.refresh_from_db();self.subscription.refresh_from_db()
                self.assertEqual(self.payment.status,Payment.Status.PENDING)
                self.assertEqual(self.payment.amount,Decimal('99.00'))
                self.assertEqual(self.subscription.status,Subscription.Status.PAST_DUE)

    def test_stale_approved_event_cannot_reverse_refund(self):
        self.payment.status=Payment.Status.REFUNDED
        self.payment.metadata={'method':'card_recurring','accounting':{'refunded':'99.00'}}
        self.payment.save(update_fields=['status','metadata'])
        with self.assertRaises(ValueError):
            self.reconcile()
        self.payment.refresh_from_db();self.subscription.refresh_from_db()
        self.assertEqual(self.payment.status,Payment.Status.REFUNDED)
        self.assertEqual(self.subscription.status,Subscription.Status.PAST_DUE)

    def test_first_recurring_payment_must_match_contracted_price(self):
        self.payment.delete()
        with self.assertRaises(ValueError):
            self.reconcile(transaction_amount='0.50')
        self.assertFalse(Payment.objects.filter(subscription=self.subscription).exists())
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status,Subscription.Status.PAST_DUE)

    def test_next_cycle_keeps_previous_payment_and_creates_new_charge(self):
        self.payment.status=Payment.Status.PAID
        self.payment.save(update_fields=['status'])
        provider=Mock()
        provider.get_payment.return_value={**self.remote,'id':'card-2'}
        with patch('billing.webhooks.platform_provider',return_value=provider):
            _reconcile_platform(self.event,self.gateway,{'type':'payment'},'card-2')
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.provider_payment_id,'card-1')
        self.assertEqual(Payment.objects.filter(subscription=self.subscription,status=Payment.Status.PAID).count(),2)
        self.assertTrue(Payment.objects.filter(provider_payment_id='card-2').exists())
