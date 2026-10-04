from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch
from django.test import TestCase,override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from tenants.models import Tenant
from billing.models import Plan,Subscription,Payment
from billing.access import subscription_allows_access


@override_settings(SUBSCRIPTION_ACCESS_ENFORCED=True)
class SubscriptionAccessTests(TestCase):
    def setUp(self):
        self.now=timezone.now()
        self.tenant=Tenant.objects.create(name='Empresa',slug='subscription-access',public_enabled=True,status='active',onboarding_step=5)
        self.owner=User.objects.create_user(email='access@example.com',tenant=self.tenant,role='owner')
        self.plan=Plan.objects.create(name='Plano',slug='access-plan',monthly_price='99.90')
        self.subscription=Subscription.objects.create(tenant=self.tenant,plan=self.plan,status='trial',started_at=self.now,
            trial_started_at=self.now,trial_ends_at=self.now+timedelta(days=2))
        self.client.force_login(self.owner)

    def expire(self):
        self.subscription.trial_ends_at=self.now-timedelta(seconds=1)
        self.subscription.save()

    def pay(self):
        return Payment.objects.create(tenant=self.tenant,subscription=self.subscription,status='paid',paid_at=self.now,
            amount='99.90',purpose='subscription')

    def test_live_trial_allows_access_without_payment(self):
        self.assertEqual(self.client.get('/').status_code,200)

    def test_expired_trial_blocks_get_post_and_api_before_cron_runs(self):
        self.expire()
        self.assertRedirects(self.client.get('/'),reverse('billing-subscription-status'),fetch_redirect_response=False)
        self.assertRedirects(self.client.post('/app/agenda/clientes/novo/',{'name':'Não criar'}),reverse('billing-subscription-status'),fetch_redirect_response=False)
        response=self.client.get('/api/scheduling/availability/')
        self.assertEqual(response.status_code,402)
        self.assertEqual(response.json()['code'],'subscription_payment_required')

    def test_payment_screen_is_accessible_and_does_not_loop(self):
        self.expire()
        response=self.client.get(reverse('billing-subscription-status'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Seu acesso está bloqueado')
        self.assertEqual(self.client.post(reverse('accounts:logout')).status_code,302)

    def test_no_subscription_is_blocked(self):
        self.subscription.delete()
        self.assertRedirects(self.client.get('/'),reverse('billing-subscription-status'),fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('billing-subscription-status')).status_code,200)

    def test_active_authorization_without_payment_does_not_unlock(self):
        self.expire()
        self.subscription.status='active'
        self.subscription.provider_subscription_id='authorized-only'
        self.subscription.provider_checkout_url='https://example.com/payment'
        self.subscription.save()
        self.assertFalse(subscription_allows_access(self.subscription))
        self.assertRedirects(self.client.get('/'),reverse('billing-subscription-status'),fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse('billing-subscription-status')),'Continuar pagamento seguro')

    def test_pending_payment_does_not_unlock(self):
        self.expire()
        Payment.objects.create(tenant=self.tenant,subscription=self.subscription,status='pending',amount='99.90')
        self.assertFalse(subscription_allows_access(self.subscription))

    def test_confirmed_payment_unlocks_existing_session_on_next_request(self):
        self.expire()
        self.assertEqual(self.client.get('/').status_code,302)
        self.pay()
        self.assertEqual(self.client.get('/').status_code,200)

    def test_old_or_unrelated_payment_does_not_unlock(self):
        self.expire()
        payment=self.pay()
        payment.paid_at=self.now-timedelta(days=90)
        payment.save()
        self.assertFalse(subscription_allows_access(self.subscription))
        payment.paid_at=self.now
        payment.purpose='appointment'
        payment.save()
        self.assertFalse(subscription_allows_access(self.subscription))

    def test_cancelled_subscription_remains_blocked_even_when_paid(self):
        self.pay()
        self.subscription.status='cancelled'
        self.subscription.save()
        self.assertFalse(subscription_allows_access(self.subscription))

    def test_staff_are_also_blocked_and_master_keeps_platform_access(self):
        self.expire()
        self.owner.role='professional'
        self.owner.save()
        self.assertRedirects(self.client.get('/app/profissional/'),reverse('billing-subscription-status'),fetch_redirect_response=False)
        self.owner.is_superuser=True
        self.owner.save()
        self.assertEqual(self.client.get('/').status_code,200)

    def test_public_booking_cannot_bypass_suspended_operation(self):
        self.expire()
        self.client.logout()
        self.assertEqual(self.client.get(reverse('tenant-public',args=[self.tenant.slug])).status_code,403)
        self.assertEqual(self.client.post(reverse('public-booking',args=[self.tenant.slug]),{}).status_code,402)
        self.assertEqual(self.client.get(reverse('accounts:login')).status_code,200)

    def test_popup_only_on_two_days_and_expiry_day_once_per_login(self):
        fixed=datetime(2026,10,4,12,tzinfo=ZoneInfo('America/Recife'))
        for days in (3,2,1,0,-1):
            with self.subTest(days=days),patch('billing.access.timezone.now',return_value=fixed):
                self.subscription.trial_ends_at=fixed+timedelta(days=days,hours=1)
                self.subscription.save()
                self.client.force_login(self.owner)
                response=self.client.get(reverse('billing-subscription-status'))
                html=response.content.decode()
                self.assertEqual('id="trial-subscription-dialog"' in html,days in (2,0))
                self.assertNotContains(self.client.get(reverse('billing-subscription-status')),'id="trial-subscription-dialog"')

    def test_popup_uses_tenant_timezone_and_paid_accounts_do_not_see_it(self):
        fixed=datetime(2026,10,5,1,tzinfo=ZoneInfo('UTC'))  # Still October 4 in Recife.
        self.subscription.trial_ends_at=datetime(2026,10,7,1,tzinfo=ZoneInfo('UTC'))
        self.subscription.save()
        with patch('billing.access.timezone.now',return_value=fixed):
            self.assertContains(self.client.get(reverse('billing-subscription-status')),'termina em 2 dias')
            self.pay()
            self.client.force_login(self.owner)
            self.assertNotContains(self.client.get(reverse('billing-subscription-status')),'id="trial-subscription-dialog"')

    def test_api_token_cannot_bypass_payment_block(self):
        import hashlib
        from accounts.models import PersonalAPIToken
        raw='ap_subscription_access_test'
        PersonalAPIToken.objects.create(user=self.owner,tenant=self.tenant,name='Test',prefix=raw[:12],
            secret_hash=hashlib.sha256(raw.encode()).hexdigest(),scopes=['agenda.read'],
            session_version=self.owner.session_version,expires_at=self.now+timedelta(days=1))
        self.expire()
        self.client.logout()
        self.assertEqual(self.client.get('/api/v1/clientes/',HTTP_AUTHORIZATION='Bearer '+raw).status_code,402)

    def test_payment_still_works_when_legal_acceptance_is_pending(self):
        from legal.models import LegalDocument
        self.expire()
        LegalDocument.objects.create(type='terms',title='Termos',version='test',content='Termos',
            status='published',published_at=self.now,requires_acceptance=True)
        self.assertEqual(self.client.get(reverse('billing-subscription-status')).status_code,200)

    def test_unpaid_authorized_card_can_subscribe_before_trial_ends(self):
        from billing.access import eligible_for_payment
        self.subscription.status='active'
        self.subscription.provider_checkout_url='https://example.com/payment'
        self.subscription.save()
        self.assertTrue(eligible_for_payment(self.subscription))
        self.assertContains(self.client.get(reverse('billing-subscription-status')),'Continuar pagamento seguro')
