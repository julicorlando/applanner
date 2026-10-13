from datetime import timedelta
from io import StringIO

from django.core.management import call_command, CommandError
from django.test import TestCase
from django.utils import timezone

from communications.models import Notification
from scheduling.models import Appointment, Customer, Professional, Service
from tenants.models import Tenant


class HomologationCleanupTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Homologação QA teste",slug="cleanup-qa")
        self.qa=Professional.objects.create(tenant=self.tenant,name="Profissional QA",active=True)
        self.real=Professional.objects.create(tenant=self.tenant,name="Ana",active=True)
        self.service=Service.objects.create(tenant=self.tenant,name="Serviço QA",duration_minutes=30,price=0)
        self.customer=Customer.objects.create(tenant=self.tenant,name="Cliente QA")
        self.real_customer=Customer.objects.create(tenant=self.tenant,name="Cliente real")
        self.appointment=self.booking(self.customer)
        self.real_booking=self.booking(self.real_customer)

    def booking(self,customer):
        start=timezone.now()+timedelta(days=2)
        return Appointment.objects.create(tenant=self.tenant,customer=customer,service=self.service,professional=self.qa,
            starts_at=start,ends_at=start+timedelta(minutes=30),status="pending",notes="Homologação sem atendimento real.")

    def test_dry_run_and_apply_preserve_real_records_and_history(self):
        call_command("cleanup_homologation",tenant_slug=self.tenant.slug,stdout=StringIO())
        self.qa.refresh_from_db()
        self.assertTrue(self.qa.active)
        notification=Notification.objects.create(tenant=self.tenant,channel="email",payload={"appointment_id":self.appointment.pk})
        call_command("cleanup_homologation",tenant_slug=self.tenant.slug,apply=True,stdout=StringIO())
        for row in [self.qa,self.real,self.service,self.appointment,self.real_booking,notification]:
            row.refresh_from_db()
        self.assertFalse(self.qa.active)
        self.assertFalse(self.service.active)
        self.assertTrue(self.real.active)
        self.assertEqual(self.appointment.status,"cancelled")
        self.assertEqual(self.real_booking.status,"pending")
        self.assertEqual(notification.status,"cancelled")
        self.assertEqual(Appointment.objects.count(),2)

    def test_normal_company_is_refused(self):
        self.tenant.name="Empresa real"
        self.tenant.save()
        with self.assertRaises(CommandError):
            call_command("cleanup_homologation",tenant_slug=self.tenant.slug,apply=True,stdout=StringIO())
        self.qa.refresh_from_db()
        self.assertTrue(self.qa.active)
