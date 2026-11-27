import hashlib
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from communications.models import Notification, TenantWhatsAppConnection
from core.crypto import encrypt_text
from scheduling.models import Appointment, Customer, Professional, Service, TenantScheduleSettings
from scheduling.tasks import queue_appointment_reminders
from tenants.models import Tenant


@override_settings(PUBLIC_BASE_URL="https://applanner.example.test")
class AppointmentReminderTests(TestCase):
    def test_two_hour_reminder_is_once_per_channel_and_contains_manage_link(self):
        tenant=Tenant.objects.create(name="Empresa",slug="empresa-reminders",status=Tenant.Status.ACTIVE)
        customer=Customer.objects.create(tenant=tenant,name="Cliente",phone="81999999999",email="cliente@example.test")
        service=Service.objects.create(tenant=tenant,name="Serviço",duration_minutes=30)
        pro=Professional.objects.create(tenant=tenant,name="Ana")
        TenantWhatsAppConnection.objects.create(tenant=tenant,enabled=True)
        TenantScheduleSettings.objects.create(tenant=tenant,reminder_2h_enabled=True)
        token="secure-manage-token"
        start=timezone.now()+timedelta(hours=2,minutes=30)
        appointment=Appointment.objects.create(tenant=tenant,customer=customer,service=service,professional=pro,
            starts_at=start,ends_at=start+timedelta(minutes=30),status=Appointment.Status.CONFIRMED,
            customer_manage_token_hash=hashlib.sha256(token.encode()).hexdigest(),
            customer_manage_token_encrypted=encrypt_text(token))
        self.assertEqual(Notification.objects.filter(template_key="appointment_confirmation",
            channel=Notification.Channel.WHATSAPP).count(),1)
        self.assertEqual(queue_appointment_reminders(),2)
        self.assertEqual(queue_appointment_reminders(),0)
        email=Notification.objects.get(template_key="appointment_2h",channel=Notification.Channel.EMAIL)
        whatsapp=Notification.objects.get(template_key="appointment_reminder",channel=Notification.Channel.WHATSAPP)
        self.assertIn("/agendamento/secure-manage-token/",email.payload["text"])
        self.assertIn("/agendamento/secure-manage-token/",whatsapp.payload["text"])
        self.assertEqual(whatsapp.destination,"5581999999999")
        appointment.status=Appointment.Status.CANCELLED
        appointment.save(update_fields=["status"])
        self.assertEqual(queue_appointment_reminders(),0)
