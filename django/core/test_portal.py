from decimal import Decimal
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from scheduling.models import Appointment, Customer, Professional, Service
from tenants.models import Tenant


class PortalTenantIsolationTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Tenant A",slug="tenant-a",status=Tenant.Status.ACTIVE)
        self.other=Tenant.objects.create(name="Tenant B",slug="tenant-b",status=Tenant.Status.ACTIVE)
        self.user=User.objects.create_user(email="user@example.test",password="StrongPassword123!",tenant=self.tenant,role="manager")
        self.client.force_login(self.user)

    def test_portal_home_works_for_tenant_user(self):
        response=self.client.get(reverse("portal-home"))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"Tenant A")
        self.assertContains(response,"Agenda")

    def test_customer_list_is_tenant_scoped(self):
        Customer.objects.create(tenant=self.tenant,name="Cliente A")
        Customer.objects.create(tenant=self.other,name="Cliente B")
        response=self.client.get(reverse("portal-resource-list",args=["agenda","clientes"]))
        self.assertContains(response,"Cliente A")
        self.assertNotContains(response,"Cliente B")

    def test_cannot_edit_record_from_another_tenant(self):
        customer=Customer.objects.create(tenant=self.other,name="Outro")
        response=self.client.get(reverse("portal-resource-edit",args=["agenda","clientes",customer.pk]))
        self.assertEqual(response.status_code,404)


class PortalAppointmentTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Agenda",slug="agenda",status=Tenant.Status.ACTIVE)
        self.user=User.objects.create_user(email="agenda@example.test",password="StrongPassword123!",tenant=self.tenant,role="manager")
        self.customer=Customer.objects.create(tenant=self.tenant,name="Cliente")
        self.service=Service.objects.create(tenant=self.tenant,name="Corte",duration_minutes=45,price="50.00")
        self.professional=Professional.objects.create(tenant=self.tenant,name="Profissional")
        self.client.force_login(self.user)

    def test_create_appointment_derives_end_and_price_snapshot(self):
        start=timezone.now().replace(second=0,microsecond=0)+timedelta(days=1)
        response=self.client.post(
            reverse("portal-resource-create",args=["agenda","agendamentos"]),
            {
                "customer":self.customer.pk,
                "professional":self.professional.pk,
                "service":self.service.pk,
                "starts_at":timezone.localtime(start).strftime("%Y-%m-%dT%H:%M"),
                "status":Appointment.Status.CONFIRMED,
                "source":Appointment.Source.INTERNAL,
                "notes":"Teste",
            },
        )
        self.assertEqual(response.status_code,302)
        appointment=Appointment.objects.get()
        self.assertEqual(int((appointment.ends_at-appointment.starts_at).total_seconds()/60),45)
        self.assertEqual(appointment.service_price_snapshot,Decimal("50.00"))
        self.assertEqual(appointment.created_by,self.user)


class PortalSuperuserTests(TestCase):
    def test_superuser_can_select_tenant(self):
        tenant=Tenant.objects.create(name="Demo",slug="demo",status=Tenant.Status.ACTIVE)
        user=User.objects.create_superuser(email="root@example.test",password="StrongPassword123!")
        self.client.force_login(user)
        response=self.client.get(reverse("portal-select-tenant",args=[tenant.pk]))
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.client.session["portal_tenant_id"],tenant.pk)
