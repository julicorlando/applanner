from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from accounts.permissions import has_capability
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


class CommercialPortalTests(TestCase):
    def setUp(self):
        self.sales=User.objects.create_user(
            email="sales-portal@example.com",password="StrongPassword!123",role="commercial"
        )
        CommercialProfile.objects.create(
            user=self.sales,commission_percent=Decimal("8"),max_discount_percent=Decimal("5")
        )
        self.plan=Plan.objects.create(
            name="Plano Portal",slug="portal-plan",monthly_price=Decimal("100")
        )
        self.client.force_login(self.sales)

    def test_proposal_captures_plan_snapshot(self):
        from billing.models import Module,PlanModule
        module=Module.objects.create(slug="finance-test",name="Financeiro teste",active=True)
        PlanModule.objects.create(plan=self.plan,module=module,enabled=True)
        response=self.client.post("/commercial/propostas/nova/",{
            "plan":self.plan.pk,
            "title":"Oferta",
            "customer_name":"Cliente",
            "customer_email":"cliente@example.com",
            "discount_percent":"2",
            "final_price":"98",
            "notes":"Teste",
            "expires_at":"",
        })
        self.assertEqual(response.status_code,302)
        proposal=Proposal.objects.get(title="Oferta")
        self.assertEqual(proposal.base_plan,self.plan)
        self.assertIn("Financeiro teste",proposal.modules)
        self.assertEqual(response.url,f"/commercial/propostas/{proposal.pk}/")


class CommercialSupportParityTests(TestCase):
    def test_support_access_respects_legacy_profile_flag(self):
        user=User.objects.create_user(
            email="commercial-support@example.test",
            password="StrongPassword123!",
            role="commercial",
        )
        profile=CommercialProfile.objects.create(
            user=user,commission_percent=Decimal("10"),
            max_discount_percent=Decimal("5"),support_enabled=False,
        )
        self.assertFalse(has_capability(user,"support.manage"))
        profile.support_enabled=True
        profile.save(update_fields=["support_enabled"])
        self.assertTrue(has_capability(user,"support.manage"))
