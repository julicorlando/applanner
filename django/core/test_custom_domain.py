from django.test import TestCase,override_settings
from django.urls import reverse

from engagement.models import TenantDomain
from tenants.models import Tenant


class CustomDomainTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(
            name="Studio Teste",slug="studio-teste",public_slug="studio",
            status=Tenant.Status.ACTIVE,public_enabled=True,
        )
        TenantDomain.objects.create(
            tenant=self.tenant,domain="agenda.example.test",
            status=TenantDomain.Status.VERIFIED,verification_token="token",
        )

    @override_settings(ALLOWED_HOSTS=["testserver","agenda.example.test"])
    def test_verified_host_resolves_public_tenant(self):
        response=self.client.get("/",HTTP_HOST="agenda.example.test")
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"Studio Teste")

    def test_public_slug_page(self):
        response=self.client.get(reverse("tenant-public",kwargs={"slug":"studio"}))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"Studio Teste")
