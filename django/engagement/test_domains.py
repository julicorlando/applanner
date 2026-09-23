from unittest.mock import patch

from django.test import TestCase
from accounts.models import User
from engagement.domains import create_tenant_domain,verify_tenant_domain
from engagement.models import TenantDomain
from tenants.models import Tenant


class DomainVerificationTests(TestCase):
    def test_txt_verification_activates_domain(self):
        tenant=Tenant.objects.create(name="Domain",slug="domain")
        row=create_tenant_domain(tenant=tenant,domain="agenda.example.test")
        answer=type("Answer",(),{"strings":[f"applanner-verification={row.verification_token}".encode()]})()
        with patch("engagement.domains.dns.resolver.resolve",return_value=[answer]):
            self.assertTrue(verify_tenant_domain(row))
        row.refresh_from_db()
        self.assertEqual(row.status,TenantDomain.Status.VERIFIED)
