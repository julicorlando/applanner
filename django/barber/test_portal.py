from django.test import TestCase
from django.urls import reverse
from accounts.models import User
from barber.models import BarberCommand
from scheduling.models import Customer,Professional,Service
from tenants.models import Tenant


class BarberPortalTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Barber",slug="barber-test")
        self.user=User.objects.create_user(email="barber@example.com",password="StrongPassword123!",tenant=self.tenant)
        self.customer=Customer.objects.create(tenant=self.tenant,name="Cliente")
        self.professional=Professional.objects.create(tenant=self.tenant,name="Profissional")
        self.service=Service.objects.create(tenant=self.tenant,name="Corte",duration_minutes=30,price="50.00")
        self.client.force_login(self.user)

    def test_open_command_from_portal(self):
        response=self.client.post(reverse("barber-command-create"),{
            "customer":self.customer.pk,"professional":self.professional.pk,"notes":"Teste",
        })
        self.assertEqual(response.status_code,302)
        self.assertEqual(BarberCommand.objects.filter(tenant=self.tenant).count(),1)
