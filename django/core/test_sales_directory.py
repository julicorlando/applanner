from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.models import Module, Plan, PlanModule, Subscription
from core.master import PlanMasterForm
from commercial.models import Lead
from tenants.models import Tenant, Unit


class PublicSalesTests(TestCase):
    def test_master_can_select_segments_without_changing_legacy_plans(self):
        plan=Plan.objects.create(name="Personalizado",slug="master-segment",features={"units":1})
        data={"name":plan.name,"slug":plan.slug,"monthly_price":"50.00","trial_days":"7","sort_order":"0",
              "active":"on","public_visible":"on","segments":["barbearia"]}
        form=PlanMasterForm(data,instance=plan)
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(form.save().features["segments"],["barbearia"])

    def test_empty_catalog_is_seeded_once_and_master_changes_survive(self):
        call_command("seed_modules",verbosity=0)
        call_command("seed_sales_plans",verbosity=0)
        self.assertEqual(Plan.objects.filter(public_visible=True).count(),3)
        pro=Plan.objects.get(slug="sales-pro")
        self.assertEqual(pro.trial_days,7)
        pro.monthly_price=42
        pro.save()
        call_command("seed_sales_plans",verbosity=0)
        pro.refresh_from_db()
        self.assertEqual(pro.monthly_price,42)
        self.assertContains(self.client.get(reverse("home")),"Começar teste grátis")

    def test_monte_o_seu_creates_a_lead_with_only_active_modules(self):
        module=Module.objects.create(slug="finance",name="Financeiro")
        response=self.client.post(reverse("billing-custom-plan"),{
            "name":"Júlio","business_type":"Barbearia","email":"julio@example.com",
            "phone":"81999999999","modules":[module.pk],"consent":"on",
        })
        self.assertEqual(response.status_code,302)
        lead=Lead.objects.get(email="julio@example.com")
        self.assertEqual(lead.source,"custom_plan")
        self.assertTrue(lead.consent_granted)
        self.assertIn("Financeiro",lead.notes)

    def test_directory_renders_html_nearest_unit_and_keeps_api(self):
        tenant=Tenant.objects.create(name="Barbearia Centro",slug="centro",public_slug="centro",status=Tenant.Status.TRIAL,public_enabled=True)
        Unit.objects.create(tenant=tenant,name="Longe",latitude=-8.5,longitude=-35.0,city="Outra")
        Unit.objects.create(tenant=tenant,name="Perto",latitude=-8.0,longitude=-35.0,city="Recife")
        response=self.client.get(reverse("public-directory"),{"lat":"-8.0","lon":"-35.0"})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"Recife")
        self.assertContains(response,"/p/centro/")
        self.assertEqual(self.client.get(reverse("public-directory-api")).json()["results"][0]["name"],"Barbearia Centro")
        self.assertEqual(self.client.get(reverse("tenant-public",args=["centro"])).status_code,200)

    def test_barber_tenant_cannot_open_auto_or_arena_resources(self):
        tenant=Tenant.objects.create(name="Corte",slug="corte",category="Barbearia")
        user=User.objects.create_user(email="corte@example.com",password="ValidPassword2026!",tenant=tenant,role="owner")
        self.client.force_login(user)
        response=self.client.get(reverse("portal-home"))
        self.assertNotContains(response,"Arenas &amp; Quadras")
        self.assertNotContains(response,"Veículos")
        self.assertEqual(self.client.get(reverse("portal-resource-list",args=["auto","veiculos"])).status_code,403)

    def test_plan_modules_restrict_resource_even_when_owner_has_broad_role(self):
        tenant=Tenant.objects.create(name="Corte",slug="corte-pro",category="Barbearia")
        user=User.objects.create_user(email="pro@example.com",password="ValidPassword2026!",tenant=tenant,role="owner")
        plan=Plan.objects.create(name="Pro",slug="pro-limited")
        finance=Module.objects.create(name="Financeiro",slug="finance")
        Module.objects.create(name="Produtos",slug="products")
        PlanModule.objects.create(plan=plan,module=finance)
        Subscription.objects.create(tenant=tenant,plan=plan,started_at=timezone.now(),status=Subscription.Status.ACTIVE)
        self.client.force_login(user)
        response=self.client.get(reverse("portal-home"))
        self.assertContains(response,"Lançamentos")
        self.assertNotContains(response,"PDV / Vendas")
        self.assertEqual(self.client.get(reverse("portal-resource-list",args=["financeiro","produtos"])).status_code,403)
        self.assertEqual(self.client.get(reverse("finance-pos")).status_code,403)

    def test_master_segment_selection_blocks_segment_routes(self):
        tenant=Tenant.objects.create(name="Oficina",slug="oficina",category="Automotivo")
        user=User.objects.create_user(email="oficina@example.com",password="ValidPassword2026!",tenant=tenant,role="owner")
        plan=Plan.objects.create(name="Só agenda",slug="so-agenda",features={"segments":["barbearia"]})
        Subscription.objects.create(tenant=tenant,plan=plan,started_at=timezone.now(),status=Subscription.Status.ACTIVE)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("portal-resource-list",args=["auto","veiculos"])).status_code,403)
