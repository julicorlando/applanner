from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase, override_settings, SimpleTestCase
from django.utils import timezone
from accounts.models import User
from tenants.models import Tenant
from scheduling.models import Customer, Professional, Service, Appointment
from engagement.contacting import send_return_invitation
from engagement.models import CustomerContactThrottle
from communications.models import TenantWhatsAppConnection, Notification, MasterWhatsAppConversation, MasterWhatsAppMessage, MasterWhatsAppFlow
from communications.master_whatsapp_flow import MasterFlowForm, process_master_automation
from communications.tasks import send_notification
from billing.models import Plan, Subscription
from billing.reminders import queue_subscription_reminder
from billing.mercadopago import MercadoPagoProvider

class MinimumChargeTests(SimpleTestCase):
    def test_invalid_amounts_never_call_provider(self):
        calls=[]
        provider=MercadoPagoProvider('TEST-abcdefghijklmnop',transport=lambda *args:calls.append(args))
        for amount in ['0','0.49','-1','NaN','Infinity','invalid']:
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                provider.create_subscription(reason='Plano',external_reference='sub1',payer_email='a@example.test',back_url='https://example.test',amount=amount)
        self.assertEqual(calls,[])

    def test_minimum_and_normal_amounts_are_preserved(self):
        calls=[]
        provider=MercadoPagoProvider('TEST-abcdefghijklmnop',transport=lambda *args:(calls.append(args) or {'id':'sub1','init_point':'https://example.test'}))
        for amount in ['0.50','49.90']:
            provider.create_subscription(reason='Plano',external_reference='sub1',payer_email='a@example.test',back_url='https://example.test',amount=amount)
        self.assertEqual([c[2]['auto_recurring']['transaction_amount'] for c in calls],[0.5,49.9])

@override_settings(PUBLIC_BASE_URL='https://example.test', MASTER_WHATSAPP_GATEWAY_TOKEN='fake-test-token',MASTER_WHATSAPP_GATEWAY_URL='http://internal:3100')
class ReturnBillingTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name='Empresa',slug='retorno-wa',phone='81999999999',status='active')
        self.user=User.objects.create_user(email='professional@example.test',password='test123',role='professional',tenant=self.tenant)
        self.owner=User.objects.create_user(email='owner@example.test',password='test123',role='owner',tenant=self.tenant)
        self.prof=Professional.objects.create(name='Ana',public_slug='ana',user=self.user,tenant=self.tenant)
        self.customer=Customer.objects.create(name='Cliente',phone='81988888888',consent_marketing=True,tenant=self.tenant)
        self.service=Service.objects.create(name='Corte',price=Decimal('50'),duration_minutes=30,tenant=self.tenant)
        now=timezone.now()-timedelta(days=30)
        Appointment.objects.create(tenant=self.tenant,customer=self.customer,service=self.service,professional=self.prof,starts_at=now,ends_at=now+timedelta(minutes=30),status='completed')
        TenantWhatsAppConnection.objects.create(tenant=self.tenant,enabled=True)

    @patch('engagement.contacting.gateway',return_value={'id':'return1'})
    def test_first_completed_customer_gets_professional_link_once(self,gateway):
        send_return_invitation(tenant=self.tenant,customer=self.customer,user=self.user)
        self.assertIn('/profissional/ana/',gateway.call_args.args[3]['text'])
        self.assertEqual(gateway.call_args.args[0],self.tenant)
        with self.assertRaisesMessage(ValueError,'24 horas'):
            send_return_invitation(tenant=self.tenant,customer=self.customer,user=self.owner)
        self.assertEqual(gateway.call_count,1)

    @patch('engagement.contacting.gateway')
    def test_consent_and_attendance_are_required(self,gateway):
        self.customer.consent_marketing=False
        with self.assertRaisesMessage(ValueError,'autorizar'):
            send_return_invitation(tenant=self.tenant,customer=self.customer,user=self.user)
        self.customer.consent_marketing=True
        self.prof.appointments.all().delete()
        with self.assertRaisesMessage(ValueError,'já atendeu'):
            send_return_invitation(tenant=self.tenant,customer=self.customer,user=self.user)
        gateway.assert_not_called()

    @patch('engagement.contacting.gateway')
    def test_professional_daily_limit(self,gateway):
        for n in range(20):
            c=Customer.objects.create(name=f'Cliente {n}',tenant=self.tenant)
            CustomerContactThrottle.objects.create(tenant=self.tenant,customer=c,last_contact_at=timezone.now(),reason='return_invite',sent_by=self.user)
        with self.assertRaisesMessage(ValueError,'20 convites'):
            send_return_invitation(tenant=self.tenant,customer=self.customer,user=self.user)
        gateway.assert_not_called()

    @patch('engagement.contacting.gateway',side_effect=ValueError('off'))
    def test_failed_gateway_releases_customer_and_daily_allowance(self,gateway):
        with self.assertRaises(ValueError):
            send_return_invitation(tenant=self.tenant,customer=self.customer,user=self.user)
        self.assertFalse(CustomerContactThrottle.objects.filter(sent_by=self.user).exists())

    def test_billing_whatsapp_is_queued_once_per_stage(self):
        plan=Plan.objects.create(name='Plano',slug='wa-plan',monthly_price=50)
        sub=Subscription.objects.create(tenant=self.tenant,plan=plan,status='trial',started_at=timezone.now(),trial_ends_at=timezone.now()+timedelta(days=2))
        self.assertEqual(queue_subscription_reminder(sub.pk),1)
        self.assertEqual(queue_subscription_reminder(sub.pk),0)
        notice=Notification.objects.get(channel='whatsapp',template_key='subscription_due')
        self.assertEqual(notice.destination,'5581999999999')
        self.assertEqual(notice.payload['sender'],'master')

    @patch('communications.master_whatsapp._gateway',return_value={'id':'billing1','to':'5581999999999@s.whatsapp.net'})
    @patch('communications.whatsapp.send_text')
    def test_due_notification_uses_master_and_records_inbox(self,cloud,gateway):
        plan=Plan.objects.create(name='Plano',slug='wa-plan2',monthly_price=50)
        sub=Subscription.objects.create(tenant=self.tenant,plan=plan,status='trial',started_at=timezone.now(),trial_ends_at=timezone.now()+timedelta(days=2))
        queue_subscription_reminder(sub.pk)
        notice=Notification.objects.get(channel='whatsapp')
        send_notification(notice.pk)
        notice.refresh_from_db()
        self.assertEqual(notice.status,'sent')
        self.assertEqual(MasterWhatsAppMessage.objects.get().provider_message_id,'billing1')
        cloud.assert_not_called()

class VisualFlowTests(TestCase):
    def test_positions_and_finish_survive_form_validation(self):
        form=MasterFlowForm(data={'enabled':'','greeting':'Olá','fallback':'Não entendi','handoff':'Equipe','steps_text':'inicio | 1;sim | Obrigado | | não | fim','positions_text':'{"inicio":{"x":100,"y":150}}'},instance=MasterWhatsAppFlow())
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(form.cleaned_data['steps_text'][0]['position'],{'x':100,'y':150})
        self.assertTrue(form.cleaned_data['steps_text'][0]['finish'])

    def test_invalid_connection_and_positions_are_rejected(self):
        form=MasterFlowForm(data={'greeting':'Olá','fallback':'Não entendi','handoff':'Equipe','steps_text':'inicio | 1 | Resposta | inexistente | não','positions_text':'{"inicio":{"x":"javascript","y":20}}'},instance=MasterWhatsAppFlow())
        self.assertFalse(form.is_valid())

    @patch('communications.master_whatsapp._gateway',return_value={'id':'end1','to':'5581999999999@s.whatsapp.net'})
    def test_finish_step_and_read_state(self,gateway):
        MasterWhatsAppFlow.objects.create(pk=1,enabled=True,steps=[{'id':'inicio','keywords':['fim'],'reply':'Obrigado!','next':'','handoff':False,'finish':True}])
        conv=MasterWhatsAppConversation.objects.create(wa_id='5581999999999@s.whatsapp.net',flow_state='inicio',last_message_at=timezone.now())
        msg=MasterWhatsAppMessage.objects.create(conversation=conv,provider_message_id='in1',direction='in',body='fim',read_at=timezone.now())
        process_master_automation(msg.pk)
        conv.refresh_from_db()
        self.assertEqual(conv.flow_state,'__finished__')

class AutomaticReturnTests(ReturnBillingTests):
    def setUp(self):
        super().setUp()
        from engagement.models import ReturnMessagingSettings,BehaviorProfile
        self.config=ReturnMessagingSettings.objects.create(tenant=self.tenant,enabled=True,daily_limit=1)
        self.profile,_=BehaviorProfile.objects.update_or_create(tenant=self.tenant,customer=self.customer,defaults={'next_expected_date':timezone.localdate()-timedelta(days=1)})

    def test_campaign_deduplicates_and_excludes_future_booking(self):
        from engagement.return_automation import queue_return_campaign
        self.assertEqual(queue_return_campaign(self.tenant),1)
        self.assertEqual(queue_return_campaign(self.tenant),0)
        Notification.objects.all().delete()
        now=timezone.now()+timedelta(days=1)
        Appointment.objects.create(tenant=self.tenant,customer=self.customer,professional=self.prof,service=self.service,starts_at=now,ends_at=now+timedelta(minutes=30),status='confirmed')
        self.assertEqual(queue_return_campaign(self.tenant),0)

    @patch('engagement.contacting.gateway',return_value={'id':'auto1'})
    def test_delivery_rechecks_opt_out_and_uses_company_sender(self,gateway):
        from engagement.return_automation import queue_return_campaign,deliver_return_invitation
        queue_return_campaign(self.tenant)
        notice=Notification.objects.get(template_key='return_invitation')
        self.customer.consent_marketing=False;self.customer.save()
        self.assertEqual(deliver_return_invitation(notice),'')
        gateway.assert_not_called()
        self.customer.consent_marketing=True;self.customer.save()
        notice.status='queued';notice.save()
        self.assertEqual(deliver_return_invitation(notice),'auto1')
        self.assertEqual(gateway.call_args.args[0],self.tenant)
