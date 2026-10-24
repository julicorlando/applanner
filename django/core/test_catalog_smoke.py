from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from core.master import MASTER_RESOURCES
from core.portal import PORTAL_MODULES
from tenants.models import Tenant


class MasterCatalogSmokeTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_superuser(
            email="master-smoke@example.test",password="StrongPassword123!"
        )
        self.client.force_login(self.user)

    def test_all_master_resource_lists_render(self):
        for slug in MASTER_RESOURCES:
            with self.subTest(resource=slug):
                response=self.client.get(reverse("master-resource-list",args=[slug]))
                self.assertEqual(response.status_code,200)


class PortalCatalogSmokeTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Smoke",slug="smoke")
        self.user=User.objects.create_superuser(
            email="portal-smoke@example.test",password="StrongPassword123!"
        )
        self.client.force_login(self.user)
        session=self.client.session
        session["portal_tenant_id"]=self.tenant.pk
        session.save()

    def test_all_portal_resources_resolve(self):
        for module_slug,module in PORTAL_MODULES.items():
            for resource_slug in module["resources"]:
                with self.subTest(module=module_slug,resource=resource_slug):
                    response=self.client.get(
                        reverse("portal-resource-list",args=[module_slug,resource_slug])
                    )
                    self.assertIn(response.status_code,{200,302})
