from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.models import Module,Plan,PlanModule,Subscription,TenantModule
from tenants.models import Tenant


class ContractedModuleVisibilityTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Arena Norte",slug="arena-norte",category="arena",status=Tenant.Status.ACTIVE)
        self.owner=User.objects.create_user(email="arena-owner@example.test",password="StrongPassword123!",
            tenant=self.tenant,role="owner")
        self.plan=Plan.objects.create(name="Plano Arena Real",slug="arena-real",features={"segments":["arena"]})
        Subscription.objects.create(tenant=self.tenant,plan=self.plan,status=Subscription.Status.ACTIVE,
            started_at=timezone.now())
        self.courts=Module.objects.create(name="Quadras contratadas",slug="sports_courts",active=True)
        self.academy=Module.objects.create(name="Escolinha adicional",slug="sports_academy",active=True)
        self.tournaments=Module.objects.create(name="Torneios",slug="sports_tournaments",active=True)
        PlanModule.objects.create(plan=self.plan,module=self.courts,enabled=True)
        self.client.force_login(self.owner)

    def test_addon_appears_for_tenant_and_locked_resource_does_not(self):
        url=reverse("portal-home")
        page=self.client.get(url)
        self.assertContains(page,"Quadras contratadas")
        self.assertNotContains(page,"Escolinha adicional")
        self.assertNotContains(page,"Torneios</h3>")
        self.assertEqual(self.client.get(reverse("portal-resource-list",args=["arena","turmas"])).status_code,403)
        TenantModule.objects.create(tenant=self.tenant,module=self.academy,enabled=True)
        page=self.client.get(url)
        self.assertContains(page,"Escolinha adicional")
        self.assertContains(page,reverse("portal-resource-list",args=["arena","turmas"]))
        self.assertEqual(self.client.get(reverse("portal-resource-list",args=["arena","turmas"])).status_code,200)
        TenantModule.objects.create(tenant=self.tenant,module=self.courts,enabled=False)
        self.assertNotContains(self.client.get(url),"Quadras contratadas")

    def test_another_company_cannot_see_these_purchases(self):
        other=Tenant.objects.create(name="Arena Sul",slug="arena-sul",category="arena",status=Tenant.Status.ACTIVE)
        other_plan=Plan.objects.create(name="Sem quadras",slug="sem-quadras",features={"segments":["arena"]})
        Subscription.objects.create(tenant=other,plan=other_plan,status=Subscription.Status.ACTIVE,
            started_at=timezone.now())
        another=User.objects.create_user(email="other-arena@example.test",password="StrongPassword123!",
            tenant=other,role="owner")
        self.client.force_login(another)
        self.assertNotContains(self.client.get(reverse("portal-home")),"Quadras contratadas")
        self.assertEqual(self.client.get(reverse("portal-resource-list",args=["arena","quadras"])).status_code,403)
