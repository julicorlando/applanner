from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from tenants.models import Tenant
from engagement.models import BehaviorEvent, BehaviorProfile, BehaviorServiceProfile
from engagement.behavior import refresh_behavior_for_tenant
from .models import Appointment, Customer, Professional, Service


class FirstBookingIntelligenceTests(TestCase):
    def test_first_booking_creates_profile_without_fake_completed_visit(self):
        tenant=Tenant.objects.create(name='Teste',slug='first-booking')
        customer=Customer.objects.create(tenant=tenant,name='Cliente')
        service=Service.objects.create(tenant=tenant,name='Corte',duration_minutes=30,price=10)
        professional=Professional.objects.create(tenant=tenant,name='Profissional')
        starts=timezone.now()+timedelta(days=1)
        Appointment.objects.create(tenant=tenant,customer=customer,service=service,professional=professional,
            starts_at=starts,ends_at=starts+timedelta(minutes=30),status=Appointment.Status.CONFIRMED)
        profile=BehaviorProfile.objects.get(tenant=tenant,customer=customer)
        self.assertEqual(profile.visits_count,0)
        self.assertIsNone(profile.next_expected_date)
        self.assertTrue(BehaviorServiceProfile.objects.filter(tenant=tenant,customer=customer,service=service).exists())
        self.assertEqual(BehaviorEvent.objects.filter(customer=customer,event_type='first_appointment').count(),1)
        refresh_behavior_for_tenant(tenant)
        self.assertTrue(BehaviorProfile.objects.filter(pk=profile.pk).exists())
