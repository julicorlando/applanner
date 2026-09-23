from datetime import date

from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch
from types import SimpleNamespace
from accounts.models import User
from engagement.models import CustomerMembership,LoyaltyReferral,ServicePackage,TenantLoyaltySettings
from engagement.services import advance_months,complete_referral,create_membership,purchase_package
from engagement.tasks import bill_due_memberships
from finance.models import FinancialTransaction
from scheduling.models import Customer,Service
from tenants.models import Tenant


class EngagementOperationsTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Rel",slug="rel-test")
        self.user=User.objects.create_user(email="rel@example.com",password="StrongPassword123!",tenant=self.tenant)
        self.a=Customer.objects.create(tenant=self.tenant,name="A")
        self.b=Customer.objects.create(tenant=self.tenant,name="B")
        self.package=ServicePackage.objects.create(tenant=self.tenant,name="Mensal",price="100",validity_days=30,active=True,recurring=True)

    def test_purchase_and_local_membership(self):
        p=purchase_package(tenant=self.tenant,customer=self.a,package=self.package)
        self.assertEqual(p.status,"active")
        m=create_membership(tenant=self.tenant,customer=self.a,package=self.package,cycle="monthly")
        self.assertEqual(m.status,"active")

    def test_monthly_due_date_uses_calendar_months(self):
        self.assertEqual(advance_months(date(2027,1,31),1),date(2027,2,28))
        self.assertEqual(advance_months(date(2027,10,31),3),date(2028,1,31))

    @patch("billing.payment_services.create_tenant_recurring_subscription")
    def test_online_membership_persists_provider_details_and_avoids_manual_invoice(self,create_remote):
        create_remote.return_value=SimpleNamespace(
            status="pending",provider_subscription_id="provider-123",
            checkout_url="https://www.mercadopago.com.br/checkout/test",
        )
        membership=create_membership(
            tenant=self.tenant,customer=self.a,package=self.package,cycle="monthly",
            online_payment=True,payer_email="customer@example.test",back_url="https://example.test/",
        )
        membership.refresh_from_db()
        self.assertEqual(membership.billing_mode,"provider")
        self.assertEqual(membership.provider_status,"pending")
        self.assertEqual(membership.provider_subscription_id,"provider-123")
        self.assertTrue(membership.provider_checkout_url.startswith("https://"))
        CustomerMembership.objects.filter(pk=membership.pk).update(next_due_at=timezone.localdate())
        self.assertEqual(bill_due_memberships(),0)
        self.assertFalse(FinancialTransaction.objects.filter(source_id=membership.pk,source_type="customer_membership").exists())

    def test_referral_credits_points(self):
        TenantLoyaltySettings.objects.create(tenant=self.tenant,enabled=True,referral_points=30)
        referral=LoyaltyReferral.objects.create(tenant=self.tenant,referrer=self.a,referred=self.b,reward_points=30)
        complete_referral(referral=referral,user=self.user)
        self.assertEqual(self.a.loyalty_accounts.get(tenant=self.tenant).points,30)
