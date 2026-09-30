from django.apps import apps
from django.test import SimpleTestCase

from core.labels import FIELD_LABELS
from core.master import MASTER_RESOURCES, _config
from core.portal import PORTAL_MODULES, _headers, _model_form


class PortugueseCatalogLabelsTests(SimpleTestCase):
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
        self.assertEqual(form.fields["phone"].label, "Telefone")
        self.assertEqual(_headers(model, ["created_at", "phone"]), ["Criado em", "Telefone"])

    def test_master_plan_column_is_named_in_portuguese(self):
        config, model = _config("assinaturas")
        self.assertIn("plan", config["columns"])
        self.assertEqual(FIELD_LABELS["plan"], "Plano")
