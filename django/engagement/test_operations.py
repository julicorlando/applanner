from django.test import TestCase
from django.utils import timezone
from accounts.models import User
from engagement.models import LoyaltyReferral,ServicePackage,TenantLoyaltySettings
from engagement.services import complete_referral,create_membership,purchase_package
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

    def test_referral_credits_points(self):
        TenantLoyaltySettings.objects.create(tenant=self.tenant,enabled=True,referral_points=30)
        referral=LoyaltyReferral.objects.create(tenant=self.tenant,referrer=self.a,referred=self.b,reward_points=30)
        complete_referral(referral=referral,user=self.user)
        self.assertEqual(self.a.loyalty_accounts.get(tenant=self.tenant).points,30)
