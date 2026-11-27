from datetime import date,datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from tenants.models import Tenant
from scheduling.models import Customer
from accounts.models import User
from billing.models import Module,TenantModule
from .models import Notification,TenantWhatsAppConnection
from .birthday_models import BirthdaySettings,BirthdayDelivery
from .birthdays import queue_tenant,validate_delivery,is_birthday,send_birthday_whatsapp
from .tasks import send_notification


class BirthdayTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name='Clínica teste',slug='birthday-clinic',category='odontologia',timezone='America/Recife')
        self.now=timezone.now().replace(hour=15)
        self.day=timezone.localtime(self.now,ZoneInfo('America/Recife')).date()
        self.customer=Customer.objects.create(tenant=self.tenant,name='Paciente Teste',email='birthday@example.invalid',phone='5581999999999',
            birth_date=self.day.replace(year=self.day.year-30),consent_marketing=True)
        self.config=BirthdaySettings.objects.create(tenant=self.tenant,enabled=True,channel='email')
        self.clock=patch('communications.birthdays.timezone.now',return_value=self.now);self.clock.start();self.addCleanup(self.clock.stop)

    def test_queue_once_per_patient_and_year_and_render_name(self):
        self.assertEqual(queue_tenant(self.tenant.pk),1)
        self.assertEqual(queue_tenant(self.tenant.pk),0)
        notice=Notification.objects.get(template_key='customer_birthday')
        self.assertIn('Paciente',notice.payload['text']);self.assertIn(self.tenant.name,notice.payload['text'])
        self.assertEqual(BirthdayDelivery.objects.count(),1)

    def test_consent_active_customer_date_and_hour_are_required(self):
        self.customer.consent_marketing=False;self.customer.save()
        self.assertEqual(queue_tenant(self.tenant.pk),0)
        self.customer.consent_marketing=True;self.customer.active=False;self.customer.save()
        self.assertEqual(queue_tenant(self.tenant.pk),0)
        self.customer.active=True;self.customer.birth_date=date(1990,1,1) if self.day.month!=1 else date(1990,2,1);self.customer.save()
        self.assertEqual(queue_tenant(self.tenant.pk),0)

    def test_revocation_or_disabled_setting_skips_even_already_queued_messages(self):
        queue_tenant(self.tenant.pk);notice=Notification.objects.get()
        self.customer.consent_marketing=False;self.customer.save()
        self.assertIsNone(validate_delivery(notice));notice.refresh_from_db();self.assertEqual(notice.status,'skipped')
        self.customer.consent_marketing=True;self.customer.save();self.config.enabled=False;self.config.save()
        self.assertIsNone(validate_delivery(notice))

    def test_email_sent_via_existing_notification_queue_and_no_repeat(self):
        from django.core import mail
        queue_tenant(self.tenant.pk);notice=Notification.objects.get()
        send_notification(notice.pk);notice.refresh_from_db()
        self.assertEqual(notice.status,'sent');self.assertEqual(len(mail.outbox),1)
        send_notification(notice.pk);self.assertEqual(len(mail.outbox),1)
        self.assertEqual(mail.outbox[0].to,['birthday@example.invalid'])

    def test_whatsapp_requires_module_and_own_connection_with_stable_idempotency(self):
        self.config.channel='whatsapp';self.config.save()
        self.assertEqual(queue_tenant(self.tenant.pk),0)
        module,_=Module.objects.get_or_create(slug='whatsapp',defaults={'name':'WhatsApp','active':True})
        TenantModule.objects.create(tenant=self.tenant,module=module,enabled=True)
        TenantWhatsAppConnection.objects.create(tenant=self.tenant,enabled=True)
        self.assertEqual(queue_tenant(self.tenant.pk),1)
        notice=Notification.objects.get();row=validate_delivery(notice)
        with patch('communications.tenant_whatsapp.gateway',return_value={'id':'fake-provider-message'}) as gateway:
            self.assertEqual(send_birthday_whatsapp(notice,row),'fake-provider-message')
            args=gateway.call_args.args
            self.assertEqual(args[0],self.tenant);self.assertEqual(args[2],'send')
            self.assertRegex(args[3]['idempotencyKey'],r'^birthday_[0-9]+_[0-9]+_[0-9]+$')
            self.assertEqual(args[3]['to'],notice.destination)

    def test_leap_birthday_and_no_late_delivery_on_next_day(self):
        self.assertTrue(is_birthday(date(2000,2,29),date(2027,2,28)))
        self.assertFalse(is_birthday(date(2000,2,29),date(2028,2,28)))
        queue_tenant(self.tenant.pk);notice=Notification.objects.get()
        with patch('communications.birthdays.local_now',return_value=self.now+timezone.timedelta(days=1)):
            self.assertIsNone(validate_delivery(notice))

    def test_tenant_timezone_and_cross_tenant_settings(self):
        self.tenant.timezone='Asia/Tokyo';self.tenant.save()
        with patch('communications.birthdays.timezone.now',return_value=datetime(2026,11,4,14,tzinfo=ZoneInfo('UTC'))):
            self.assertEqual(queue_tenant(self.tenant.pk),0) # 23h in Tokyo, outside sending window
        other=Tenant.objects.create(name='Outra',slug='birthday-other',category='odontologia')
        self.assertEqual(queue_tenant(other.pk),0)

    def test_only_management_can_enable_and_scheduler_is_registered(self):
        owner=User.objects.create_user(email='birthday-owner@example.invalid',tenant=self.tenant,role='owner')
        module,_=Module.objects.get_or_create(slug='finance',defaults={'name':'Financeiro','active':True})
        TenantModule.objects.create(tenant=self.tenant,module=module,enabled=True)
        self.client.force_login(owner)
        response=self.client.post(reverse('clinic-birthday-settings'),{'enabled':'on','channel':'email','hour':10,'message':'Olá, {nome}! Parabéns! {empresa}'})
        self.assertEqual(response.status_code,302)
        self.config.refresh_from_db();self.assertEqual(self.config.hour,10)
        from core.management.commands.seed_periodic_tasks import TASKS
        self.assertTrue(any(row[1]=='communications.tasks.queue_customer_birthdays' for row in TASKS))
