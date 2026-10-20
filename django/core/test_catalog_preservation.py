from contextlib import nullcontext
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from billing.models import Module, Plan, PlanModule


class ReleaseCatalogPreservationTests(TestCase):
    def test_bootstrap_explicitly_preserves_existing_catalog(self):
        with patch("core.management.commands.bootstrap_application.release_initialization_lock",
                   return_value=nullcontext()), patch("core.management.commands.bootstrap_application.call_command") as command:
            call_command("bootstrap_application", verbosity=0)
        for name in ["seed_modules", "seed_sales_plans"]:
            command.assert_any_call(name, verbosity=0, preserve_existing=True)

    def test_module_prices_names_flags_and_custom_modules_survive_repeated_release_seeds(self):
        module, _ = Module.objects.update_or_create(slug="products", defaults={
            "name": "Produtos corrigidos no Master", "addon_monthly_price": Decimal("73.45"),
            "active": False, "addon_sellable": False, "per_unit_billing": True, "sort_order": 37})
        custom, _ = Module.objects.update_or_create(slug="growth", defaults={
            "name": "Módulo adicional já implementado", "active": True, "addon_monthly_price": Decimal("12.34")})
        before = list(Module.objects.filter(pk__in=[module.pk, custom.pk]).order_by("pk").values())
        for _ in range(2):
            call_command("seed_modules", preserve_existing=True, verbosity=0)
        self.assertEqual(list(Module.objects.filter(pk__in=[module.pk, custom.pk]).order_by("pk").values()), before)

    def test_plan_prices_limits_visibility_and_disabled_links_survive_release_seeds(self):
        module, _ = Module.objects.get_or_create(slug="sports_courts", defaults={"name": "Arena"})
        plan, _ = Plan.objects.update_or_create(slug="segment-arena", defaults={
            "name": "Arena ajustada", "monthly_price": Decimal("137.90"), "quarterly_price": Decimal("390.00"),
            "active": False, "public_visible": False, "featured": False, "trial_days": 21,
            "features": {"segments": ["arena"], "courts": 8, "reservations": 120, "custom": "preservar"}})
        link, _ = PlanModule.objects.update_or_create(plan=plan, module=module, defaults={"enabled": False})
        custom = Plan.objects.create(slug="novo-plano-do-master", name="Arena Sports", monthly_price=77,
                                     public_visible=True, featured=True, features={"segments": ["arena"], "courts": 5})
        before = list(Plan.objects.filter(pk__in=[plan.pk, custom.pk]).order_by("pk").values())
        for _ in range(2):
            call_command("seed_sales_plans", preserve_existing=True, verbosity=0)
        self.assertEqual(list(Plan.objects.filter(pk__in=[plan.pk, custom.pk]).order_by("pk").values()), before)
        link.refresh_from_db()
        self.assertFalse(link.enabled)
        self.assertFalse(custom.module_links.exists())

    def test_fresh_install_still_receives_catalog_defaults(self):
        call_command("seed_modules", preserve_existing=True, verbosity=0)
        call_command("seed_sales_plans", preserve_existing=True, verbosity=0)
        plan = Plan.objects.get(slug="segment-barbearia-salao")
        self.assertTrue(plan.module_links.exists())
        self.assertTrue(Module.objects.filter(slug="professional-extra").exists())
