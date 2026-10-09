from datetime import time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from engagement.models import WaitlistEntry
from scheduling.models import Appointment, Customer, Professional, ProfessionalAvailability, ProfessionalService, Service
from tenants.models import Tenant


class ProfessionalWaitlistTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Oficina",slug="oficina-espera",status=Tenant.Status.ACTIVE)
        self.other=Tenant.objects.create(name="Outra",slug="outra-espera",status=Tenant.Status.ACTIVE)
        self.user=User.objects.create_user(email="espera@example.test",password="Secure123!",tenant=self.tenant,role="professional")
        self.professional=Professional.objects.create(tenant=self.tenant,user=self.user,name="Ana")
        self.customer=Customer.objects.create(tenant=self.tenant,name="Cliente",phone="(81) 99999-9999")
        self.service=Service.objects.create(tenant=self.tenant,name="Revisão",duration_minutes=30,price=Decimal("75"))
        ProfessionalService.objects.create(professional=self.professional,service=self.service)
        tomorrow=(timezone.now().astimezone(ZoneInfo(self.tenant.timezone)).date()+timedelta(days=1))
        ProfessionalAvailability.objects.create(tenant=self.tenant,professional=self.professional,
            weekday=tomorrow.isoweekday(),start_time=time(8),end_time=time(18))
        self.entry=WaitlistEntry.objects.create(tenant=self.tenant,customer=self.customer,service=self.service,
            preferred_date=tomorrow,status=WaitlistEntry.Status.WAITING)
        self.client.force_login(self.user)

    def test_schedules_waiting_customer_once_with_manage_link(self):
        url=reverse("professional-waitlist",args=[self.entry.pk])
        self.assertContains(self.client.get(reverse("professional-area")),"Cliente")
        page=self.client.get(url)
        self.assertContains(page,"Atendimento avulso agora")
        slot=page.context["slots"][0]["value"]
        self.assertEqual(self.client.post(url,{"action":"schedule","starts_at":slot}).status_code,302)
        self.entry.refresh_from_db()
        appointment=self.entry.appointment
        self.assertEqual(self.entry.status,WaitlistEntry.Status.BOOKED)
        self.assertEqual(appointment.status,Appointment.Status.CONFIRMED)
        self.assertTrue(appointment.customer_manage_token_encrypted)
        self.assertEqual(appointment.service_price_snapshot,Decimal("75"))
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertNotContains(self.client.get(reverse("professional-area")),"Clientes na lista de espera</h2><span>1")

    def test_walk_in_occupies_time_and_cannot_double_book(self):
        url=reverse("professional-waitlist",args=[self.entry.pk])
        self.assertEqual(self.client.post(url,{"action":"instant"}).status_code,302)
        self.entry.refresh_from_db()
        appointment=self.entry.appointment
        self.assertEqual(appointment.status,Appointment.Status.IN_PROGRESS)
        self.assertEqual(appointment.source,Appointment.Source.WALK_IN)
        self.assertIsNotNone(appointment.checked_in_at)
        self.assertLess(abs((appointment.starts_at-timezone.now()).total_seconds()),30)
        second=WaitlistEntry.objects.create(tenant=self.tenant,customer=self.customer,service=self.service,
            status=WaitlistEntry.Status.WAITING)
        response=self.client.post(reverse("professional-waitlist",args=[second.pk]),{"action":"instant"})
        self.assertContains(response,"Profissional ocupado")
        second.refresh_from_db()
        self.assertEqual(second.status,WaitlistEntry.Status.WAITING)

    def test_other_professional_and_tenant_are_hidden(self):
        other_prof=Professional.objects.create(tenant=self.tenant,name="Bia")
        self.entry.professional=other_prof
        self.entry.save(update_fields=["professional"])
        self.assertEqual(self.client.get(reverse("professional-waitlist",args=[self.entry.pk])).status_code,403)
        foreign_customer=Customer.objects.create(tenant=self.other,name="Outro")
        foreign_service=Service.objects.create(tenant=self.other,name="Outro",duration_minutes=30)
        foreign=WaitlistEntry.objects.create(tenant=self.other,customer=foreign_customer,service=foreign_service)
        self.assertEqual(self.client.get(reverse("professional-waitlist",args=[foreign.pk])).status_code,404)
