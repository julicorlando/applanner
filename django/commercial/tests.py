from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from billing.models import Plan

from .models import CommercialProfile,Lead,Proposal
from .services import accept_proposal,claim_lead,project_commission


class CommercialFlowTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user(email="commercial@example.com",password="StrongPassword!123")
        CommercialProfile.objects.create(user=self.user,commission_percent=Decimal("10.00"))
        self.plan=Plan.objects.create(name="Profissional",slug="commercial-pro",monthly_price=Decimal("100.00"))

    def test_claim_and_accept_proposal_snapshot(self):
        lead=Lead.objects.create(
            name="Lead",phone="81999999999",email="lead@example.com",
            business_type="barber",consent_granted=True,
        )
        claim_lead(lead=lead,user=self.user)
        lead.refresh_from_db()
        self.assertEqual(lead.assigned_to,self.user)

        proposal=Proposal.objects.create(
            commercial_user=self.user,plan=self.plan,title="Proposta",
            customer_name="Lead",customer_email="lead@example.com",
            final_price=Decimal("90.00"),public_token="proposal-token-0000000000000001",
        )
        acceptance=accept_proposal(proposal=proposal,ip="127.0.0.1",user_agent="tests")
        self.assertEqual(len(acceptance.document_hash),64)
        self.assertEqual(acceptance.proposal_snapshot["final_price"],"90.00")
