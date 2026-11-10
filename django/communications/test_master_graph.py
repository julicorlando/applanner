from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase
from django.core.exceptions import ValidationError
from .master_graph import validate_graph
from .master_runtime import run_graph,expand_json
from .master_integrations import public_endpoint


def node(key,kind,config=None,outputs=None):
    return {'id':key,'type':kind,'config':config or {},'outputs':outputs or {}}


def graph(*nodes):
    return {'version':2,'start':'start','nodes':[node('start','start',{'text':'Olá'},{'next':nodes[0]['id']}),*nodes]}


class MasterGraphTests(SimpleTestCase):
    flow=SimpleNamespace(handoff='Vamos chamar um atendente.',fallback='Tente novamente.')

    def run(self,g,prior=None,incoming='',resume=False):
        # Do not shadow unittest.TestCase.run.
        return run_graph(g,self.flow,prior['state'] if prior else '',prior['context'] if prior else {},prior['waiting'] if prior else '',incoming,resume=resume,simulation=True)

    def test_menu_routes_independent_outputs(self):
        g=validate_graph(graph(node('menu','menu',{'text':'Escolha','options':[{'id':'sales','label':'Planos'},{'id':'help','label':'Suporte'}]},{'sales':'sale','help':'help'}),node('sale','finish',{'text':'Vendas'}),node('help','finish',{'text':'Suporte'})))
        first=self.execute(g)
        self.assertEqual(first['waiting'],'menu')
        self.assertEqual(self.execute(g,first,'2')['messages'],['Suporte'])
        self.assertEqual(self.execute(g,first,'Planos')['messages'],['Vendas'])
        self.assertEqual(self.execute(g,first,'errado')['waiting'],'menu')

    def test_input_validation_variables_and_condition(self):
        g=validate_graph(graph(node('value','input',{'variable':'amount','validation':'number'},{'next':'check'}),node('check','condition',{'variable':'amount','operator':'gt','expected':'10'},{'yes':'yes','no':'no'}),node('yes','finish',{'text':'Valor {{amount}} aprovado'}),node('no','finish',{'text':'Valor baixo'})))
        first=self.execute(g)
        self.assertEqual(self.execute(g,first,'abc')['waiting'],'input')
        self.assertEqual(self.execute(g,first,'12,50')['messages'],['Valor 12.50 aprovado'])
        self.assertEqual(self.execute(g,first,'2')['messages'],['Valor baixo'])

    @patch('communications.master_runtime.call_api')
    @patch('communications.master_runtime.call_ai')
    def test_simulator_never_calls_external_integrations(self,ai,api):
        g=validate_graph(graph(node('api','api',{'integration':'crm','variable':'response'},{'next':'ai'}),node('ai','ai',{'variable':'answer'},{'next':'end'}),node('end','finish',{'text':'{{response.result}}'})))
        result=self.execute(g)
        api.assert_not_called();ai.assert_not_called()
        self.assertIn('Resposta simulada',result['messages'])

    def test_wait_resumes_without_resetting_deadline(self):
        g=validate_graph(graph(node('wait','wait',{'seconds':30},{'next':'end'}),node('end','finish',{'text':'Fim'})))
        first=self.execute(g)
        self.assertEqual(first['wake_seconds'],30)
        self.assertEqual(self.execute(g,first,'oi')['messages'],[])
        self.assertEqual(self.execute(g,first,resume=True)['messages'],['Fim'])

    def test_rejects_automatic_cycles_and_dangling_edges(self):
        for output in ('loop','missing'):
            with self.assertRaises(ValidationError):validate_graph(graph(node('loop','message',{}, {'next':output})))

    def test_rejects_credentials_in_graph(self):
        with self.assertRaises(ValidationError):validate_graph(graph(node('end','finish',{'api_key':'secret'})))

    def test_message_budget_hands_off_without_raising(self):
        nodes=[node('msg'+str(i),'message',{'text':str(i)},{'next':'msg'+str(i+1) if i<9 else 'end'}) for i in range(10)]
        result=self.execute(validate_graph(graph(*nodes,node('end','finish'))))
        self.assertTrue(result['handoff']);self.assertLessEqual(len(result['messages']),8)

    def test_json_substitution_preserves_values(self):
        self.assertEqual(expand_json({'name':'{{name}}'},{'name':'"\\test'}),{'name':'"\\test'})

    def test_rejects_private_urls_even_without_dns(self):
        for url in ('http://example.com','https://127.0.0.1','https://169.254.169.254','https://localhost','https://user:pass@example.com'):
            with self.assertRaises(ValidationError):public_endpoint(url,resolve=False)

    @patch('communications.master_integrations.socket.getaddrinfo',return_value=[(0,0,0,'',('8.8.8.8',443)),(0,0,0,'',('127.0.0.1',443))])
    def test_rejects_mixed_public_private_dns(self,_):
        with self.assertRaises(ValidationError):public_endpoint('https://example.com')

    execute=run
    del run

from django.test import TestCase
from django.utils import timezone
from accounts.models import User
from .models import MasterWhatsAppFlow,MasterWhatsAppConversation,MasterWhatsAppMessage,MasterFlowDelivery
from .master_graph_services import advance_graph,deliver
from django.urls import reverse
import json


class MasterGraphPersistenceTests(TestCase):
    def setUp(self):
        self.flow=MasterWhatsAppFlow.objects.create(pk=1,enabled=True,graph=graph(node('wait','wait',{'seconds':10},{'next':'end'}),node('end','finish',{'text':'Fim'})))
        self.conversation=MasterWhatsAppConversation.objects.create(wa_id='5581999999999@s.whatsapp.net',last_message_at=timezone.now())
        self.message=MasterWhatsAppMessage.objects.create(conversation=self.conversation,direction='in',body='oi',provider_message_id='in-1')

    def test_runner_deduplicates_inbound_and_encrypts_context(self):
        advance_graph(self.conversation.pk,self.message.pk)
        advance_graph(self.conversation.pk,self.message.pk)
        self.assertEqual(MasterFlowDelivery.objects.count(),1)
        self.conversation.refresh_from_db();self.message.refresh_from_db()
        self.assertIsNotNone(self.message.flow_processed_at)
        self.assertIsNotNone(self.conversation.flow_wake_at)
        self.assertNotIn('5581999999999',self.conversation.flow_context_encrypted)

    @patch('communications.master_whatsapp._gateway',return_value={'id':'out-1','to':'5581999999999@s.whatsapp.net'})
    def test_delivery_deduplicates_and_respects_order(self,gateway):
        self.conversation.flow_revision=self.flow.updated_at.isoformat();self.conversation.save()
        first=MasterFlowDelivery.objects.create(conversation=self.conversation,event_key='first',body='Primeiro')
        second=MasterFlowDelivery.objects.create(conversation=self.conversation,event_key='second',body='Segundo')
        deliver(second.pk);gateway.assert_not_called()
        deliver(first.pk);deliver(first.pk)
        self.assertEqual(gateway.call_count,1)
        self.assertEqual(MasterWhatsAppMessage.objects.filter(direction='out').count(),1)

    @patch('communications.master_whatsapp._gateway')
    def test_disabled_flow_cancels_delivery(self,gateway):
        row=MasterFlowDelivery.objects.create(conversation=self.conversation,event_key='pending',body='Olá')
        self.flow.enabled=False;self.flow.save()
        deliver(row.pk);row.refresh_from_db()
        self.assertEqual(row.status,'cancelled');gateway.assert_not_called()

    @patch('communications.master_whatsapp._gateway',side_effect=RuntimeError('secret token'))
    def test_delivery_failure_has_backoff_without_secrets(self,gateway):
        self.conversation.flow_revision=self.flow.updated_at.isoformat();self.conversation.save()
        row=MasterFlowDelivery.objects.create(conversation=self.conversation,event_key='pending',body='Olá')
        deliver(row.pk);row.refresh_from_db()
        self.assertEqual(row.attempts,1);self.assertIsNotNone(row.next_attempt_at)
        self.assertNotIn('secret',row.last_error)

    def test_simulator_is_master_only_and_rejects_nonobject(self):
        url=reverse('master-whatsapp-simulate')
        self.assertEqual(self.client.post(url,data='{}',content_type='application/json').status_code,302)
        user=User.objects.create_superuser(email='graph@example.com',password='Test123456!')
        self.client.force_login(user)
        self.assertEqual(self.client.post(url,data='[]',content_type='application/json').status_code,400)
        response=self.client.post(url,data=json.dumps({'graph':self.flow.graph}),content_type='application/json')
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['waiting'],'wait')
        self.assertFalse(MasterFlowDelivery.objects.exists())
        self.assertContains(self.client.get(reverse('master-whatsapp-flow')),'graph-viewport')
