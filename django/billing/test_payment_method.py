from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone
from accounts.models import User
from tenants.models import Tenant
from .access import paid_access_until, subscription_allows_access
from .mercadopago import MercadoPagoProvider
from .models import Payment, PaymentGateway, Plan, Subscription, SubscriptionHistory, WebhookEvent
from .payment_method import change_payment_method
from .payment_services import create_platform_pix_charge, create_platform_subscription
from .reminders import billing_notice
from .webhooks import _reconcile_platform


@override_settings(SUBSCRIPTION_ACCESS_ENFORCED=True)
class PaymentMethodTests(TestCase):
    url = '/billing/assinatura/forma-pagamento/'

    def setUp(self):
        self.tenant = Tenant.objects.create(name='Empresa', slug='method-change', onboarding_step=5)
        self.owner = User.objects.create_user(email='owner@example.com', tenant=self.tenant, role='owner')
        self.plan = Plan.objects.create(name='Plano', slug='method-plan', monthly_price=99, quarterly_price=280)
        self.sub = Subscription.objects.create(tenant=self.tenant, plan=self.plan, status='active',
            started_at=timezone.now()-timedelta(days=60), next_billing_at=timezone.now()+timedelta(days=2),
            contracted_price=Decimal('89.90'), payment_method='card', provider_subscription_id='old-card',
            provider_checkout_url='https://example.test/old', provider_environment='sandbox')
        Payment.objects.create(tenant=self.tenant, subscription=self.sub, amount=89.9, status='paid',
            paid_at=timezone.now()-timedelta(days=29))
        self.gateway = PaymentGateway.objects.create(environment='sandbox', active=True, last_test_status='validated',
            access_token_encrypted='unused', webhook_secret_encrypted='unused')
        self.client.force_login(self.owner)
        self.provider = Mock()
        self.provider.get_subscription.return_value = {'status': 'authorized'}
        self.provider.cancel_subscription.return_value = {'status': 'cancelled'}
        self.provider.create_subscription.return_value = {'reference': 'new-card', 'init_point': 'https://example.test/new'}

    def switch(self, method, version=0):
        return change_payment_method(tenant_id=self.tenant.pk, method=method, expected_version=version)

    def test_card_to_pix_preserves_paid_access(self):
        deadline = paid_access_until(self.sub)
        with patch('billing.payment_method.platform_provider', return_value=self.provider):
            self.switch('pix')
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.payment_method, 'pix')
        self.assertEqual(self.sub.payment_method_version, 1)
        self.assertEqual(self.sub.provider_subscription_id, '')
        self.assertEqual(self.sub.provider_checkout_url, '')
        self.assertEqual(self.sub.status, 'active')
        self.assertEqual(paid_access_until(self.sub), deadline)
        self.assertTrue(subscription_allows_access(self.sub))
        self.provider.cancel_subscription.assert_called_once_with('old-card')
        self.assertEqual(SubscriptionHistory.objects.count(), 1)

    def test_failed_cancellation_preserves_current_method(self):
        self.provider.cancel_subscription.return_value = {'status': 'authorized'}
        with patch('billing.payment_method.platform_provider', return_value=self.provider):
            with self.assertRaisesMessage(ValueError, 'não confirmou'):
                self.switch('pix')
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.provider_subscription_id, 'old-card')
        self.assertEqual(self.sub.payment_method_version, 0)
        self.assertFalse(SubscriptionHistory.objects.exists())

    def test_retry_of_already_cancelled_authorization(self):
        self.provider.get_subscription.return_value = {'status': 'canceled'}
        with patch('billing.payment_method.platform_provider', return_value=self.provider):
            self.switch('pix')
        self.provider.cancel_subscription.assert_not_called()

    def test_late_old_webhook_cannot_cancel_subscription(self):
        with patch('billing.payment_method.platform_provider', return_value=self.provider):
            self.switch('pix')
        event = WebhookEvent.objects.create(provider='mercadopago', event_id='old-event', resource_id='old-card', payload_hash='a'*64)
        self.provider.get_subscription.return_value = {'status': 'cancelled'}
        with patch('billing.webhooks.platform_provider', return_value=self.provider):
            _reconcile_platform(event, self.gateway, {'type': 'subscription_preapproval'}, 'old-card')
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, 'active')
        self.assertTrue(subscription_allows_access(self.sub))

    def test_active_pix_to_card_preserves_paid_cycle_and_contract(self):
        self.sub.provider_subscription_id = ''
        self.sub.provider_checkout_url = ''
        self.sub.payment_method = 'pix'
        self.sub.billing_cycle = 'quarterly'
        self.sub.save()
        deadline = paid_access_until(self.sub)
        self.switch('card')
        self.assertContains(self.client.get('/billing/assinatura/'), 'Configurar cartão')
        with patch('billing.payment_services.platform_provider', return_value=self.provider):
            response = self.client.post('/billing/assinatura/pagar/')
        self.assertEqual(response.url, 'https://example.test/new')
        args = self.provider.create_subscription.call_args.kwargs
        self.assertEqual(args['start_at'], deadline)
        self.assertEqual(args['amount'], Decimal('89.90'))
        self.assertEqual(args['frequency'], 3)
        self.assertEqual(args['trial_days'], 0)
        self.assertIn('-v1-', args['idempotency_key'])

    def test_card_pix_card_uses_new_authorization_version(self):
        with patch('billing.payment_method.platform_provider', return_value=self.provider):
            self.switch('pix')
        self.switch('card', 1)
        with patch('billing.payment_services.platform_provider', return_value=self.provider):
            self.client.post('/billing/assinatura/pagar/')
        self.assertIn('-v2-', self.provider.create_subscription.call_args.kwargs['idempotency_key'])

    def test_pending_pix_blocks_switch_until_expiration(self):
        self.sub.provider_subscription_id = ''
        self.sub.provider_checkout_url = ''
        self.sub.payment_method = 'pix'
        self.sub.status = 'past_due'
        self.sub.save()
        self.provider.create_pix_order.return_value = {'order_id': 'pix-order', 'payment_id': 'pix-payment',
            'qr_code': 'PIX', 'status': 'action_required'}
        with patch('billing.payment_services.platform_provider', return_value=self.provider):
            charge = create_platform_pix_charge(subscription=self.sub, payer_email=self.owner.email)
        with self.assertRaisesMessage(ValueError, 'Pix pendente'):
            self.switch('card')
        charge.expires_at = timezone.now()-timedelta(seconds=1)
        charge.save()
        self.switch('card')
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.payment_method, 'card')
        self.assertEqual(charge.payment.status, 'pending')

    def test_owner_only_post_and_stale_form_rejected(self):
        self.assertContains(self.client.get('/billing/assinatura/'), 'Confirmar alteração')
        self.assertEqual(self.client.get(self.url).status_code, 405)
        response = self.client.post(self.url, {'payment_method': 'pix', 'payment_method_version': 9}, follow=True)
        self.assertContains(response, 'Recarregue a página')
        manager = User.objects.create_user(email='manager@example.com', tenant=self.tenant, role='manager')
        self.client.force_login(manager)
        self.assertEqual(self.client.post(self.url, {'payment_method': 'pix', 'payment_method_version': 0}).status_code, 403)

    def test_request_cannot_modify_another_company(self):
        other = Tenant.objects.create(name='Outra', slug='other-method')
        other_sub = Subscription.objects.create(tenant=other, plan=self.plan, status='trial', payment_method='pix', started_at=timezone.now())
        with patch('billing.payment_method.platform_provider', return_value=self.provider):
            self.client.post(self.url, {'payment_method': 'pix', 'payment_method_version': 0, 'subscription': other_sub.pk})
        self.sub.refresh_from_db()
        other_sub.refresh_from_db()
        self.assertEqual(self.sub.payment_method_version, 1)
        self.assertEqual(other_sub.payment_method_version, 0)

    def test_switch_does_not_unlock_unpaid_expired_company(self):
        self.sub.payments.all().delete()
        self.sub.provider_subscription_id = ''
        self.sub.provider_checkout_url = ''
        self.sub.status = 'past_due'
        self.sub.payment_method = 'pix'
        self.sub.save()
        self.assertEqual(self.client.post(self.url, {'payment_method': 'card', 'payment_method_version': 0}).status_code, 302)
        self.sub.refresh_from_db()
        self.assertFalse(subscription_allows_access(self.sub))
        self.assertEqual(self.client.get('/').url, '/billing/assinatura/')

    def test_direct_services_respect_selected_method(self):
        self.sub.status = 'past_due'
        self.sub.provider_subscription_id = ''
        self.sub.provider_checkout_url = ''
        self.sub.save()
        with self.assertRaisesMessage(ValueError, 'Selecione Pix'):
            create_platform_pix_charge(subscription=self.sub, payer_email=self.owner.email)
        self.sub.payment_method = 'pix'
        self.sub.save()
        with self.assertRaisesMessage(ValueError, 'Selecione cartão'):
            create_platform_subscription(subscription=self.sub, payer_email=self.owner.email, back_url='https://example.test', idempotency_key='test')

    def test_card_without_authorization_reminder(self):
        self.sub.provider_subscription_id = ''
        self.sub.provider_checkout_url = ''
        self.sub.save()
        self.assertIn('Configure a autorização do cartão', billing_notice(self.sub)['message'])


class CardStartDateTests(SimpleTestCase):
    def test_future_start_does_not_grant_another_free_trial(self):
        calls = []
        def transport(method, path, payload, idempotency, token):
            calls.append(payload)
            return {'id': 'card', 'init_point': 'https://example.test'}
        deadline = timezone.now()+timedelta(days=10)
        MercadoPagoProvider('TEST-123456789012345', transport=transport).create_subscription(
            reason='Plano', external_reference='subscription:1', payer_email='owner@example.com',
            back_url='https://example.test', amount=Decimal('99'), frequency=1, trial_days=14,
            start_at=deadline, idempotency_key='new-card')
        self.assertEqual(calls[0]['auto_recurring']['start_date'], deadline.isoformat())
        self.assertNotIn('free_trial', calls[0]['auto_recurring'])
