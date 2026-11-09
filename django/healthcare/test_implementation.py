from datetime import date, timedelta
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from . import test_dental_assessments as dental
from .dental_assessment_forms import AssessmentForm
from .dental_assessment_services import save_assessment
from .dentistry import dental_history
from .implementation import open_period, close_period, active_period, tenant_today, MAX_DAYS
from .services import create_record


class ImplementationTranscriptionTests(TestCase):
    def create(self, **kwargs):
        return dental.DentalAssessmentTests.create(self, **kwargs)

    def setUp(self):
        dental.DentalAssessmentTests.setUp(self)

    def data(self, **changes):
        return dental.DentalAssessmentTests.data(self, **changes)

    def transcribe(self, when="2020-05-10", **changes):
        values = self.data(evaluation_date=when, implementation_transcription="on", attestation="on", **changes)
        values.pop("appointment", None)
        form = AssessmentForm(values, user=self.doctor, finalizing=True)
        self.assertTrue(form.is_valid(), form.errors)
        return save_assessment(form=form, user=self.doctor, finalize=True)

    def test_without_period_backdating_is_refused(self):
        self.assertNotIn("implementation_transcription", AssessmentForm(user=self.doctor).fields)
        with self.assertRaises(ValidationError):
            create_record(tenant=self.tenant, customer=self.patient, professional=self.professional,
                          user=self.doctor, title="X", content="Y", record_type="procedure",
                          clinical_date=date(2020, 1, 1))
        with self.assertRaises(ValidationError):
            create_record(tenant=self.tenant, customer=self.patient, professional=self.professional,
                          user=self.doctor, title="X", content="Y", record_type="procedure",
                          clinical_date=date(2020, 1, 1), transcription=True)

    def test_owner_opens_period_and_dentist_transcribes_with_original_date(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("dental-implementation"), {
            "action": "open", "ends_on": (tenant_today(self.tenant) + timedelta(days=30)).isoformat()})
        self.assertEqual(response.status_code, 302)
        period = active_period(self.tenant)
        self.assertIsNotNone(period)
        row = self.transcribe()
        entry = row.final_entry
        self.assertEqual(entry.clinical_date, date(2020, 5, 10))
        self.assertEqual(entry.transcribed_in_period, period)
        self.assertEqual(timezone.localtime(entry.created_at).date(), timezone.localdate())
        self.assertIsNone(entry.appointment_id)
        self.assertIsNone(row.treatment_plan_id)
        self.assertIn("transcrito", entry.title)
        # Atendimento atual registrado depois aparece após o histórico transcrito.
        current = dental.DentalAssessmentTests.save(self, final=True)
        history = dental_history(tenant=self.tenant, customer=self.patient, user=self.doctor)
        self.assertEqual([item["entry_id"] for item in history], [entry.pk, current.final_entry_id])
        self.assertTrue(history[0]["transcribed"])
        self.client.force_login(self.doctor)
        self.assertContains(self.client.get(reverse("clinical-record", args=[entry.pk])), "transcrito na implantação")

    def test_future_date_and_closed_period_are_refused(self):
        open_period(tenant=self.tenant, user=self.owner, ends_on=tenant_today(self.tenant))
        future = (tenant_today(self.tenant) + timedelta(days=2)).isoformat()
        values = self.data(evaluation_date=future, implementation_transcription="on", attestation="on")
        values.pop("appointment", None)
        form = AssessmentForm(values, user=self.doctor, finalizing=True)
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaises(ValidationError):
            save_assessment(form=form, user=self.doctor, finalize=True)
        close_period(tenant=self.tenant, user=self.owner)
        self.assertIsNone(active_period(self.tenant))
        values["submission_key"] = dental.DentalAssessmentTests.data(self)["submission_key"]
        form = AssessmentForm(values, user=self.doctor, finalizing=True)
        self.assertFalse(form.is_valid())  # sem implantação, o atendimento volta a ser obrigatório

    def test_only_clinic_manager_controls_period_and_length_is_limited(self):
        today = tenant_today(self.tenant)
        for user in (self.doctor, self.reception):
            with self.assertRaises(PermissionDenied):
                open_period(tenant=self.tenant, user=user, ends_on=today)
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("dental-implementation")).status_code, 403)
        with self.assertRaises(ValidationError):
            open_period(tenant=self.tenant, user=self.owner, ends_on=today + timedelta(days=MAX_DAYS + 1))
        open_period(tenant=self.tenant, user=self.owner, ends_on=today)
        with self.assertRaises(ValidationError):
            open_period(tenant=self.tenant, user=self.owner, ends_on=today)
