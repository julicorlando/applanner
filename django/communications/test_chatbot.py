import hashlib
import hmac
import json
from unittest.mock import patch

from django.test import TestCase,SimpleTestCase,override_settings
from django.urls import reverse

from accounts.models import User
from tenants.models import Tenant
from .chatbot import next_reply
from .models import ChatbotFlow,WhatsAppConversation


class ChatbotRoutingTests(SimpleTestCase):
    def test_handoff_overrides_rules_and_bot_stops_replying(self):
        flow=ChatbotFlow(greeting="Olá",fallback="Encaminhando",handoff="Um atendente irá ajudar",rules=[{"keywords":["agenda"],"reply":"Abra a agenda"}])
        conversation=WhatsAppConversation(status=WhatsAppConversation.Status.BOT)
        self.assertEqual(next_reply(flow,conversation,"Quero agenda"),("Abra a agenda","bot"))
        self.assertEqual(next_reply(flow,conversation,"Quero um atendente e agenda"),("Um atendente irá ajudar","waiting_human"))
        conversation.status=WhatsAppConversation.Status.HUMAN
        self.assertEqual(next_reply(flow,conversation,"agenda"),(None,"human"))


class MasterChatbotTests(TestCase):
    def test_only_master_can_edit_and_activation_requires_provider(self):
        tenant=Tenant.objects.create(name="Corte",slug="corte",category="Barbearia")
        user=User.objects.create_user(email="owner@example.com",password="StrongPassword2026!",tenant=tenant,role="owner")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("master-chatbot")).status_code,403)
        self.client.force_login(User.objects.create_superuser(email="master@example.com",password="StrongPassword2026!"))
        data={"tenant":tenant.pk,"enabled":"on","greeting":"Olá","fallback":"Encaminhando","handoff":"Atendente","rules_text":"agenda | Veja os horários"}
        self.assertEqual(self.client.post(reverse("master-chatbot"),data).status_code,200)
        self.assertFalse(ChatbotFlow.objects.filter(tenant=tenant).exists())
        data.pop("enabled")
        self.assertEqual(self.client.post(reverse("master-chatbot"),data).status_code,302)
        self.assertEqual(ChatbotFlow.objects.get(tenant=tenant).rules[0]["keywords"],["agenda"])


class ChatbotWebhookTests(TestCase):
    @override_settings(WHATSAPP_APP_SECRET="webhook-test-secret",WHATSAPP_PHONE_NUMBER_ID="number-123")
    def test_signed_webhook_replies_once_then_transfers_to_human(self):
        tenant=Tenant.objects.create(name="Corte",slug="whatsapp-corte",metadata={"whatsapp_phone_number_id":"number-123"})
        ChatbotFlow.objects.create(tenant=tenant,enabled=True,greeting="Olá",fallback="Encaminhando",
                                   handoff="Chamando atendente",rules=[{"keywords":["agenda"],"reply":"Veja horários"}])

        def deliver(message_id,body):
            data=json.dumps({"entry":[{"changes":[{"value":{
                "metadata":{"phone_number_id":"number-123"},
                "messages":[{"id":message_id,"from":"5581999999999","type":"text","text":{"body":body}}],
            }}]}]}).encode()
            signature="sha256="+hmac.new(b"webhook-test-secret",data,hashlib.sha256).hexdigest()
            return self.client.post(reverse("whatsapp-webhook"),data=data,content_type="application/json",
                                    HTTP_X_HUB_SIGNATURE_256=signature)

        with patch("communications.views.send_chatbot_reply.delay") as enqueue:
            self.assertEqual(deliver("msg-1","Quero ver a agenda").status_code,200)
            self.assertEqual(deliver("msg-1","Quero ver a agenda").status_code,200)
            enqueue.assert_called_once_with(WhatsAppConversation.objects.get(tenant=tenant).pk,"Veja horários")
            self.assertEqual(deliver("msg-2","Quero falar com atendente").status_code,200)
            self.assertEqual(deliver("msg-3","agenda").status_code,200)
            self.assertEqual(enqueue.call_count,2)
            conversation=WhatsAppConversation.objects.get(tenant=tenant)
            self.assertEqual(conversation.status,WhatsAppConversation.Status.WAITING_HUMAN)
