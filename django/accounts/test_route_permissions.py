from django.test import TestCase
from django.urls import reverse

from accounts.models import Capability,PlatformRole,RoleCapability,User,UserRole
from tenants.models import Tenant


class CapabilityRouteTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="RBAC",slug="rbac-tenant")
        self.user=User.objects.create_user(email="rbac-route@example.com",password="StrongPassword123!",tenant=self.tenant)
        role=PlatformRole.objects.create(slug="finance-only-test",name="Finance only")
        cap=Capability.objects.create(slug="finance.manage",name="Finance")
        RoleCapability.objects.create(role=role,capability=cap)
        UserRole.objects.create(user=self.user,role=role)
        self.client.force_login(self.user)

    def test_allowed_module(self):
        self.assertEqual(self.client.get(reverse("portal-resource-list",args=["financeiro","produtos"])).status_code,200)

    def test_denied_module(self):
        self.assertEqual(self.client.get(reverse("portal-resource-list",args=["arena","quadras"])).status_code,403)
