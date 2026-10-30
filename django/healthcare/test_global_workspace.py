from datetime import timedelta
from django.test import TestCase, RequestFactory
from django.urls import reverse, resolve
from django.utils import timezone
from django.templatetags.static import static
from billing.models import Module, TenantModule
from scheduling.models import Appointment, Customer
from . import test_clinical_security as fixtures
from . import test_assessments as assessment_fixtures
from .navigation import shell_context, workspace_enabled
from core.workspace import navigation


class GlobalPhysioWorkspaceTests(TestCase):
    def create(self, **kwargs):
        return fixtures.ClinicalSecurityTests.create(self, **kwargs)

    def setUp(self):
        assessment_fixtures.AssessmentTests.setUp(self)

    def request(self, path, user=None):
        req = RequestFactory().get(path)
        req.user = user or self.owner
        req.session = {}
        req.resolver_match = resolve(path)
        return req

    def test_owner_has_reference_menu_across_operational_pages(self):
        self.client.force_login(self.owner)
        pages = [
            ("operation-calendar", [], "Agenda"),
            ("portal-resource-list", ["agenda", "clientes"], "Pacientes"),
            ("portal-resource-create", ["agenda", "clientes"], "Pacientes"),
            ("operation-today", [], "Atendimentos"),
            ("portal-resource-list", ["financeiro", "lancamentos"], "Financeiro"),
            ("operation-performance", [], "Relatórios"),
            ("physio-settings", [], "Configurações"),
            ("physio-dashboard", [], "Dashboard"),
        ]
        for name, args, active in pages:
            with self.subTest(name=name, args=args):
                url = reverse(name, args=args)
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'id="pa-sidebar"', count=1)
                self.assertContains(response, 'class="pa-topbar"', count=1)
                self.assertContains(response, static("healthcare/physio-workspace.css"))
                self.assertNotContains(response, 'id="workspace-sidebar"')
                self.assertEqual(
                    [
                        item["title"]
                        for item in response.context["physio_menu"]
                        if item["active"]
                    ],
                    [active],
                )
                self.assertEqual(
                    [item["title"] for item in response.context["physio_menu"]],
                    [
                        "Dashboard",
                        "Agenda",
                        "Pacientes",
                        "Atendimentos",
                        "Fisioterapia",
                        "Financeiro",
                        "Relatórios",
                        "Configurações",
                    ],
                )

    def test_home_redirects_existing_owner_and_professional_to_physio_dashboard(self):
        for user in (self.owner, self.doctor, self.reception):
            self.client.force_login(user)
            for url in ("/", reverse("portal-home")):
                self.assertRedirects(
                    self.client.get(url),
                    reverse("physio-dashboard"),
                    fetch_redirect_response=False,
                )

    def test_reception_keeps_administrative_access_without_clinical_access(self):
        self.client.force_login(self.reception)
        for name in ("physio-dashboard", "physio-settings", "operation-calendar"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Menu Fisioterapia")
            self.assertContains(response, "Recepção")
            clinical = next(
                item
                for item in response.context["physio_menu"]
                if item["title"] == "Fisioterapia"
            )
            self.assertIsNone(clinical["url"])
            self.assertNotContains(response, "Informação clínica de teste")
        self.assertEqual(
            self.client.get(reverse("physio-assessments")).status_code, 403
        )
        self.assertEqual(
            self.client.get(reverse("physio-assessment-create")).status_code, 403
        )

    def test_other_segment_and_master_keep_original_navigation(self):
        self.tenant.category = "barbearia"
        self.tenant.save()
        TenantModule.objects.filter(tenant=self.tenant, module__slug="dentistry").delete()
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("portal-resource-list", args=["agenda", "clientes"])
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="pa-sidebar"')
        self.assertNotContains(response, static("healthcare/physio-workspace.css"))
        self.tenant.category = "fisioterapia"
        self.tenant.save()
        self.client.force_login(self.master)
        req = self.request(reverse("portal-home"), self.master)
        self.assertFalse(workspace_enabled(req))
        self.assertNotIn("physio_workspace", navigation(req))

    def test_module_only_existing_clinic_gets_global_skin(self):
        self.tenant.category = "saude"
        self.tenant.save()
        module, _ = Module.objects.get_or_create(
            slug="physiotherapy", defaults={"name": "Fisioterapia"}
        )
        TenantModule.objects.create(tenant=self.tenant, module=module, enabled=True)
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("portal-resource-list", args=["agenda", "clientes"])
        )
        self.assertContains(response, 'id="pa-sidebar"')
        self.assertTrue(response.context["physio_workspace"])
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.category, "saude")

    def test_simple_mode_does_not_restore_barber_navigation(self):
        self.tenant.simple_mode = True
        self.tenant.save()
        self.client.force_login(self.owner)
        response = self.client.get(reverse("physio-dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="pa-sidebar"', count=1)
        self.assertNotContains(response, "Gerenciar barbearia")
        self.assertEqual(len(response.context["physio_menu"]), 8)

    def test_public_booking_and_anonymous_pages_do_not_get_private_skin(self):
        req = RequestFactory().get("/directory/")
        req.user = self.owner
        self.assertFalse(workspace_enabled(req))
        from django.contrib.auth.models import AnonymousUser

        req = RequestFactory().get("/app/")
        req.user = AnonymousUser()
        self.assertFalse(workspace_enabled(req))

    def test_billing_lock_keeps_only_payment_and_account_destinations(self):
        req = self.request(reverse("billing-subscription-status"))
        req.billing_locked = True
        context = shell_context(self.owner, req)
        for item in context["physio_menu"]:
            if item["title"] not in {"Financeiro", "Configurações"}:
                self.assertIsNone(item["url"])
        self.assertEqual(
            next(
                item for item in context["physio_menu"] if item["title"] == "Financeiro"
            )["url"],
            reverse("billing-subscription-status"),
        )

    def test_professional_dashboard_scopes_appointments_and_patients(self):
        patient = Customer.objects.create(
            tenant=self.tenant, name="Paciente de outro profissional"
        )
        start = timezone.now() - timedelta(minutes=5)
        Appointment.objects.create(
            tenant=self.tenant,
            professional=self.colleague_profile,
            customer=patient,
            service=self.appointment.service,
            starts_at=start,
            ends_at=start + timedelta(minutes=30),
            status="completed",
        )
        self.client.force_login(self.doctor)
        response = self.client.get(reverse("physio-dashboard"))
        self.assertNotContains(response, patient.name)
        self.assertEqual(response.context["stats"]["patients"], 1)
        response = self.client.get(reverse("physio-settings"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response, reverse("portal-resource-list", args=["agenda", "profissionais"])
        )
        self.assertContains(response, "Identificação profissional e CREFITO")

    def test_settings_retains_existing_management_tools_and_logout(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("physio-settings"))
        for text in (
            "Plano e assinatura",
            "Acesso da recepção",
            "Segurança da conta",
            "Sair da conta",
            "Serviços",
        ):
            self.assertContains(response, text)
