from django.apps import apps
from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils import timezone

from datetime import datetime

from core.labels import FIELD_LABELS
from core.master import MASTER_RESOURCES, _config
from core.portal import PORTAL_MODULES, _headers, _model_form
from core.templatetags.display_pt import notification_type_pt, payment_method_pt


class PortugueseCatalogLabelsTests(SimpleTestCase):
    def test_portuguese_is_the_only_supported_interface_language(self):
        self.assertEqual([code for code, _ in settings.LANGUAGES], ["pt-br"])

    def test_every_catalog_field_has_a_portuguese_label(self):
        names = {name for config in MASTER_RESOURCES.values()
                 for name in config["fields"] + config["columns"]}
        names.update(name for module in PORTAL_MODULES.values()
                     for resource in module["resources"].values()
                     for name in resource["fields"] + resource["columns"])
        self.assertEqual(names - FIELD_LABELS.keys(), set())

    def test_portal_form_and_headers_show_translated_labels(self):
        resource = PORTAL_MODULES["agenda"]["resources"]["clientes"]
        model = apps.get_model(resource["model"])
        form = _model_form(model, resource)
        self.assertEqual(form.fields["birth_date"].label, "Data de nascimento")
        self.assertEqual(form.fields["phone"].label, "Telefone com DDD")
        self.assertTrue(form.fields["phone"].required)
        self.assertEqual(_headers(model, ["created_at", "phone"]), ["Criado em", "Telefone"])

    def test_master_plan_column_is_named_in_portuguese(self):
        config, model = _config("assinaturas")
        self.assertIn("plan", config["columns"])
        self.assertEqual(FIELD_LABELS["plan"], "Plano")

    def test_legacy_payment_and_notification_codes_are_presented_in_portuguese(self):
        self.assertEqual(payment_method_pt("credit_card"), "Cartão de crédito")
        self.assertEqual(payment_method_pt("pix"), "Pix")
        self.assertEqual(notification_type_pt("appointment_reminder"), "Lembrete de agendamento")
        self.assertEqual(payment_method_pt("forma não mapeada"), "forma não mapeada")

    def test_security_pages_share_the_single_portal_layout(self):
        challenge = render_to_string("accounts/two_factor_challenge.html")
        codes = render_to_string("accounts/recovery_codes.html", {"codes": ["CODIGO-TESTE"]})
        for html in (challenge, codes):
            self.assertEqual(html.count('<main id="conteudo">'), 1)
            self.assertNotIn('<main class="container"', html)
            self.assertIn('class="shell portal-page narrow security-page"', html)
        self.assertIn("CODIGO-TESTE", codes)

    def test_catalog_choices_use_names_instead_of_generic_object_ids(self):
        from arena.models import SportsClass
        from auto.models import ServiceBay
        from billing.models import Plan
        from engagement.models import ServicePackage
        from finance.models import FinancialCategory, PlatformFinanceCategory, Product
        from scheduling.models import Appointment, Customer

        self.assertEqual(str(Plan(name="Essencial")), "Essencial")
        self.assertEqual(str(SportsClass(name="Futebol infantil")), "Futebol infantil")
        self.assertEqual(str(ServiceBay(name="Box 1")), "Box 1")
        self.assertEqual(str(ServicePackage(name="Mensalidade Bronze")), "Mensalidade Bronze")
        self.assertEqual(str(FinancialCategory(name="Aluguel")), "Aluguel")
        self.assertEqual(str(PlatformFinanceCategory(name="Receitas da plataforma")), "Receitas da plataforma")
        self.assertEqual(str(Product(name="Shampoo")), "Shampoo")
        appointment = Appointment(customer=Customer(pk=12, name="Ana"), starts_at=timezone.make_aware(datetime(2026, 10, 1, 15)))
        self.assertEqual(str(appointment), "Ana — 01/10/2026 15:00")
