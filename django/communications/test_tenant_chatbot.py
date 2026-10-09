import json
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError
from accounts.models import User
from tenants.models import Tenant
from scheduling.models import Service,Customer
from core.crypto import encrypt_text,decrypt_json
from .models import ChatbotFlow,MasterWhatsAppFlow,WhatsAppConversation,WhatsAppMessage,TenantWhatsAppConnection,TenantFlowDelivery
from .tenant_flow import company_graph,company_ai,validate_company_graph
from .tenant_graph_services import advance,deliver

class TenantChatbotTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name='Empresa A',slug='empresa-a',status='active',public_enabled=True)
        self.other=Tenant.objects.create(name='Empresa B',slug='empresa-b',status='active')
        self.owner=User.objects.create_user(email='a@example.test',password='Test123!',role='owner',tenant=self.tenant)
        self.client.force_login(self.owner)
        self.flow=ChatbotFlow.objects.create(tenant=self.tenant,enabled=True,graph=company_graph())
        TenantWhatsAppConnection.objects.create(tenant=self.tenant,enabled=True)
        self.conversation=WhatsAppConversation.objects.create(tenant=self.tenant,wa_id='5581999999999',last_message_at=timezone.now(),context={'_chatbot_transport':'qr','_chatbot_jid':'5581999999999@s.whatsapp.net'})
    def test_builder_renders_without_secret_and_saves_only_own_flow(self):
        MasterWhatsAppFlow.objects.create(pk=1,ai_enabled=True,ai_model='test-model',ai_key_encrypted=encrypt_text('never-render-secret'))
        response=self.client.get(reverse('tenant-whatsapp-chatbot'))
        self.assertContains(response,'test-model');self.assertNotContains(response,'never-render-secret');self.assertNotContains(response,'name="ai_key"')
        data={'tenant_id':self.other.pk,'enabled':'on','ai_enabled':'on','greeting':'Oi','fallback':'Repita','handoff':'Equipe','graph_json':json.dumps(company_graph())}
        self.assertEqual(self.client.post(reverse('tenant-whatsapp-chatbot'),data).status_code,302)
        self.assertFalse(ChatbotFlow.objects.filter(tenant=self.other).exists())
    def test_unauthorized_role(self):
        self.owner.role='professional';self.owner.save(update_fields=['role'])
        self.assertEqual(self.client.get(reverse('tenant-whatsapp-chatbot')).status_code,403)
    def test_ai_uses_only_own_catalog_and_central_key(self):
        Service.objects.create(tenant=self.tenant,name='Corte A',price=30,duration_minutes=30)
        Service.objects.create(tenant=self.other,name='SEGREDO B',price=90,duration_minutes=45)
        MasterWhatsAppFlow.objects.create(pk=1,ai_enabled=True,ai_model='test-model',ai_key_encrypted=encrypt_text('central-key'))
        with patch('communications.master_integrations.request_json',return_value={'choices':[{'message':{'content':'{"in_scope":true,"fact_ids":["servicos"],"answer":"inventado"}'}}]}) as api:
            result=company_ai(self.tenant,self.flow,{}, {'nome':'CLIENTE PRIVADO'},'Preço?')
        self.assertIn('Corte A',result);self.assertNotIn('inventado',result)
        payload=json.dumps(api.call_args.args[2]);self.assertNotIn('SEGREDO B',payload);self.assertNotIn('CLIENTE PRIVADO',payload)
        self.assertEqual(api.call_args.args[3],'central-key')
    def test_rejects_external_integrations(self):
        graph=company_graph();graph['nodes'][4]['type']='legacy'
        with self.assertRaises(ValidationError):validate_company_graph(graph)
    @patch('communications.master_integrations.request_json')
    def test_simulator_has_no_paid_calls_or_customer_writes(self,api):
        response=self.client.post(reverse('tenant-whatsapp-simulate'),json.dumps({'graph':company_graph(),'state':'ia','incoming':'Dúvida','context':{'variables':{}}}),content_type='application/json')
        self.assertEqual(response.status_code,200);api.assert_not_called();self.assertFalse(Customer.objects.exists())
        bad=self.client.post(reverse('tenant-whatsapp-simulate'),json.dumps({'graph':company_graph(),'context':{'variables':{'telefone':[]}}}),content_type='application/json')
        self.assertEqual(bad.status_code,400)
    def send(self,text):
        message=WhatsAppMessage.objects.create(tenant=self.tenant,conversation=self.conversation,direction='in',body=text,chatbot_transport='qr')
        advance(self.conversation.pk,message.pk);self.conversation.refresh_from_db();return message
    def test_triage_creates_company_customer_and_deduplicates(self):
        first=self.send('Oi');count=TenantFlowDelivery.objects.count();advance(self.conversation.pk,first.pk)
        self.assertEqual(TenantFlowDelivery.objects.count(),count)
        self.send('3');self.send('Quero cortar cabelo');self.send('Ana');self.send('Unidade central')
        self.assertEqual(self.conversation.status,'waiting_human')
        self.assertEqual(self.conversation.customer.tenant_id,self.tenant.pk)
        self.assertEqual(decrypt_json(self.conversation.flow_context_encrypted)['variables']['necessidade'],'Quero cortar cabelo')
        self.assertNotIn('Ana',self.conversation.flow_context_encrypted)
        from commercial.models import Lead
        self.assertFalse(Lead.objects.exists())
    def test_qr_delivery_uses_own_connection_with_idempotency(self):
        self.send('Oi');row=TenantFlowDelivery.objects.filter(status='queued').first()
        with patch('communications.tenant_whatsapp.gateway',return_value={'id':'own-provider-id'}) as gateway:
            deliver(row.pk);deliver(row.pk)
        gateway.assert_called_once();self.assertEqual(gateway.call_args.args[0],self.tenant)
        self.assertEqual(gateway.call_args.args[3]['idempotencyKey'],row.event_key)
    def test_human_cancels_queue_and_bot_resets(self):
        self.send('Oi')
        self.assertEqual(self.client.post(reverse('communications-conversation-action',args=[self.conversation.pk]),{'action':'human'}).status_code,302)
        self.assertFalse(TenantFlowDelivery.objects.filter(status='queued').exists())
        self.client.post(reverse('communications-conversation-action',args=[self.conversation.pk]),{'action':'bot'})
        self.conversation.refresh_from_db();self.assertEqual(self.conversation.flow_context_encrypted,'')
    def test_paused_company_does_not_generate_replies(self):
        self.tenant.status='suspended';self.tenant.save(update_fields=['status'])
        self.send('Oi');self.assertFalse(TenantFlowDelivery.objects.exists())
    def test_out_of_order_message_waits(self):
        first=WhatsAppMessage.objects.create(tenant=self.tenant,conversation=self.conversation,direction='in',body='Oi')
        second=WhatsAppMessage.objects.create(tenant=self.tenant,conversation=self.conversation,direction='in',body='3')
        advance(self.conversation.pk,second.pk);self.assertFalse(TenantFlowDelivery.objects.exists())
        advance(self.conversation.pk,first.pk);advance(self.conversation.pk,second.pk)
        second.refresh_from_db();self.assertIsNotNone(second.flow_processed_at)
    def test_manual_reply_uses_company_qr_not_global_cloud(self):
        with patch('communications.tenant_whatsapp.gateway',return_value={'id':'human-own-id'}) as qr,patch('communications.portal.send_text') as cloud:
            response=self.client.post(reverse('communications-conversation-action',args=[self.conversation.pk]),{'action':'reply','body':'Olá Ana'})
        self.assertEqual(response.status_code,302);cloud.assert_not_called();qr.assert_called_once()
        self.assertEqual(qr.call_args.args[0],self.tenant)
        self.conversation.refresh_from_db();self.assertEqual(self.conversation.status,'human')
    def test_signed_qr_callback_enqueues_once(self):
        from django.test import override_settings
        with override_settings(MASTER_WHATSAPP_GATEWAY_TOKEN='gateway-test'),patch('communications.tenant_graph_services.enqueue') as queue:
            payload={'tenant_id':self.tenant.pk,'from':'5581999999999@s.whatsapp.net','id':'incoming-once','text':'Oi'}
            with self.captureOnCommitCallbacks(execute=True):
                response=self.client.post('/webhooks/tenant-whatsapp/',json.dumps(payload),content_type='application/json',HTTP_AUTHORIZATION='Bearer gateway-test')
            self.assertEqual(response.status_code,200)
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post('/webhooks/tenant-whatsapp/',json.dumps(payload),content_type='application/json',HTTP_AUTHORIZATION='Bearer gateway-test')
            queue.assert_called_once()
    def test_flow_change_during_wait_requires_human(self):
        from datetime import timedelta
        self.conversation.flow_wake_at=timezone.now()-timedelta(seconds=1)
        self.conversation.flow_revision='older-revision';self.conversation.save()
        advance(self.conversation.pk,resume=True);self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.status,'waiting_human');self.assertIsNone(self.conversation.flow_wake_at)
    def test_disabled_flow_does_not_answer(self):
        self.flow.enabled=False;self.flow.save(update_fields=['enabled'])
        self.send('Oi');self.assertFalse(TenantFlowDelivery.objects.exists())

    def test_blank_and_preconfiguration_messages_do_not_trigger_bot(self):
        message=WhatsAppMessage.objects.create(tenant=self.tenant,conversation=self.conversation,direction='in',body='')
        advance(self.conversation.pk,message.pk)
        message.refresh_from_db();self.assertIsNotNone(message.flow_processed_at)
        older=WhatsAppMessage.objects.create(tenant=self.tenant,conversation=self.conversation,direction='in',body='Oi')
        self.flow.save()
        advance(self.conversation.pk,older.pk)
        self.assertFalse(TenantFlowDelivery.objects.exists())
