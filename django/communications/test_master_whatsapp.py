import json
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase,override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import User
from tenants.models import Tenant
from .models import MasterWhatsAppConversation,MasterWhatsAppMessage,MasterWhatsAppFlow


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

    def test_delivery_and_read_receipts_are_authenticated_and_match_recipient(self):
        row=MasterWhatsAppConversation.objects.create(wa_id="5581999999999@s.whatsapp.net",last_message_at=timezone.now(),contact_name="Empresa Nova")
        self.client.force_login(self.master)
        url=reverse("master-whatsapp-receive")
        event={"event":"receipt","to":row.wa_id,"id":"delivery-id","status":"read"}
        self.assertEqual(self.client.post(url,data=json.dumps(event),content_type="application/json").status_code,403)
        self.assertEqual(self.client.post(url,data=json.dumps(event),content_type="application/json",HTTP_AUTHORIZATION="Bearer test-gateway-secret").status_code,200)
        with patch("communications.master_whatsapp._gateway",return_value={"id":"delivery-id","to":row.wa_id}):
            self.client.post(reverse("master-whatsapp-conversation",args=[row.pk]),{"action":"reply","body":"Olá"})
        message=row.messages.get()
        self.assertEqual(message.delivery_status,"read")
        self.assertIsNotNone(message.read_at)
        self.assertContains(self.client.get(reverse("master-whatsapp-conversation",args=[row.pk])),"Empresa Nova leu às")
        different={"event":"receipt","to":"5581888888888@s.whatsapp.net","id":"delivery-id","status":"delivered"}
        self.client.post(url,data=json.dumps(different),content_type="application/json",HTTP_AUTHORIZATION="Bearer test-gateway-secret")
        event["status"]="delivered"
        self.client.post(url,data=json.dumps(event),content_type="application/json",HTTP_AUTHORIZATION="Bearer test-gateway-secret")
        message.refresh_from_db()
        self.assertEqual(message.delivery_status,"read")
        self.assertIn("Empresa Nova leu às",self.client.get(reverse("master-whatsapp-messages",args=[row.pk])).json()["messages"][0]["receipt"])

    def test_flow_editor_and_automated_handoff_are_master_only(self):
        from .master_whatsapp_flow import process_master_automation
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("master-whatsapp-flow")).status_code,403)
        self.client.force_login(self.master)
        editor=reverse("master-whatsapp-flow")
        self.assertContains(self.client.get(editor),"Prévia das etapas")
        self.assertEqual(self.client.post(editor,{
            "enabled":"on","greeting":"Olá empresa","fallback":"Pode explicar?",
            "handoff":"Chamando uma pessoa",
            "steps_text":"inicio | plano;valor | Qual o segmento? | segmento | não\nsegmento | barbearia | Vamos conversar | | sim",
        }).status_code,302)
        flow=MasterWhatsAppFlow.objects.get(pk=1)
        self.assertEqual(len(flow.steps),2)
        row=MasterWhatsAppConversation.objects.create(wa_id="5581999999999@s.whatsapp.net",last_message_at=timezone.now())
        with patch("communications.master_whatsapp._gateway",side_effect=[
            {"id":"bot-1","to":row.wa_id},{"id":"bot-2","to":row.wa_id},{"id":"bot-3","to":row.wa_id},
        ]) as gateway:
            for index,content in enumerate(("Oi","Quero saber o valor do plano","Somos barbearia"),start=1):
                incoming=MasterWhatsAppMessage.objects.create(
                    conversation=row,provider_message_id=f"incoming-{index}",direction="in",body=content,
                )
                process_master_automation(incoming.pk)
                process_master_automation(incoming.pk)
        self.assertEqual(gateway.call_count,3)
        row.refresh_from_db()
        self.assertTrue(row.human_handoff)
        self.assertEqual(row.messages.filter(direction="out").count(),3)
        self.assertEqual(self.client.post(reverse("master-whatsapp-conversation",args=[row.pk]),{"action":"handoff","enabled":"0"}).status_code,302)
        row.refresh_from_db()
        self.assertFalse(row.human_handoff)

    def test_master_sends_valid_image_and_media_stays_private(self):
        row=MasterWhatsAppConversation.objects.create(wa_id="5581999999999@s.whatsapp.net",last_message_at=timezone.now())
        content=BytesIO()
        Image.new("RGB",(8,8),"white").save(content,format="PNG")
        with TemporaryDirectory() as temp,override_settings(MEDIA_ROOT=temp):
            self.client.force_login(self.master)
            with patch("communications.master_whatsapp._gateway",return_value={"id":"image-1","to":row.wa_id}) as gateway:
                response=self.client.post(reverse("master-whatsapp-conversation",args=[row.pk]),{
                    "action":"reply","body":"Veja a imagem","attachment":SimpleUploadedFile("foto.png",content.getvalue(),content_type="image/png"),
                })
            self.assertEqual(response.status_code,302)
            self.assertEqual(gateway.call_args.args[:2],("POST","/send"))
            self.assertEqual(gateway.call_args.args[2]["file"]["mime"],"image/png")
            sent=row.messages.get()
            self.assertEqual(self.client.get(reverse("master-whatsapp-attachment",args=[sent.pk])).status_code,200)
            self.client.force_login(self.user)
            self.assertEqual(self.client.get(reverse("master-whatsapp-attachment",args=[sent.pk])).status_code,403)
            self.client.force_login(self.master)
            with patch("communications.master_whatsapp._gateway") as not_sent:
                bad=self.client.post(reverse("master-whatsapp-conversation",args=[row.pk]),{
                    "action":"reply","body":"", "attachment":SimpleUploadedFile("fake.png",b"not an image"),
                },follow=True)
            self.assertContains(bad,"imagem PNG, JPG ou WebP válida")
            not_sent.assert_not_called()
