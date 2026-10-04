from datetime import timedelta
from unittest.mock import Mock, patch
from django.test import TestCase, override_settings
from django.utils import timezone
from accounts.models import User
from tenants.models import Tenant
from . import test_platform_pix as fixtures
from .models import Payment, PixCharge, Subscription
from .pix_reconciliation import reconcile_pix_charge
from .tasks import reconcile_pending_pix
from .webhooks import _reconcile_platform


@override_settings(SUBSCRIPTION_ACCESS_ENFORCED=True)
class PixReconciliationTests(TestCase):
    _charge = fixtures.PlatformPixTests._charge
    _order = fixtures.PlatformPixTests._order
    _event = fixtures.PlatformPixTests._event
    url = '/billing/assinatura/pix/verificar/'

    def setUp(self):
        fixtures.PlatformPixTests.setUp(self)
        self.charge = self._charge()
        self.provider = Mock()
        self.provider.get_order.return_value = self._order(self.charge)
        self.provider.get_payment.return_value = {'status': 'approved', 'transaction_amount': '49.90',
            'external_reference': self.charge.payment.provider_reference}

    def test_payment_notification_also_reconciles_order(self):
        with patch('billing.webhooks.platform_provider', return_value=self.provider):
            _reconcile_platform(self._event(), self.gateway, {'type': 'payment'}, 'pay-pix-1')
        self.charge.refresh_from_db()
        self.subscription.refresh_from_db()
        self.assertEqual(self.charge.status, 'paid')
        self.assertEqual(self.subscription.status, 'active')
        self.provider.get_order.assert_called_once_with('order-pix-1')

    def test_payment_notification_without_processed_order_keeps_pending(self):
        self.provider.get_order.return_value = {**self._order(self.charge), 'status': 'action_required'}
        with patch('billing.webhooks.platform_provider', return_value=self.provider):
            _reconcile_platform(self._event(), self.gateway, {'type': 'payment'}, 'pay-pix-1')
        self.charge.payment.refresh_from_db()
        self.assertEqual(self.charge.payment.status, 'pending')

    def test_manual_check_unlocks_and_does_not_create_another_charge(self):
        self.client.force_login(self.owner)
        self.assertContains(self.client.get('/billing/assinatura/'), 'Já paguei')
        with patch('billing.pix_reconciliation.platform_provider', return_value=self.provider):
            response = self.client.post(self.url, follow=True)
        self.assertContains(response, 'Pix confirmado pelo Mercado Pago')
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(PixCharge.objects.count(), 1)
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_retries_do_not_extend_cycle_twice(self):
        with patch('billing.pix_reconciliation.platform_provider', return_value=self.provider):
            self.assertTrue(reconcile_pix_charge(self.charge.pk))
            self.subscription.refresh_from_db()
            deadline = self.subscription.next_billing_at
            self.assertTrue(reconcile_pix_charge(self.charge.pk))
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.next_billing_at, deadline)

    def test_partial_old_confirmation_repairs_charge_without_extra_cycle(self):
        from .access import paid_access_until
        self.charge.payment.status='paid'
        self.charge.payment.paid_at=timezone.now()
        self.charge.payment.save()
        deadline=paid_access_until(self.subscription)
        with patch('billing.pix_reconciliation.platform_provider',return_value=self.provider):
            reconcile_pix_charge(self.charge.pk)
        self.subscription.refresh_from_db()
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status,'paid')
        self.assertEqual(self.subscription.next_billing_at,deadline)

    def test_active_expired_subscription_gets_new_cycle(self):
        self.subscription.status = 'active'
        self.subscription.next_billing_at = timezone.now()-timedelta(days=1)
        self.subscription.save()
        with patch('billing.pix_reconciliation.platform_provider', return_value=self.provider):
            reconcile_pix_charge(self.charge.pk)
        self.subscription.refresh_from_db()
        self.assertGreater(self.subscription.next_billing_at, timezone.now()+timedelta(days=27))

    def test_old_qr_can_be_verified_after_expiry(self):
        self.charge.expires_at = timezone.now()-timedelta(days=1)
        self.charge.save()
        self.client.force_login(self.owner)
        self.assertContains(self.client.get('/billing/assinatura/'), 'Já paguei')
        with patch('billing.pix_reconciliation.platform_provider', return_value=self.provider):
            self.client.post(self.url)
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status, 'paid')

    def test_wrong_amount_currency_reference_or_order_never_unlocks(self):
        for values in [{'total_paid_amount': '0.01'}, {'currency_id': 'USD'},
                {'external_reference': 'another-company'}, {'id': 'another-order'}]:
            self.provider.get_order.return_value = {**self._order(self.charge), **values}
            with patch('billing.pix_reconciliation.platform_provider', return_value=self.provider):
                with self.assertRaises(ValueError):
                    reconcile_pix_charge(self.charge.pk)
            self.charge.payment.refresh_from_db()
            self.assertEqual(self.charge.payment.status, 'pending')

    def test_cancelled_subscription_is_not_reactivated(self):
        self.subscription.status = 'cancelled'
        self.subscription.save()
        with patch('billing.pix_reconciliation.platform_provider', return_value=self.provider):
            reconcile_pix_charge(self.charge.pk)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, 'cancelled')
        self.charge.payment.refresh_from_db()
        self.assertEqual(self.charge.payment.status, 'paid')

    def test_refresh_is_post_only_and_company_scoped(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        other = Tenant.objects.create(name='Outra', slug='other-pix')
        owner = User.objects.create_user(email='other@example.com', tenant=other, role='owner')
        self.client.force_login(owner)
        with patch('billing.pix_reconciliation.platform_provider') as provider:
            self.client.post(self.url, {'charge': self.charge.pk})
        provider.assert_not_called()
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status, 'pending')

    def test_background_check_recovers_missing_webhook(self):
        with patch('billing.pix_reconciliation.platform_provider', return_value=self.provider):
            self.assertEqual(reconcile_pending_pix.run(), 1)
            self.assertEqual(reconcile_pending_pix.run(), 0)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, 'active')

    def test_gateway_environment_must_match_charge(self):
        self.gateway.environment = 'production'
        with self.assertRaisesMessage(ValueError, 'ambiente'):
            reconcile_pix_charge(self.charge.pk, gateway=self.gateway, provider=self.provider)
        self.provider.get_order.assert_not_called()

    def test_provider_failure_does_not_mark_paid(self):
        self.client.force_login(self.owner)
        self.provider.get_order.side_effect = RuntimeError('consulta indisponível')
        with patch('billing.pix_reconciliation.platform_provider', return_value=self.provider):
            response = self.client.post(self.url, follow=True)
        self.assertContains(response, 'Não foi possível consultar o Pix agora')
        self.charge.payment.refresh_from_db()
        self.assertEqual(self.charge.payment.status, 'pending')
