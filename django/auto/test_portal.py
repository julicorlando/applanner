from datetime import timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from auto.models import Job,Vehicle
from scheduling.models import Appointment,Customer,Service
from tenants.models import Tenant


class AutoPortalTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Auto",slug="auto-test")
        self.user=User.objects.create_user(email="auto@example.com",password="StrongPassword123!",tenant=self.tenant,role="auto-manager")
        customer=Customer.objects.create(tenant=self.tenant,name="Cliente")
        service=Service.objects.create(tenant=self.tenant,name="Detail",duration_minutes=60,price="100.00")
        vehicle=Vehicle.objects.create(tenant=self.tenant,customer=customer,plate="ABC1D23",model="Carro")
        start=timezone.now()+timedelta(days=1)
        appointment=Appointment.objects.create(tenant=self.tenant,customer=customer,service=service,starts_at=start,ends_at=start+timedelta(hours=1))
        self.job=Job.objects.create(tenant=self.tenant,appointment=appointment,vehicle=vehicle)
        self.client.force_login(self.user)

    def test_job_detail_and_open_command(self):
        self.assertEqual(self.client.get(reverse("auto-job-detail",args=[self.job.pk])).status_code,200)
        response=self.client.post(reverse("auto-job-action",args=[self.job.pk]),{"action":"open_command"})
        self.assertEqual(response.status_code,302)
        self.assertTrue(hasattr(Job.objects.get(pk=self.job.pk),"command"))


    def test_regular_user_is_denied(self):
        other=User.objects.create_user(
            email="basic-auto@example.com",password="StrongPassword123!",
            tenant=self.tenant,role="user",
        )
        self.client.force_login(other)
        self.assertEqual(
            self.client.get(reverse("auto-job-detail",args=[self.job.pk])).status_code,
            403,
        )
