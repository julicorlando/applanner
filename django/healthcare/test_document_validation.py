from io import BytesIO
import uuid
from django.test import TestCase
from django.urls import reverse
from pypdf import PdfReader
from core.crypto import encrypt_text
from scheduling.models import Customer
from . import test_document_delivery as delivery
from .clinical import save_structured_record
from .document_models import ClinicalIssuedDocument, ClinicalDocumentValidation
from .document_services import save_signature, finalize_document
from .document_validation import masked_name
from .patient_registration import missing_registration
from .patient_scope import patients_for

VALID_CPF = "529.982.247-25"


class DocumentValidationTests(TestCase):
    def setUp(self):
        delivery.ClinicalDocumentDeliveryTests.setUp(self)
        self.patient.name = "Paciente Fictício da Silva"
        self.patient.save()

    def image(self):
        return delivery.ClinicalDocumentDeliveryTests.image(self)

    def issue(self, kind="certificate", body="Atesto que o paciente esteve sob meus cuidados por motivo de CID K08.9."):
        save_signature(self.doctor, self.image())
        row = ClinicalIssuedDocument.objects.create(tenant=self.tenant, customer=self.patient, professional=self.professional,
                                                    kind=kind, title="Atestado", body_encrypted=encrypt_text(body), created_by=self.doctor)
        return finalize_document(user=self.doctor, document=row, body=body, title=row.title, version=1, confirmed=True)

    def test_emission_prints_qr_validation_link_and_public_page_hides_clinical_content(self):
        row = self.issue()
        self.assertTrue(row.verification_code)
        self.assertGreaterEqual(len(row.verification_code), 30)
        pdf = self.client.get(reverse("clinical-document-pdf", args=[row.pk])).content
        text = "".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
        url = reverse("clinical-document-validate", args=[row.verification_code])
        self.assertIn(url, text.replace("\n", ""))
        self.assertIn("ATESTADO", text)
        self.client.logout()
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Documento autêntico")
        self.assertContains(page, "Paciente F. da S.")
        self.assertContains(page, row.sha256)
        self.assertNotContains(page, "K08.9")
        self.assertNotContains(page, "Fictício da Silva")

    def test_anyone_with_document_can_register_validation_and_professional_sees_it(self):
        row = self.issue()
        url = reverse("clinical-document-validate", args=[row.verification_code])
        self.client.logout()
        self.assertEqual(self.client.post(url, {"validator_name": "Ana Farmacêutica"}).status_code, 200)
        self.assertFalse(ClinicalDocumentValidation.objects.exists())
        response = self.client.post(url, {"validator_name": "Ana Farmacêutica", "validator_role": "Farmácia Central", "confirm": "on"})
        self.assertRedirects(response, url + "?registrado=1", fetch_redirect_response=False)
        validation = ClinicalDocumentValidation.objects.get()
        self.assertEqual(validation.document, row)
        self.assertContains(self.client.get(url + "?registrado=1"), "Ana Farmacêutica")
        self.client.force_login(self.doctor)
        detail = self.client.get(reverse("clinical-document-detail", args=[row.pk]))
        self.assertContains(detail, "Ana Farmacêutica")
        self.assertContains(detail, "Farmácia Central")

    def test_unknown_or_draft_codes_are_not_found(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("clinical-document-validate", args=["x" * 32])).status_code, 404)
        self.assertEqual(self.client.get("/validar/curto/").status_code, 404)
        draft = ClinicalIssuedDocument.objects.create(tenant=self.tenant, customer=self.patient, professional=self.professional,
                                                      kind="declaration", title="Declaração", body_encrypted=encrypt_text("x"), created_by=self.doctor)
        self.assertIsNone(draft.verification_code)

    def test_masked_name_keeps_first_name_and_connectors(self):
        self.assertEqual(masked_name("Klécia Maria da Silva"), "Klécia M. da S.")
        self.assertEqual(masked_name(""), "")

    def test_record_shortcuts_prefill_models_and_budget_from_treatment_plan(self):
        self.client.force_login(self.doctor)
        response = self.client.get(reverse("clinical-documents") + f"?customer={self.patient.pk}&kind=certificate")
        self.assertEqual(response.status_code, 200)
        initial = response.context["form"].initial
        self.assertEqual(initial["kind"], "certificate")
        self.assertIn(self.patient.name, initial["body"])
        save_structured_record(tenant=self.tenant, customer=self.patient, professional=self.professional, user=self.doctor,
                               kind="treatment_plan", title="Plano",
                               data={"lines": [{"tooth": "11", "procedure": "Restauração", "quantity": 2, "price": "90.00"}]})
        budget = self.client.get(reverse("clinical-documents") + f"?customer={self.patient.pk}&kind=budget").context["form"].initial
        self.assertEqual(budget["title"], "Orçamento")
        self.assertIn("Restauração (x2)", budget["body"])
        self.assertIn("R$ 180,00", budget["body"])
        result = self.client.post(reverse("clinical-documents"), {"customer": self.patient.pk, "professional": self.professional.pk,
                                                                  "kind": "budget", "title": "Orçamento", "body": budget["body"],
                                                                  "request_id": str(uuid.uuid4())})
        self.assertEqual(result.status_code, 302)
        row = ClinicalIssuedDocument.objects.get(kind="budget")
        save_signature(self.doctor, self.image())
        issued = finalize_document(user=self.doctor, document=row, body=budget["body"], title="Orçamento", version=1, confirmed=True)
        self.assertTrue(issued.entry_id)
        self.assertEqual(issued.entry.customer_id, self.patient.pk)


class PatientRegistrationTests(TestCase):
    def setUp(self):
        delivery.ClinicalDocumentDeliveryTests.setUp(self)

    def data(self, **changes):
        values = {"name": "Maria Teste Souza", "phone": "(81) 99999-1234", "email": "", "cpf": VALID_CPF,
                  "postal_code": "", "street": "Rua Exemplo", "address_number": "10", "address_complement": "",
                  "district": "Centro", "city": "Carpina", "state": "pe", "birth_date": ""}
        values.update(changes)
        return values

    def test_professional_registers_patient_from_record_and_returns_to_editor(self):
        response = self.client.post(reverse("dental-patient-create"), self.data(next=reverse("dental-assessment-create")))
        patient = Customer.objects.get(name="Maria Teste Souza")
        self.assertRedirects(response, reverse("dental-assessment-create") + f"?customer={patient.pk}", fetch_redirect_response=False)
        self.assertEqual(patient.registered_by, self.doctor)
        self.assertEqual(patient.cpf, "52998224725")
        self.assertEqual(patient.state, "PE")
        self.assertTrue(patients_for(self.doctor).filter(pk=patient.pk).exists())
        self.assertEqual(missing_registration(patient), [])

    def test_validation_requires_full_name_valid_unique_cpf(self):
        self.assertFormError(self.client.post(reverse("dental-patient-create"), self.data(name="Maria")).context["form"],
                             "name", "Informe o nome completo (nome e sobrenome).")
        self.assertFalse(self.client.post(reverse("dental-patient-create"), self.data(cpf="111.111.111-11")).context["form"].is_valid())
        self.client.post(reverse("dental-patient-create"), self.data())
        clash = self.client.post(reverse("dental-patient-create"), self.data(name="Outra Pessoa", phone="(81) 98888-0000"))
        self.assertIn("cpf", clash.context["form"].errors)
        self.assertEqual(Customer.objects.filter(name="Outra Pessoa").count(), 0)

    def test_incomplete_patient_is_flagged_and_completed(self):
        self.assertIn("CPF", missing_registration(self.patient))
        editor = self.client.get(reverse("dental-assessment-create") + f"?customer={self.patient.pk}")
        self.assertEqual(editor.status_code, 200)
        self.assertIn("CPF", editor.context["registration_missing"])
        url = reverse("dental-patient-edit", args=[self.patient.pk])
        self.assertEqual(self.client.post(url, self.data(name="Paciente Fictício Completo")).status_code, 302)
        self.patient.refresh_from_db()
        self.assertEqual(missing_registration(self.patient), [])

    def test_reception_and_other_professionals_cannot_use_record_registration(self):
        self.client.force_login(self.reception)
        self.assertEqual(self.client.get(reverse("dental-patient-create")).status_code, 403)
        self.client.force_login(self.colleague)
        self.assertEqual(self.client.get(reverse("dental-patient-edit", args=[self.patient.pk])).status_code, 404)

    def test_next_parameter_cannot_redirect_off_site(self):
        response = self.client.post(reverse("dental-patient-create"), self.data(next="https://evil.example/x"))
        patient = Customer.objects.get(name="Maria Teste Souza")
        self.assertRedirects(response, reverse("dental-assessment-create") + f"?customer={patient.pk}", fetch_redirect_response=False)
