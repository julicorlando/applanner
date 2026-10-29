import uuid
import hashlib
import json
from datetime import timedelta
from io import BytesIO
from unittest import skipUnless
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction, IntegrityError
from django.test import TestCase, RequestFactory
from django.contrib.messages.storage.fallback import FallbackStorage
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from scheduling.models import Appointment, Service, Customer
from . import test_clinical_security as fixtures
from .models import (
    ClinicalRegistration,
    PhysiotherapyAssessment,
    PhysiotherapyAssessmentVersion,
)
from .assessment_forms import AssessmentForm
from .assessment_services import (
    save_assessment,
    read_assessment,
    assessments_for,
    AssessmentConflict,
    read_assessment_document,
)
from . import assessment_views
from .services import create_record


class AssessmentTests(TestCase):
    def create(self, **kwargs):
        return fixtures.ClinicalSecurityTests.create(self, **kwargs)

    def setUp(self):
        fixtures.ClinicalSecurityTests.setUp(self)
        self.tenant.category = "fisioterapia"
        self.tenant.save()
        ClinicalRegistration.objects.create(
            professional=self.professional,
            council="CREFITO",
            number="12345",
            jurisdiction="1",
            professional_name="Dra. Ana Teste",
        )
        service = Service.objects.create(
            tenant=self.tenant, name="Sessão fictícia", duration_minutes=30, price=30
        )
        start = timezone.now() - timedelta(days=1)
        self.appointment = Appointment.objects.create(
            tenant=self.tenant,
            customer=self.patient,
            professional=self.professional,
            service=service,
            starts_at=start,
            ends_at=start + timedelta(minutes=30),
            status="completed",
        )

    def data(self, **changes):
        data = {
            "submission_key": str(uuid.uuid4()),
            "customer": self.patient.pk,
            "professional": self.professional.pk,
            "evaluation_date": "2026-10-29",
            "version": 0,
            "chief_complaint": "Dor lombar confidencial",
            "body_findings": json.dumps(
                {
                    "lower_back": {
                        "pain": 7,
                        "condition": "pain",
                        "note": "Teste clínico",
                    }
                }
            ),
            "goals": json.dumps([{"text": "Melhorar mobilidade", "achieved": False}]),
            "treatment_plan": json.dumps(
                [{"text": "Exercícios", "frequency": "2x semana"}]
            ),
        }
        data.update(changes)
        return data

    def save(self, row=None, final=False, **changes):
        if row:
            changes.setdefault("version", row.version)
            changes.setdefault("submission_key", str(row.submission_key))
        if final:
            changes.update(appointment=self.appointment.pk, attestation="on")
        form = AssessmentForm(
            self.data(**changes), user=self.doctor, assessment=row, finalizing=final
        )
        self.assertTrue(form.is_valid(), form.errors)
        return save_assessment(
            form=form,
            user=self.doctor,
            assessment_id=row.pk if row else None,
            finalize=final,
        )

    def req(self, user, data=None):
        req = (
            RequestFactory().post("/", data)
            if data is not None
            else RequestFactory().get("/")
        )
        req.user = user
        req.session = {}
        req._messages = FallbackStorage(req)
        return req

    def test_draft_encrypted_roundtrip_versions_and_stale_write(self):
        row = self.save()
        self.assertNotIn("Dor lombar", row.payload_encrypted)
        self.assertEqual(
            read_assessment(assessment=row, user=self.doctor)["sections"][
                "chief_complaint"
            ],
            "Dor lombar confidencial",
        )
        self.save(row, chief_complaint="Revisão")
        row.refresh_from_db()
        self.assertEqual(row.version, 2)
        self.assertEqual(
            read_assessment(assessment=row, user=self.doctor, version=1)["sections"][
                "chief_complaint"
            ],
            "Dor lombar confidencial",
        )
        with self.assertRaises(AssessmentConflict):
            self.save(row, version=1)
        self.assertEqual(row.versions.count(), 2)

    def test_finalize_once_signer_binding_and_immutable_history(self):
        row = self.save()
        row = self.save(row, final=True)
        payload = read_assessment(assessment=row, user=self.doctor)
        self.assertEqual(row.status, "finalized")
        self.assertEqual(payload["signature"]["name"], "Dra. Ana Teste")
        self.assertEqual(row.final_entry.physiotherapy_assessment_id, row.pk)
        self.assertEqual(row.appointment_id, self.appointment.pk)
        self.assertEqual(self.save(row, final=True).final_entry_id, row.final_entry_id)
        with self.assertRaises(ValidationError):
            row.save()
        with self.assertRaises(ValidationError):
            row.versions.first().save()
        with self.assertRaises(ValidationError):
            PhysiotherapyAssessment.objects.filter(pk=row.pk).update(status="draft")

    def test_final_requires_appointment_goals_plan_and_authorship(self):
        form = AssessmentForm(
            self.data(goals="[]", treatment_plan="[]"),
            user=self.doctor,
            finalizing=True,
        )
        self.assertFalse(form.is_valid())
        for key in ("appointment", "goals", "treatment_plan", "attestation"):
            self.assertIn(key, form.errors)

    def test_access_denied_reception_master_owner_other_clinician(self):
        row = self.save()
        for user in (self.reception, self.master, self.owner):
            with self.subTest(user=user.pk), self.assertRaises(PermissionDenied):
                assessments_for(user)
        self.assertFalse(assessments_for(self.colleague).filter(pk=row.pk).exists())
        with self.assertRaises(PermissionDenied):
            read_assessment(assessment=row, user=self.colleague)

    def test_cross_tenant_patient_and_unowned_professional_rejected(self):
        other = Customer.objects.create(tenant=self.other, name="Outro paciente")
        for changes in (
            {"customer": other.pk},
            {"professional": self.colleague_profile.pk},
        ):
            form = AssessmentForm(self.data(**changes), user=self.doctor)
            self.assertFalse(form.is_valid())

    def test_invalid_body_measurements_and_signature_rejected(self):
        for changes in (
            {"body_findings": '{"invalid":{"pain":1}}'},
            {"rom": '[{"text":"Flexão","value":400}]'},
            {"strength": '[{"text":"Quadríceps","value":6}]'},
            {"signature_png": "data:image/svg+xml;base64,PHN2Zz4="},
        ):
            form = AssessmentForm(self.data(**changes), user=self.doctor)
            self.assertFalse(form.is_valid(), changes)

    def test_encrypted_document_validated_and_preserved_on_finalization(self):
        buf = BytesIO()
        Image.new("RGB", (40, 40), "white").save(buf, format="PNG")
        raw = buf.getvalue()
        form = AssessmentForm(
            self.data(),
            {
                "documents": [
                    SimpleUploadedFile("exame.png", raw, content_type="image/png")
                ]
            },
            user=self.doctor,
        )
        self.assertTrue(form.is_valid(), form.errors)
        row = save_assessment(form=form, user=self.doctor)
        doc = row.documents.get()
        self.assertNotEqual(bytes(doc.content_encrypted), raw)
        self.assertEqual(
            read_assessment_document(document=doc, user=self.doctor)[0], raw
        )
        self.save(row, final=True)
        doc.refresh_from_db()
        self.assertIsNotNone(doc.final_document_id)
        with self.assertRaises(ValidationError):
            doc.save()
        with self.assertRaises(PermissionDenied):
            read_assessment_document(document=doc, user=self.reception)

    def test_render_editor_history_and_readonly_final(self):
        response = assessment_views.assessment_editor(self.req(self.doctor))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mapa corporal")
        for label in (
            "Dashboard",
            "Agenda",
            "Pacientes",
            "Atendimentos",
            "Fisioterapia",
            "Financeiro",
            "Relatórios",
            "Configurações",
        ):
            self.assertContains(response, label)
        self.assertContains(response, 'id="pa-sidebar"')
        self.assertContains(response, "pa-top-grid")
        self.assertContains(response, "pa-middle-grid")
        self.assertContains(response, "pa-bottom-grid")
        row = self.save()
        response = assessment_views.assessment_editor(self.req(self.doctor), pk=row.pk)
        self.assertContains(response, "Salvar rascunho")
        self.save(row, final=True)
        response = assessment_views.assessment_editor(self.req(self.doctor), pk=row.pk)
        self.assertContains(response, "Dra. Ana Teste")
        self.assertNotContains(response, 'value="finalize"')
        response = assessment_views.assessment_list(self.req(self.doctor))
        self.assertContains(response, self.patient.name)

    def test_future_evolution_links_finalized_same_patient_only(self):
        row = self.save()
        with self.assertRaises(ValidationError):
            create_record(
                tenant=self.tenant,
                customer=self.patient,
                professional=self.professional,
                user=self.doctor,
                record_type="physio_evolution",
                title="Sessão",
                content="teste",
                physiotherapy_assessment=row,
            )
        row = self.save(row, final=True)
        entry = create_record(
            tenant=self.tenant,
            customer=self.patient,
            professional=self.professional,
            user=self.doctor,
            record_type="physio_evolution",
            title="Sessão",
            content="teste",
            physiotherapy_assessment=row,
        )
        self.assertEqual(entry.physiotherapy_assessment_id, row.pk)

    def test_http_routes_authentication_and_reception_denial(self):
        self.client.force_login(self.doctor)
        response = self.client.get(reverse("physio-assessment-create"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        data = self.data(action="draft")
        response = self.client.post(reverse("physio-assessment-create"), data)
        self.assertEqual(response.status_code, 302)
        row = PhysiotherapyAssessment.objects.get()
        data.update(
            version=row.version,
            action="finalize",
            appointment=self.appointment.pk,
            attestation="on",
        )
        response = self.client.post(
            reverse("physio-assessment-detail", args=[row.pk]), data
        )
        self.assertEqual(response.status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.status, "finalized")
        self.assertEqual(row.final_entry.customer_id, self.patient.pk)
        self.client.force_login(self.reception)
        self.assertEqual(
            self.client.get(reverse("physio-assessments")).status_code, 403
        )

    @skipUnless(connection.vendor == "postgresql", "PostgreSQL ledger triggers")
    def test_postgres_bypass_is_blocked(self):
        row = self.save(final=True)
        for model, pk, values in (
            (PhysiotherapyAssessment, row.pk, {"payload_encrypted": "tamper"}),
            (
                PhysiotherapyAssessmentVersion,
                row.versions.get().pk,
                {"sha256": "0" * 64},
            ),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                model._base_manager.filter(pk=pk).update(**values)

    def test_new_form_finalize_replay_is_idempotent(self):
        token = str(uuid.uuid4())
        first = self.save(final=True, submission_key=token)
        second = self.save(final=True, submission_key=token)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(PhysiotherapyAssessment.objects.count(), 1)
        payload = read_assessment(assessment=first, user=self.doctor)
        signature = payload.pop("signature")
        from .assessment_services import canonical

        self.assertEqual(
            signature["payload_sha256"],
            hashlib.sha256(canonical(payload).encode()).hexdigest(),
        )

    def test_care_grant_exposes_only_finalized_readonly_record(self):
        from .clinical import grant_care

        draft = self.save()
        finalized = self.save(final=True)
        grant_care(
            entry=finalized.final_entry,
            grantee=self.colleague_profile,
            user=self.doctor,
            reason="Atendimento compartilhado autorizado",
        )
        self.assertEqual(
            list(assessments_for(self.colleague).values_list("pk", flat=True)),
            [finalized.pk],
        )
        response = assessment_views.assessment_editor(
            self.req(self.colleague), pk=finalized.pk
        )
        self.assertContains(response, "Dra. Ana Teste")
        self.assertNotContains(response, "Salvar rascunho")
        with self.assertRaises(PermissionDenied):
            read_assessment(assessment=finalized, user=self.colleague, version=1)
        self.assertFalse(assessments_for(self.colleague).filter(pk=draft.pk).exists())

    def test_physiotherapy_module_enables_other_category_without_changing_it(self):
        from billing.models import Module, TenantModule

        self.tenant.category = "saude"
        self.tenant.save()
        with self.assertRaises(PermissionDenied):
            assessments_for(self.doctor)
        module, _ = Module.objects.get_or_create(
            slug="physiotherapy", defaults={"name": "Fisioterapia"}
        )
        TenantModule.objects.create(tenant=self.tenant, module=module, enabled=True)
        response = assessment_views.assessment_list(self.req(self.doctor))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="pa-sidebar"')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.category, "saude")

    def test_invalid_document_rolls_back_draft_and_its_version(self):
        form = AssessmentForm(
            self.data(),
            {
                "documents": [
                    SimpleUploadedFile(
                        "virus.pdf",
                        b"<script>alert(1)</script>",
                        content_type="application/pdf",
                    )
                ]
            },
            user=self.doctor,
        )
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaises(ValidationError):
            save_assessment(form=form, user=self.doctor)
        self.assertEqual(PhysiotherapyAssessment.objects.count(), 0)
        self.assertEqual(PhysiotherapyAssessmentVersion.objects.count(), 0)

    def test_existing_registration_gets_reference_menu_without_recreation(self):
        from scheduling.models import Professional, Customer

        before = (Professional.objects.count(), Customer.objects.count())
        self.client.force_login(self.doctor)
        response = self.client.get(reverse("physio-assessment-create"))
        self.assertContains(response, 'id="pa-sidebar"')
        self.assertContains(response, "pa-profile")
        self.assertEqual(
            (Professional.objects.count(), Customer.objects.count()), before
        )
        self.entry.refresh_from_db()
        from .services import read_record

        self.assertEqual(
            read_record(entry=self.entry, user=self.doctor),
            "Informação clínica de teste",
        )
