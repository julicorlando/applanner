import re
from datetime import timedelta
from unittest.mock import patch
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from tenants.models import Tenant, Unit
from scheduling.models import Customer, Service, Appointment, CustomerAccessChallenge


class CustomerPortalTests(TestCase):
    def setUp(self):
        self.limit = patch(
            "scheduling.customer_portal.attempt_budget", return_value=("test-budget", 0)
        )
        self.limit.start()
        self.addCleanup(self.limit.stop)
        self.tenant = Tenant.objects.create(
            name="Empresa",
            slug="portal-tenant",
            public_slug="portal-tenant",
            public_enabled=True,
            status="active",
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name="Cliente protegido",
            email="portal-customer@example.test",
        )
        self.unit = Unit.objects.create(tenant=self.tenant, name="Centro")
        self.service = Service.objects.create(
            tenant=self.tenant, name="Serviço próprio", duration_minutes=30, price=40
        )
        Appointment.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            customer=self.customer,
            service=self.service,
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(minutes=30),
        )
        self.url = reverse("customer-portal", args=[self.tenant.slug])

    def send(self, email=None):
        return self.client.post(
            self.url, {"action": "send", "email": email or self.customer.email}
        )

    def code(self):
        return re.search(r": (\d{6})\.", mail.outbox[-1].body).group(1)

    def test_anonymous_cannot_read_customer_name_or_history(self):
        response = self.client.get(self.url)
        self.assertNotContains(response, self.customer.name)
        self.assertNotContains(response, self.service.name)
        self.assertIn("no-store", response["Cache-Control"])

    def test_verified_identity_only_sees_own_company_and_customer(self):
        outsider = Customer.objects.create(
            tenant=self.tenant,
            name="Não deve aparecer",
            email="other-customer@example.test",
        )
        Appointment.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            customer=outsider,
            service=self.service,
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(minutes=30),
        )
        self.send()
        self.client.post(self.url, {"action": "verify", "code": self.code()})
        response = self.client.get(self.url)
        self.assertContains(response, self.customer.name)
        self.assertContains(response, self.service.name)
        self.assertNotContains(response, outsider.name)
        self.assertIsNotNone(CustomerAccessChallenge.objects.get().used_at)

    def test_unknown_email_receives_same_notice_and_no_message(self):
        response = self.send("unknown@example.test")
        self.assertContains(response, "Se esse e-mail estiver cadastrado")
        self.assertEqual(len(mail.outbox), 0)

    def test_wrong_or_expired_code_does_not_grant_access(self):
        self.send()
        row = CustomerAccessChallenge.objects.get()
        row.expires_at = timezone.now() - timedelta(seconds=1)
        row.save()
        response = self.client.post(self.url, {"action": "verify", "code": self.code()})
        self.assertContains(response, "Código inválido ou expirado")
        self.assertNotIn(f"customer-portal:{self.tenant.pk}", self.client.session)

    def test_email_change_invalidates_existing_code(self):
        self.send()
        code = self.code()
        self.customer.email = "new@example.test"
        self.customer.save()
        response = self.client.post(self.url, {"action": "verify", "code": code})
        self.assertContains(response, "Código inválido ou expirado")

    def test_email_ambiguity_does_not_expose_multiple_customers(self):
        Customer.objects.create(
            tenant=self.tenant, name="Outra identidade", email=self.customer.email
        )
        self.send()
        self.assertEqual(len(mail.outbox), 0)

    def test_logout_revokes_portal_session(self):
        self.send()
        self.client.post(self.url, {"action": "verify", "code": self.code()})
        self.client.post(self.url, {"action": "logout"})
        self.assertNotContains(self.client.get(self.url), self.customer.name)
