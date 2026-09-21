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
