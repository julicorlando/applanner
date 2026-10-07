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

    def test_manual_prospect_and_duplicate_prevention(self):
        data={"name":"Barbearia Central","phone":"5581999999999","email":"novo@example.com",
              "business_type":"Barbearia","estimated_value":"200","source":"prospeccao_manual",
              "notes":"Contato inicial","next_contact_at":"","consent_granted":"on"}
        response=self.client.post("/commercial/leads/novo/",data)
        self.assertEqual(response.status_code,302)
        lead=Lead.objects.get(email="novo@example.com")
        self.assertEqual(lead.assigned_to,self.sales)
        self.assertTrue(lead.history.filter(action="created").exists())
        self.assertEqual(self.client.post("/commercial/leads/novo/",data).status_code,200)
        self.assertEqual(Lead.objects.filter(email="novo@example.com").count(),1)
        self.assertContains(self.client.get("/commercial/?q=Central"),"Barbearia Central")

    def test_commercial_role_required_for_new_lead(self):
        other=User.objects.create_user(email="visitor@example.com",password="StrongPassword!123")
        self.client.force_login(other)
        self.assertEqual(self.client.get("/commercial/leads/novo/").status_code,403)

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


class MasterLeadDeleteTests(TestCase):
    def setUp(self):
        self.master=User.objects.create_superuser(email='master-delete@example.com',password='StrongPassword!123')
        self.lead=Lead.objects.create(name='Lead QA',phone='5581999999999',email='lead-delete@example.com',business_type='Barbearia')
        self.url=f'/commercial/leads/{self.lead.pk}/excluir/'
        self.client.force_login(self.master)

    def test_get_and_unconfirmed_post_do_not_delete(self):
        self.assertContains(self.client.get(self.url),'Excluir lead definitivamente')
        self.assertEqual(self.client.post(self.url,{}).status_code,302)
        self.assertTrue(Lead.objects.filter(pk=self.lead.pk).exists())

    def test_commercial_cannot_delete_even_assigned_lead(self):
        sales=User.objects.create_user(email='sales-delete@example.com',password='StrongPassword!123',role='commercial')
        CommercialProfile.objects.create(user=sales)
        self.lead.assigned_to=sales;self.lead.save()
        self.client.force_login(sales)
        self.assertEqual(self.client.get(self.url).status_code,403)
        self.assertEqual(self.client.post(self.url,{'confirm':'delete'}).status_code,403)
        self.assertTrue(Lead.objects.filter(pk=self.lead.pk).exists())

    def test_delete_preserves_messages_and_stops_pending_intake(self):
        from communications.models import MasterWhatsAppConversation,MasterWhatsAppMessage,MasterFlowDelivery
        from core.models import AuditLog
        from core.crypto import encrypt_json
        from django.utils import timezone
        conversation=MasterWhatsAppConversation.objects.create(wa_id='delete-test',sales_lead=self.lead,last_message_at=timezone.now(),flow_wait_kind='commercial',flow_context_encrypted=encrypt_json({'variables':{'nome':'Lead QA'}}))
        message=MasterWhatsAppMessage.objects.create(conversation=conversation,provider_message_id='delete-msg',direction='in',body='Preserve esta mensagem')
        pending=MasterFlowDelivery.objects.create(conversation=conversation,event_key='delete-delivery',body='Próximo dado')
        response=self.client.post(self.url,{'confirm':'delete'})
        self.assertEqual(response.status_code,302)
        self.assertFalse(Lead.objects.filter(pk=self.lead.pk).exists())
        self.assertTrue(MasterWhatsAppMessage.objects.filter(pk=message.pk).exists())
        conversation.refresh_from_db();pending.refresh_from_db()
        self.assertIsNone(conversation.sales_lead_id)
        self.assertTrue(conversation.human_handoff)
        self.assertEqual(conversation.flow_context_encrypted,'')
        self.assertEqual(pending.status,'cancelled')
        self.assertTrue(AuditLog.objects.filter(action='commercial_lead_deleted',entity_id=self.lead.pk).exists())

    def test_csrf_required(self):
        from django.test import Client
        client=Client(enforce_csrf_checks=True);client.force_login(self.master)
        self.assertEqual(client.post(self.url,{'confirm':'delete'}).status_code,403)
        self.assertTrue(Lead.objects.filter(pk=self.lead.pk).exists())
