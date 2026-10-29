from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from billing.models import Module, TenantModule
from scheduling.models import Professional
from tenants.models import Tenant


class ClinicalDashboardSetupTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Clínica Fisio",slug="fisio-clinical-setup",category="fisioterapia")
        self.owner=User.objects.create_user(
            email="owner-fisio-setup@example.test",password="GoodPassword123!",
            tenant=self.tenant,role="owner",
        )
        self.client.force_login(self.owner)

    def test_unlicensed_owner_sees_setup_not_records(self):
        module=Module.objects.create(slug="medical_records",name="Prontuários",active=True)
        TenantModule.objects.create(tenant=self.tenant,module=module,enabled=True)
        response=self.client.get(reverse("clinical-dashboard"))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"vinculada a um profissional clínico autorizado")
        self.assertNotIn("patients",response.context)

    def test_unentitled_owner_sees_module_activation_not_403(self):
        response=self.client.get(reverse("clinical-dashboard"))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"medical_records")

    def test_reception_cannot_use_activation_to_bypass_permissions(self):
        reception=User.objects.create_user(email="recepcao-fisio@example.test",
            password="GoodPassword123!",tenant=self.tenant,role="reception")
        self.client.force_login(reception)
        response=self.client.get(reverse("clinical-dashboard"))
        self.assertEqual(response.status_code,403)
