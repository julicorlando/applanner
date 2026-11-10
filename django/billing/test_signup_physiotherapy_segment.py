"""Regression checks for healthcare segments in the public signup flow."""
from django.test import TestCase

from billing.models import Plan
from billing.views import SignupForm, plan_categories


class PhysiotherapySignupSegmentTests(TestCase):
    def make_plan(self, slug, segments):
        return Plan.objects.create(
            name="Fisioterapia" if "fisio" in slug else "Plano de teste",
            slug=slug,
            monthly_price="99.90",
            active=True,
            public_visible=True,
            features={"segments": segments},
        )

    def test_physio_health_plan_offers_clinic_without_medical_launch(self):
        plan = self.make_plan("fisioterapia-qa", ["saude"])
        form = SignupForm(selected_plan=plan)
        self.assertIn(("clinica", "Médico / Clínica"), list(form.fields["category"].widget.choices))

    def test_physio_specific_segment_alias_offers_clinic(self):
        plan = self.make_plan("fisioterapia-alias-qa", ["fisioterapia"])
        form = SignupForm(selected_plan=plan)
        self.assertIn(("clinica", "Médico / Clínica"), list(form.fields["category"].widget.choices))

    def test_non_health_plan_does_not_offer_clinic(self):
        plan = self.make_plan("barber-qa", ["barbearia"])
        form = SignupForm(selected_plan=plan)
        self.assertNotIn("clinica", [key for key, _ in form.fields["category"].widget.choices])

    def test_plan_categories_filters_only_allowed_segments(self):
        choices = [("", "Selecione"), ("barbearia", "Barbearia"), ("clinica", "Médico / Clínica")]
        plan = self.make_plan("fisioterapia-filter-qa", ["fisioterapia"])
        self.assertEqual(plan_categories(plan, choices), [("", "Selecione"), ("clinica", "Médico / Clínica")])
