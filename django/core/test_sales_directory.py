from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.models import Module, Plan, PlanModule, Subscription
from billing.views import SignupForm
from billing.segment_access import segment_enabled
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

    def test_segment_catalog_preserves_legacy_subscriptions_and_master_changes(self):
        call_command("seed_modules",verbosity=0)
        old=Plan.objects.create(name="Inicial",slug="sales-start",monthly_price=49,public_visible=True)
        tenant=Tenant.objects.create(name="Cliente antigo",slug="cliente-antigo",category="arena")
        Subscription.objects.create(tenant=tenant,plan=old,started_at=timezone.now(),status=Subscription.Status.ACTIVE)
        call_command("seed_sales_plans",verbosity=0)
        self.assertEqual(Plan.objects.filter(public_visible=True).count(),3)
        self.assertFalse(Plan.objects.get(pk=old.pk).public_visible)
        self.assertEqual(Subscription.objects.get(tenant=tenant).plan_id,old.pk)
        arena=Plan.objects.get(slug="segment-arena")
        self.assertEqual(arena.features["segments"],["arena"])
        self.assertTrue(arena.module_links.filter(module__slug="sports_courts",enabled=True).exists())
        self.assertEqual(arena.trial_days,7)
        self.assertEqual(Plan.objects.get(slug="segment-medico").active,False)
        arena.monthly_price=42
        arena.save()
        call_command("seed_sales_plans",verbosity=0)
        arena.refresh_from_db()
        self.assertEqual(arena.monthly_price,42)
        self.assertEqual(Plan.objects.filter(slug__startswith="segment-").count(),4)
        self.assertContains(self.client.get(reverse("home")),"Começar teste grátis")
        self.assertContains(self.client.get(reverse("billing-plans")),"Médico / Clínica")

    def test_signup_respects_segment_and_medical_is_unavailable(self):
        call_command("seed_modules",verbosity=0)
        call_command("seed_sales_plans",verbosity=0)
        arena=Plan.objects.get(slug="segment-arena")
        form=SignupForm(selected_plan=arena)
        choices=[key for key,_ in form.fields["category"].widget.choices]
        self.assertEqual(choices,["","arena"])
        data={"plan":arena.pk,"billing_cycle":"monthly","business_name":"Arena Nova",
              "category":"barbearia","owner_name":"Titular","email":"titular@example.test",
              "password":"SenhaSegura2026!","password_confirm":"SenhaSegura2026!"}
        self.assertFalse(SignupForm(data,selected_plan=arena).is_valid())
        legacy=Plan.objects.create(name="Legado",slug="legacy-arena",monthly_price=40,
            features={"segments":["arena"]},public_visible=True,active=True)
        legacy_data={**data,"plan":legacy.pk,"category":"arena"}
        self.assertTrue(SignupForm(legacy_data).is_valid())
        self.assertContains(self.client.get(reverse("billing-plans")),"Em preparação")
        data["category"]="clinica"
        self.assertFalse(SignupForm(data).is_valid())
        self.assertFalse(Plan.objects.filter(slug="segment-medico",active=True).exists())

        data.update(category="arena")
        response=self.client.post(reverse("billing-signup"),data)
        self.assertEqual(response.status_code,302)
        tenant=Tenant.objects.get(name="Arena Nova")
        self.assertTrue(segment_enabled(tenant,"arena"))
        self.assertFalse(segment_enabled(tenant,"barbearia"))
        self.assertEqual(Subscription.objects.get(tenant=tenant).plan,arena)

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
