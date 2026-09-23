from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.test import TestCase

from accounts.models import User
from tenants.models import Tenant
from .availability import AvailabilityService
from .models import Appointment, Customer, Professional, ProfessionalAvailability, Service


class AvailabilityServiceTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Demo",slug="demo",status=Tenant.Status.ACTIVE)
        self.user=User.objects.create(email="owner@example.com",tenant=self.tenant)
        self.customer=Customer.objects.create(tenant=self.tenant,name="Cliente")
        self.service=Service.objects.create(tenant=self.tenant,name="Corte",duration_minutes=60,price=50)
        self.professional=Professional.objects.create(tenant=self.tenant,name="Profissional")
        self.professional.services.add(self.service)
        ProfessionalAvailability.objects.create(
            tenant=self.tenant,
            professional=self.professional,
            weekday=1,
            start_time=time(8,0),
            end_time=time(12,0),
        )

    def test_slots_respect_existing_appointment(self):
        monday=date(2030,1,7)
        slots=AvailabilityService().slots(
            self.tenant,self.service.pk,self.professional.pk,monday,public_rules=False
        )
        self.assertTrue(any(slot["label"]=="08:00" for slot in slots))

        tz=ZoneInfo("America/Recife")
        Appointment.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            professional=self.professional,
            service=self.service,
            starts_at=datetime(2030,1,7,8,0,tzinfo=tz),
            ends_at=datetime(2030,1,7,9,0,tzinfo=tz),
            status=Appointment.Status.CONFIRMED,
            created_by=self.user,
        )
        slots=AvailabilityService().slots(
            self.tenant,self.service.pk,self.professional.pk,monday,public_rules=False
        )
        self.assertFalse(any(slot["label"]=="08:00" for slot in slots))


class PublicBookingFlowTests(TestCase):
    def setUp(self):
        from django.utils import timezone
        self.tenant=Tenant.objects.create(
            name="Public Demo",slug="public-demo",public_slug="public-demo",
            public_enabled=True,public_booking_enabled=True,status=Tenant.Status.ACTIVE,
        )
        self.service=Service.objects.create(
            tenant=self.tenant,name="Atendimento",duration_minutes=30,price=60
        )
        self.professionals=[]
        tomorrow=timezone.localdate()+__import__("datetime").timedelta(days=1)
        self.day=tomorrow
        for idx in range(2):
            professional=Professional.objects.create(
                tenant=self.tenant,name=f"Profissional {idx+1}",public_slug=f"prof-{idx+1}"
            )
            professional.services.add(self.service)
            ProfessionalAvailability.objects.create(
                tenant=self.tenant,professional=professional,weekday=tomorrow.isoweekday(),
                start_time=time(8,0),end_time=time(18,0),
            )
            self.professionals.append(professional)

    def test_availability_can_choose_any_professional(self):
        response=self.client.get(
            f"/api/public/{self.tenant.public_slug}/availability/",
            {"service_id":self.service.pk,"date":self.day.isoformat()},
        )
        self.assertEqual(response.status_code,200)
        payload=response.json()
        self.assertTrue(payload["auto_professional"])
        self.assertTrue(payload["slots"])
        self.assertIn("professional_id",payload["slots"][0])

    def test_booking_without_professional_auto_assigns_and_returns_management_url(self):
        availability=self.client.get(
            f"/api/public/{self.tenant.public_slug}/availability/",
            {"service_id":self.service.pk,"date":self.day.isoformat()},
        ).json()
        start=availability["slots"][0]["value"]
        response=self.client.post(
            f"/api/public/{self.tenant.public_slug}/book/",
            {
                "service_id":self.service.pk,"starts_at":start,
                "name":"Cliente Teste","phone":"81999999999",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code,201)
        payload=response.json()
        self.assertTrue(payload["professional"]["id"])
        self.assertIn("/agendamento/",payload["manage_url"])
        appointment=Appointment.objects.get(pk=payload["id"])
        self.assertIsNotNone(appointment.professional_id)

    def test_professional_public_page_exists(self):
        response=self.client.get(
            f"/p/{self.tenant.public_slug}/profissional/{self.professionals[0].public_slug}/"
        )
        self.assertEqual(response.status_code,200)
        self.assertContains(response,self.professionals[0].name)
        self.assertContains(response,"AGENDAMENTO ONLINE")
