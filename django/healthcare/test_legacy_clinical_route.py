"""Legacy medical record navigation must reach the secure clinic dashboard."""
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from tenants.models import Tenant


class LegacyClinicalRouteTests(TestCase):
    def test_physiotherapy_owner_legacy_route_redirects_to_clinical_dashboard(self):
        tenant=Tenant.objects.create(name="Fisioterapia Teste",slug="fisio-legacy-route",category="fisioterapia")
        owner=User.objects.create_user(
            email="fisio-legacy-route@example.test",password="StrongPassword2026!",
            tenant=tenant,role="owner",
        )
        self.client.force_login(owner)
        response=self.client.get("/app/saude/prontuarios/")
        self.assertEqual(response.status_code,302)
        self.assertEqual(response.url,reverse("clinical-dashboard"))
        landing=self.client.get(response.url)
        self.assertEqual(landing.status_code,200)
        self.assertContains(landing,"Prontuários clínicos")
