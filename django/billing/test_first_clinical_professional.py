"""The first clinic booking profile belongs to the company and is included."""
from django.test import TestCase
from billing.entitlements import is_healthcare_tenant, professional_capacity
from billing.models import Plan, Subscription
from tenants.models import Tenant
from tenants.onboarding import ProfessionalForm
from django.utils import timezone


class FirstClinicalProfessionalTests(TestCase):
    def test_company_booking_profile_for_each_clinical_segment(self):
        for category in ("fisioterapia", "clinica", "odontologia"):
            with self.subTest(category=category):
                tenant=Tenant.objects.create(name="Clínica Exemplo",slug="clinica-"+category,
                                             category=category,status=Tenant.Status.ACTIVE)
                self.assertTrue(is_healthcare_tenant(tenant))
                form=ProfessionalForm(tenant=tenant)
                self.assertEqual(form.initial["name"],tenant.name)
                self.assertIn("prontuário",form.fields["name"].help_text)
                if category=="odontologia":
                    self.assertEqual(professional_capacity(tenant)["limit"],1)

    def test_medical_and_physiotherapy_plans_have_one_included_seat_without_metadata(self):
        for category in ("clinica","fisioterapia"):
            with self.subTest(category=category):
                tenant=Tenant.objects.create(name="Clínica",slug="test-seat-"+category,
                                             category=category,status=Tenant.Status.ACTIVE)
                plan=Plan.objects.create(name="Plano clínico",slug="seat-plan-"+category,
                                         monthly_price="99.90",features={})
                Subscription.objects.create(tenant=tenant,plan=plan,
                    billing_cycle=Subscription.BillingCycle.MONTHLY,
                    contracted_price="99.90",status=Subscription.Status.ACTIVE,
                    started_at=timezone.now())
                capacity=professional_capacity(tenant)
                self.assertEqual(capacity["plan_limit"],1)
                self.assertEqual(capacity["limit"],1)
                self.assertEqual(capacity["available"],1)
