from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch,Mock
from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from accounts.models import User
from tenants.models import Tenant,Unit
from communications.models import UserNotification,Notification
from .models import Plan,Subscription,SubscriptionPriceChange,Module,TenantModuleAddon,Payment,PixCharge
from .commercial_pricing import cycle_price,offer,schedule_plan_renewals,prepare_price_changes
from .breakdown import subscription_charge_breakdown

class CommercialPricingTests(TestCase):
    def setUp(self):
        self.now=timezone.now()
        self.plan=Plan.objects.create(name='Plano comercial',slug='commercial-test',monthly_price=Decimal('100'),annual_discount=10,trial_days=7,features={'units':1,'professionals':3})
        self.tenant=Tenant.objects.create(name='Empresa',slug='commercial-company',status='active')
        self.owner=User.objects.create_user(email='commercial@example.test',password='test-only',tenant=self.tenant,role='owner')
        self.sub=Subscription.objects.create(tenant=self.tenant,plan=self.plan,started_at=self.now,status='active',billing_cycle='monthly',contracted_price=100,base_contracted_price=100,next_billing_at=self.now+timedelta(days=35))

    def test_cycle_discount_and_fixed_price_are_exact_and_validated(self):
        self.assertEqual(cycle_price(self.plan,'annual'),Decimal('1080.00'))
        self.plan.annual_price=Decimal('1050')
        with self.assertRaises(ValidationError): self.plan.full_clean()
        self.plan.annual_discount=0
        self.assertEqual(cycle_price(self.plan,'annual'),Decimal('1050'))

    def test_catalog_edit_freezes_legacy_contract_instead_of_repricing(self):
        self.sub.base_contracted_price=None;self.sub.contracted_price=Decimal('85');self.sub.save()
        self.plan.monthly_price=Decimal('150');self.plan.save()
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.base_contracted_price,Decimal('85'))
        self.assertEqual(subscription_charge_breakdown(self.sub)['total'],'85.00')
        self.assertEqual(cycle_price(self.plan,'monthly'),Decimal('150'))

    def test_promotion_is_monthly_time_limited_and_does_not_change_existing_contract(self):
        self.plan.promotion_price=Decimal('79.90');self.plan.promotion_months=3
        self.plan.promotion_ends_at=self.now+timedelta(days=1);self.plan.save()
        self.assertEqual(offer(self.plan,'monthly',self.now)['amount'],Decimal('79.90'))
        self.assertEqual(offer(self.plan,'annual',self.now)['promotion_months'],0)
        self.assertEqual(offer(self.plan,'monthly',self.now+timedelta(days=2))['amount'],Decimal('100'))
        self.sub.refresh_from_db();self.assertEqual(self.sub.contracted_price,Decimal('100'))

    def test_renewal_is_announced_once_and_preserves_pending_payments(self):
        Payment.objects.create(tenant=self.tenant,subscription=self.sub,amount=100,purpose='subscription',status='paid',paid_at=self.now)
        self.plan.monthly_price=Decimal('120');self.plan.save()
        self.assertEqual(schedule_plan_renewals(self.plan,self.owner,self.now),1)
        self.assertEqual(schedule_plan_renewals(self.plan,self.owner,self.now),0)
        change=self.sub.price_changes.get();self.assertGreaterEqual(change.effective_at,self.now+timedelta(days=30))
        self.assertEqual(UserNotification.objects.filter(user=self.owner).count(),1)
        self.assertEqual(Notification.objects.filter(template_key='subscription_price_change').count(),1)
        payment=Payment.objects.create(tenant=self.tenant,subscription=self.sub,amount=100,purpose='subscription',status='pending')
        prepare_price_changes(self.sub,self.now);self.sub.refresh_from_db()
        self.assertEqual(self.sub.contracted_price,Decimal('100'))
        payment.status='paid';payment.save()
        prepare_price_changes(self.sub,self.now);prepare_price_changes(self.sub,self.now)
        self.sub.refresh_from_db();self.assertEqual(self.sub.contracted_price,Decimal('120'))
        payment.refresh_from_db();self.assertEqual(payment.amount,Decimal('100'))

    def test_promotion_end_preserves_addons_and_provider_failure_rolls_back(self):
        self.sub.contracted_price=Decimal('100');self.sub.base_contracted_price=Decimal('80');self.sub.addon_contracted_price=Decimal('20');self.sub.save()
        change=SubscriptionPriceChange.objects.create(subscription=self.sub,new_base_price=100,effective_at=self.now,reason='promotion')
        with patch('billing.module_services._gateway_for',return_value=object()),patch('billing.payment_services.platform_provider') as factory:
            factory.return_value.update_subscription_amount.side_effect=RuntimeError('provider unavailable')
            with self.assertRaises(RuntimeError):prepare_price_changes(self.sub,self.now)
        self.sub.refresh_from_db();change.refresh_from_db()
        self.assertEqual(self.sub.contracted_price,Decimal('100'));self.assertEqual(change.status,'pending')
        prepare_price_changes(self.sub,self.now);self.sub.refresh_from_db()
        self.assertEqual(self.sub.contracted_price,Decimal('120'));self.assertEqual(self.sub.addon_contracted_price,Decimal('20'))

    def test_module_quote_shows_full_cycle_total_without_activating(self):
        module=Module.objects.create(name='Extra',slug='commercial-extra',addon_monthly_price=15,addon_sellable=True)
        self.client.force_login(self.owner)
        response=self.client.get('/billing/modulos/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'115,00')
        self.assertFalse(TenantModuleAddon.objects.filter(tenant=self.tenant,module=module).exists())

    def test_per_unit_catalog_edit_preserves_the_contracted_unit_rate(self):
        module=Module.objects.create(name='Unidades',slug='multiunit',addon_monthly_price=10,per_unit_billing=True)
        addon=TenantModuleAddon.objects.create(tenant=self.tenant,module=module,monthly_price=10,status='active',billing_mode='merged_subscription')
        module.addon_monthly_price=20;module.save();addon.refresh_from_db()
        self.assertEqual(addon.pricing_components,['10.00'])

    def test_signup_records_promotion_and_regular_renewal_amount(self):
        self.plan.promotion_price=Decimal('79.90');self.plan.promotion_months=3;self.plan.save()
        response=self.client.post('/cadastro/',{'plan':self.plan.pk,'billing_cycle':'monthly','payment_method':'pix',
            'business_name':'Empresa promocional','postal_code':'55818255','category':'barbearia',
            'owner_name':'Gestor','email':'promotion@example.test','phone':'81999990042',
            'password':'SyntheticTest2026!','password_confirm':'SyntheticTest2026!'})
        self.assertEqual(response.status_code,302)
        sub=Subscription.objects.get(tenant__email='promotion@example.test')
        self.assertEqual(sub.contracted_price,Decimal('79.90'))
        self.assertEqual(sub.regular_base_price,Decimal('100'))
        self.assertGreater(sub.promotion_ends_at,sub.trial_ends_at)
        self.assertEqual(sub.price_changes.get().new_base_price,Decimal('100'))

    def test_signed_stale_offer_is_rejected_before_account_creation(self):
        from django.core import signing
        from .commercial_pricing import quote_payload
        quote=signing.dumps(quote_payload(self.plan,'monthly'),salt='subscription-offer')
        self.plan.monthly_price=Decimal('120');self.plan.save()
        response=self.client.post('/cadastro/',{'plan':self.plan.pk,'price_quote':quote,'billing_cycle':'monthly',
            'business_name':'Cotação antiga','postal_code':'55818255','category':'barbearia','owner_name':'Gestor',
            'email':'old-quote@example.test','password':'SyntheticTest2026!','password_confirm':'SyntheticTest2026!'})
        self.assertContains(response,'As condições do plano mudaram')
        self.assertFalse(Tenant.objects.filter(email='old-quote@example.test').exists())

    def test_trial_first_payment_keeps_quote_before_announced_renewal(self):
        self.sub.status='trial';self.sub.trial_ends_at=self.now+timedelta(days=7)
        self.sub.next_billing_at=self.sub.trial_ends_at;self.sub.save()
        self.plan.monthly_price=Decimal('120');self.plan.save()
        schedule_plan_renewals(self.plan,self.owner,self.now)
        change=self.sub.price_changes.get()
        from dateutil.relativedelta import relativedelta
        self.assertEqual(change.effective_at,self.sub.trial_ends_at+relativedelta(months=1))
        prepare_price_changes(self.sub,self.now);self.sub.refresh_from_db()
        self.assertEqual(self.sub.contracted_price,Decimal('100'))

    def test_expired_promotion_for_card_uses_paid_cycle_coverage(self):
        self.sub.base_contracted_price=Decimal('80');self.sub.contracted_price=Decimal('80')
        self.sub.next_billing_at=self.now-timedelta(days=60);self.sub.provider_subscription_id='card-reference';self.sub.save()
        Payment.objects.create(tenant=self.tenant,subscription=self.sub,purpose='subscription',status='paid',amount=80,paid_at=self.now)
        change=SubscriptionPriceChange.objects.create(subscription=self.sub,new_base_price=100,effective_at=self.now+timedelta(days=25),reason='promotion')
        with patch('billing.module_services._gateway_for',return_value=object()),patch('billing.payment_services.platform_provider') as provider:
            prepare_price_changes(self.sub,self.now)
            provider.return_value.update_subscription_amount.assert_called_once_with('card-reference',Decimal('100'))
        change.refresh_from_db();self.assertEqual(change.status,'applied')

    def test_local_failure_compensates_provider_amount(self):
        self.sub.provider_subscription_id='card-ref';self.sub.save()
        change=SubscriptionPriceChange.objects.create(subscription=self.sub,new_base_price=120,effective_at=self.now,reason='catalog')
        with patch('billing.module_services._gateway_for',return_value=object()),patch('billing.payment_services.platform_provider') as provider,patch('core.audit.append_audit',side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):prepare_price_changes(self.sub,self.now)
            self.assertEqual(provider.return_value.update_subscription_amount.call_count,2)
            provider.return_value.update_subscription_amount.assert_called_with('card-ref',Decimal('100'))
        self.sub.refresh_from_db();change.refresh_from_db()
        self.assertEqual(self.sub.contracted_price,Decimal('100'));self.assertEqual(change.status,'pending')
