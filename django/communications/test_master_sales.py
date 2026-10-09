from django.test import TestCase
from django.utils import timezone
from billing.models import Plan
from commercial.models import Lead
from core.crypto import decrypt_json
from .models import MasterWhatsAppConversation,MasterWhatsAppFlow,MasterWhatsAppMessage
from .master_sales import commercial_graph,plans_text,answer_question
from .master_graph import validate_graph
from .master_graph_services import advance_graph
from .master_runtime import run_graph


class MasterSalesTests(TestCase):
    def setUp(self):
        self.flow,_=MasterWhatsAppFlow.objects.get_or_create(pk=1)
        self.flow.enabled=True;self.flow.graph=commercial_graph();self.flow.save()
        self.conversation=MasterWhatsAppConversation.objects.create(wa_id='5581999999999@s.whatsapp.net',last_message_at=timezone.now())
        self.sequence=0

    def send(self,text):
        self.sequence+=1
        m=MasterWhatsAppMessage.objects.create(conversation=self.conversation,direction='in',body=text,provider_message_id='sales-'+str(self.sequence))
        advance_graph(self.conversation.pk,m.pk)
        self.conversation.refresh_from_db()
        return decrypt_json(self.conversation.flow_context_encrypted)['variables']

    def test_complete_sales_journey_progressively_saves_one_lead(self):
        validate_graph(self.flow.graph)
        self.send('Olá');self.send('1');self.send('Júlio')
        self.assertEqual(Lead.objects.filter(source='whatsapp_master_chatbot').count(),1)
        self.send('Barbearia Orlando');self.send('Barbearia')
        self.send('email errado')
        self.assertEqual(Lead.objects.get().email,'')
        self.send('julio@example.com');self.send('2');self.send('6');self.send('Empresarial');self.send('Organizar os atendimentos')
        lead=Lead.objects.get()
        self.assertEqual(lead.email,'julio@example.com');self.assertIn('Unidades: 2',lead.notes)
        self.assertIn('Plano de interesse: Empresarial',lead.notes)
        self.assertFalse(lead.consent_granted)
        self.assertEqual(self.conversation.sales_lead_id,lead.pk)
        self.assertTrue(self.conversation.human_handoff)
        self.assertEqual(lead.history.count(),1)

    def test_question_during_intake_preserves_field(self):
        self.send('oi');self.send('3');self.send('Ana')
        context=self.send('Como funciona a agenda?')
        self.assertEqual(context['_sales_field'],'empresa')
        self.assertEqual(context['nome'],'Ana')
        self.assertEqual(Lead.objects.get().notes.count('[Chatbot ApPlanner]'),1)
        self.send('Salão Ana')
        self.assertIn('Salão Ana',Lead.objects.get().notes)

    def test_public_plans_are_live_and_hide_private_plans(self):
        p=Plan.objects.create(name='Plano Atual',slug='atual',monthly_price='49.90',trial_days=7)
        Plan.objects.create(name='Privado',slug='privado',public_visible=False)
        self.assertIn('49,90',plans_text());self.assertNotIn('Privado',plans_text())
        p.monthly_price='59.90';p.save()
        self.assertIn('59,90',answer_question('Quanto custa?'))

    def test_simulation_never_creates_leads(self):
        result=run_graph(commercial_graph(),self.flow,'cadastro',{'variables':{'contact_phone':'5581999999999'}},'', '',simulation=True)
        result=run_graph(commercial_graph(),self.flow,result['state'],result['context'],result['waiting'],'Ana',simulation=True)
        self.assertEqual(result['context']['variables']['nome'],'Ana')
        self.assertFalse(Lead.objects.exists())

    def test_human_request_is_not_triggered_by_generic_question(self):
        self.send('oi');self.send('O sistema envia mensagem para clientes atendidos?')
        self.assertFalse(self.conversation.human_handoff)
        self.send('Quero falar com atendente')
        self.assertTrue(self.conversation.human_handoff)

    def test_new_api_resources_require_scopes_and_exclude_secrets(self):
        import hashlib
        from datetime import timedelta
        from accounts.models import User,PersonalAPIToken
        master=User.objects.create_superuser(email='sales-api@example.com',password='Test12345!')
        raw='ap_sales_test_token'
        token=PersonalAPIToken.objects.create(user=master,name='Test',prefix=raw[:12],secret_hash=hashlib.sha256(raw.encode()).hexdigest(),scopes=['master.read','commercial.read'],session_version=master.session_version,expires_at=timezone.now()+timedelta(days=1))
        self.flow.ai_key_encrypted='encrypted-secret';self.flow.save()
        response=self.client.get('/api/v1/chatbot-master/',HTTP_AUTHORIZATION='Bearer '+raw)
        self.assertEqual(response.status_code,200)
        self.assertNotIn('encrypted-secret',response.content.decode())
        self.assertEqual(self.client.get('/api/v1/planos-publicos/',HTTP_AUTHORIZATION='Bearer '+raw).status_code,200)
        self.send('oi');self.send('3');self.send('Ana');self.send('Salão Ana')
        response=self.client.get('/api/v1/leads/',HTTP_AUTHORIZATION='Bearer '+raw)
        self.assertEqual(response.status_code,200)
        self.assertIn('phone',response.json()['dados'][0])
        token.scopes=['commercial.read'];token.save()
        self.assertEqual(self.client.get('/api/v1/chatbot-master/',HTTP_AUTHORIZATION='Bearer '+raw).status_code,403)

    def test_reused_lead_preserves_notes_and_marketing_choice(self):
        lead=Lead.objects.create(name='Contato',phone='5581999999999',email='',business_type='',notes='Observação do vendedor',consent_granted=True)
        self.send('oi');self.send('3');self.send('Ana');self.send('Salão Ana')
        lead.refresh_from_db()
        self.assertEqual(Lead.objects.count(),1)
        self.assertIn('Observação do vendedor',lead.notes)
        self.assertEqual(lead.notes.count('[Chatbot ApPlanner]'),1)
        self.assertTrue(lead.consent_granted)
