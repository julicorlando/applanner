import json
from unittest.mock import patch

from django.test import TestCase,override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from tenants.models import Tenant
from .models import MasterWhatsAppConversation,MasterWhatsAppMessage


@override_settings(MASTER_WHATSAPP_GATEWAY_TOKEN="test-gateway-secret",MASTER_WHATSAPP_GATEWAY_URL="http://internal-gateway:3100")
class MasterWhatsAppTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Empresa Teste",slug="empresa-teste")
        self.user=User.objects.create_user(email="user@example.com",password="SenhadeTeste1234!",tenant=self.tenant)
        self.master=User.objects.create_superuser(email="master@example.com",password="SenhadeTeste1234!")

    def test_tenant_user_cannot_read_status_or_conversations(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("master-whatsapp")).status_code,403)
        self.assertEqual(self.client.get(reverse("master-whatsapp-status")).status_code,403)
        self.assertEqual(self.client.post(reverse("master-whatsapp-connect")).status_code,403)

    def test_webhook_rejects_bad_token_and_deduplicates_messages(self):
        url=reverse("master-whatsapp-receive")
        payload={"from":"5581999999999@s.whatsapp.net","id":"message-1","name":"Empresa Nova","text":"Quero conhecer os planos"}
        self.assertEqual(self.client.post(url,data=json.dumps(payload),content_type="application/json").status_code,403)
        for _ in range(2):
            response=self.client.post(url,data=json.dumps(payload),content_type="application/json",HTTP_AUTHORIZATION="Bearer test-gateway-secret")
            self.assertEqual(response.status_code,200)
        self.assertEqual(MasterWhatsAppConversation.objects.count(),1)
        self.assertEqual(MasterWhatsAppMessage.objects.count(),1)
        self.assertIsNone(MasterWhatsAppConversation.objects.get().tenant_id)

    def test_webhook_accepts_lid_contact_for_incoming_message(self):
        payload={"from":"123456789012345@lid","id":"lid-message-1","text":"Minha empresa precisa de ajuda"}
        response=self.client.post(
            reverse("master-whatsapp-receive"),data=json.dumps(payload),content_type="application/json",
            HTTP_AUTHORIZATION="Bearer test-gateway-secret",
        )
        self.assertEqual(response.status_code,200)
        self.assertEqual(MasterWhatsAppConversation.objects.get().wa_id,payload["from"])

    @patch("communications.master_whatsapp._gateway",side_effect=ValueError("Número não encontrado no WhatsApp"))
    def test_failed_send_does_not_claim_delivery_or_save_message(self,_):
        row=MasterWhatsAppConversation.objects.create(wa_id="5581999999999@s.whatsapp.net",last_message_at=timezone.now())
        self.client.force_login(self.master)
        url=reverse("master-whatsapp-conversation",args=[row.pk])
        self.assertEqual(self.client.post(url,{"action":"reply","body":"Olá"}).status_code,302)
        self.assertFalse(row.messages.exists())
        self.assertContains(self.client.get(url),"Número não encontrado")

    @patch("communications.master_whatsapp._gateway",return_value={"id":"sent-1"})
    def test_master_can_link_company_and_reply(self,gateway):
        row=MasterWhatsAppConversation.objects.create(wa_id="5581999999999@s.whatsapp.net",last_message_at=timezone.now())
        self.client.force_login(self.master)
        url=reverse("master-whatsapp-conversation",args=[row.pk])
        self.assertEqual(self.client.post(url,{"action":"assign","tenant_id":self.tenant.pk}).status_code,302)
        self.assertEqual(self.client.post(url,{"action":"reply","body":"Olá, podemos ajudar."}).status_code,302)
        row.refresh_from_db()
        self.assertEqual(row.tenant,self.tenant)
        self.assertEqual(row.messages.get().sent_by,self.master)
        gateway.assert_called_once_with("POST","/send",{"to":row.wa_id,"text":"Olá, podemos ajudar."})

    def test_master_can_see_pairing_page(self):
        self.client.force_login(self.master)
        response=self.client.get(reverse("master-whatsapp"))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"Gerar QR code")
