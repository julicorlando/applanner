from decimal import Decimal

from django.test import TestCase

from scheduling.models import Customer
from accounts.models import User
from communications.models import MarketingCampaign,MarketingLead
from tenants.models import Tenant

from .models import LoyaltyAccount,ReferralVisit,TenantLoyaltySettings
from .services import earn_points,issue_reward


class LoyaltyTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Loyalty",slug="loyalty-test",status=Tenant.Status.ACTIVE)
        self.customer=Customer.objects.create(tenant=self.tenant,name="Cliente")
        TenantLoyaltySettings.objects.create(
            tenant=self.tenant,enabled=True,points_per_currency=Decimal("1.00"),
            reward_points=100,reward_value=Decimal("10.00"),
        )

    def test_earning_is_idempotent_by_source(self):
        first=earn_points(
            tenant=self.tenant,customer=self.customer,amount="120.00",
            source_type="appointment",source_id=10,
        )
        second=earn_points(
            tenant=self.tenant,customer=self.customer,amount="120.00",
            source_type="appointment",source_id=10,
        )
        self.assertEqual(first,120)
        self.assertEqual(second,0)
        account=LoyaltyAccount.objects.get(tenant=self.tenant,customer=self.customer)
        self.assertEqual(account.points,120)

    def test_reward_debits_points(self):
        earn_points(
            tenant=self.tenant,customer=self.customer,amount="120.00",
            source_type="sale",source_id=20,
        )
        reward=issue_reward(tenant=self.tenant,customer=self.customer)
        account=LoyaltyAccount.objects.get(tenant=self.tenant,customer=self.customer)
        self.assertEqual(account.points,20)
        self.assertEqual(reward.reward_value,Decimal("10.00"))


class ReferralMigrationParityTests(TestCase):
    def test_referral_visit_preserves_campaign_attribution(self):
        user=User.objects.create_user(
            email="referrer@example.test",password="StrongPassword123!"
        )
        campaign=MarketingCampaign.objects.create(
            subject="Campanha",body="Conteúdo",created_by=user
        )
        lead=MarketingLead.objects.create(
            name="Lead",email="lead-referral@example.test",source="campaign"
        )
        visit=ReferralVisit.objects.create(
            referrer_user=user,campaign=campaign,lead=lead,
            visit_token_hash="a"*64,clicked_at="2026-09-23T10:00:00Z",
        )
        self.assertEqual(visit.campaign,campaign)
        self.assertEqual(visit.lead,lead)
