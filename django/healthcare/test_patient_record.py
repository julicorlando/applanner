import uuid
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from billing.models import Module, TenantModule
from core.crypto import decrypt_text, encrypt_text
from scheduling.models import Customer

from .document_models import ClinicalIssuedDocument, PatientNote
from .models import MedicalRecordAccessLog
from . import test_dental_assessments as dental


class PatientRecordTests(TestCase):
    create = dental.DentalAssessmentTests.create
    data = dental.DentalAssessmentTests.data
    save = dental.DentalAssessmentTests.save

    def setUp(self):
        dental.DentalAssessmentTests.setUp(self)

    def url(self, patient=None):
        return reverse("dental-patient-record", args=[(patient or self.patient).pk])

    def test_dentist_sees_own_record_with_both_text_boxes_and_other_dentist_cannot(self):
        self.save(final=True, initial_evolution="Restauração no 46.", orthodontic_treatment="Troca de elástico superior.")
        self.client.force_login(self.doctor)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        for text in ("Procedimento clínico", "Restauração no 46.", "Tratamento ortodôntico", "Troca de elástico superior.",
                     "Informação clínica de teste", "Histórico do paciente"):
            self.assertContains(response, text)
        self.assertTrue(MedicalRecordAccessLog.objects.filter(user=self.doctor).exists())
        self.client.force_login(self.colleague)
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_editor_has_two_evolution_boxes(self):
        self.client.force_login(self.doctor)
        response = self.client.get(reverse("dental-assessment-create") + f"?customer={self.patient.pk}")
        self.assertContains(response, 'name="initial_evolution"')
        self.assertContains(response, 'name="orthodontic_treatment"')
        self.assertContains(response, "Tratamento ortodôntico")

    def test_reception_opens_any_patient_without_appointment_and_adds_observation(self):
        unscheduled = Customer.objects.create(tenant=self.tenant, name="Paciente Sem Agenda Exemplo")
        self.client.force_login(self.reception)
        listing = self.client.get(reverse("dental-assessments"))
        self.assertContains(listing, "Paciente Sem Agenda Exemplo")
        self.assertContains(listing, self.url(unscheduled))
        self.assertEqual(self.client.get(self.url(unscheduled)).status_code, 200)
        self.assertContains(self.client.get(self.url()), "Informação clínica de teste")
        self.assertContains(self.client.get(self.url()), 'name="procedure"')
        self.assertEqual(self.client.post(self.url(), {"action": "note", "text": ""}).status_code, 200)
        response = self.client.post(self.url(), {"action": "note", "procedure": "Moldagem superior realizada.",
                                                 "orthodontic": "", "text": "Paciente pediu retorno à tarde."})
        self.assertRedirects(response, self.url(), fetch_redirect_response=False)
        note = PatientNote.objects.get(customer=self.patient)
        self.assertIn("Moldagem superior realizada.", decrypt_text(note.text_encrypted))
        self.assertNotIn("Moldagem", note.text_encrypted)
        page = self.client.get(self.url())
        self.assertContains(page, "Moldagem superior realizada.")
        self.assertContains(page, "Paciente pediu retorno à tarde.")
        with self.assertRaises(ValidationError):
            note.save()
        # The dentist of the patient sees the front desk evolution too.
        self.client.force_login(self.doctor)
        self.assertContains(self.client.get(self.url()), "Moldagem superior realizada.")

    def test_patient_link_goes_to_record_and_other_clinic_is_hidden(self):
        self.client.force_login(self.doctor)
        response = self.client.get(reverse("dental-assessments") + f"?customer={self.patient.pk}")
        self.assertRedirects(response, self.url(), fetch_redirect_response=False)
        outsider = Customer.objects.create(tenant=self.other, name="Paciente de outra clínica")
        self.assertEqual(self.client.get(self.url(outsider)).status_code, 404)
        self.client.force_login(self.master)
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_reception_completes_registration_and_returns_to_record(self):
        self.client.force_login(self.reception)
        response = self.client.post(reverse("dental-patient-edit", args=[self.patient.pk]), {
            "name": "Paciente Fictício Completo", "phone": "(81) 99999-1234", "email": "", "cpf": "529.982.247-25",
            "birth_date": "1990-03-14", "postal_code": "", "street": "Rua Exemplo", "address_number": "10",
            "address_complement": "", "district": "Centro", "city": "Recife", "state": "pe"})
        self.assertRedirects(response, self.url(), fetch_redirect_response=False)
        self.patient.refresh_from_db()
        self.assertEqual(str(self.patient.birth_date), "1990-03-14")

    def test_patient_list_has_schedule_record_and_edit_actions(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("portal-resource-list", args=["agenda", "clientes"]))
        if response.status_code != 200:
            self.skipTest("Lista de clientes indisponível para este plano de teste.")
        self.assertContains(response, self.url())
        self.assertContains(response, ">Prontuário<")
        self.assertContains(response, f"?customer={self.patient.pk}")
        self.assertNotContains(response, "Histórico e preferências")


class PatientRecordPaymentTests(TestCase):
    def setUp(self):
        from finance import test_clinic_desk as desk
        from finance import clinic_services
        desk.ClinicDeskTests.setUp(self)
        for slug in ("dentistry", "medical_records"):
            module, _ = Module.objects.get_or_create(slug=slug, defaults={"name": slug, "active": True})
            TenantModule.objects.create(tenant=self.tenant, module=module, enabled=True)
        self.session = clinic_services.open_clinic_cash(self.reception, self.unit, "50")

    def url(self):
        return reverse("dental-patient-record", args=[self.patient.pk])

    def test_payment_in_record_is_paid_cash_line_and_shows_in_the_day(self):
        from finance.clinic_models import ClinicCashEntry
        response = self.client.post(self.url(), {
            "action": "receive", "request_id": str(uuid.uuid4()), "professional": "", "professional_name": "Dra. Volante Exemplo",
            "dentist_amount": "150.00", "clinic_amount": "50.00", "other_amount": "0", "method": self.pix.pk, "notes": ""})
        self.assertRedirects(response, self.url(), fetch_redirect_response=False)
        row = ClinicCashEntry.objects.get(customer=self.patient)
        self.assertEqual(row.session_id, self.session.pk)
        self.assertEqual(row.status, "paid")
        self.assertEqual(row.total, Decimal("200.00"))
        self.assertEqual(row.transaction.status, "paid")
        page = self.client.get(self.url())
        self.assertContains(page, "Pagamento recebido")
        self.assertContains(page, "Dra. Volante Exemplo")

    def test_payment_on_an_earlier_date_goes_to_that_days_sheet(self):
        from datetime import timedelta
        from django.utils import timezone
        from finance.clinic_models import ClinicCashEntry
        yesterday = timezone.localdate() - timedelta(days=1)
        response = self.client.post(self.url(), {
            "action": "receive", "request_id": str(uuid.uuid4()), "professional": "", "professional_name": "Dra. Volante Exemplo",
            "dentist_amount": "0", "clinic_amount": "0", "other_amount": "0", "method": self.pix.pk, "notes": "Avaliação",
            "paid_on": yesterday.isoformat()})
        self.assertRedirects(response, self.url(), fetch_redirect_response=False)
        row = ClinicCashEntry.objects.get(customer=self.patient)
        self.assertEqual(row.session.business_date, yesterday)
        self.assertEqual(timezone.localtime(row.transaction.paid_at).date(), yesterday)
        future = self.client.post(self.url(), {
            "action": "receive", "request_id": str(uuid.uuid4()), "professional_name": "Dra. Volante Exemplo",
            "dentist_amount": "10", "clinic_amount": "0", "other_amount": "0", "method": self.pix.pk,
            "paid_on": (timezone.localdate() + timedelta(days=1)).isoformat()})
        self.assertContains(future, "A data não pode ser no futuro")

    def test_dated_evolution_and_treatment_plan_go_into_the_history(self):
        from datetime import date
        from django.utils import timezone
        from .document_models import PatientNote
        self.client.post(self.url(), {"action": "note", "procedure": "Restauração 16", "orthodontic": "", "text": "",
                                      "occurred_on": "2026-10-05"})
        note = PatientNote.objects.get(customer=self.patient)
        self.assertEqual(timezone.localtime(note.occurred_at).date(), date(2026, 10, 5))
        empty = self.client.post(self.url(), {"action": "plan", "plan_procedure": ["", ""], "plan_price": ["", ""]})
        self.assertContains(empty, "Adicione pelo menos um procedimento")
        response = self.client.post(self.url(), {
            "action": "plan", "occurred_on": "", "professional": "", "notes": "Começar pela urgência",
            "plan_tooth": ["16", "", ""], "plan_procedure": ["Restauração", "Limpeza", ""], "plan_price": ["150,00", "120", ""]})
        self.assertRedirects(response, self.url(), fetch_redirect_response=False)
        page = self.client.get(self.url())
        self.assertContains(page, "Plano de tratamento")
        self.assertContains(page, "1. Dente 16 · Restauração · R$ 150,00")
        self.assertContains(page, "Total do plano: R$ 270,00")
        self.assertContains(page, "05/10/2026")
        self.assertContains(page, 'value="Limpeza"')  # current plan comes back as editable rows
        history = [label for day in page.context["timeline"] for note in day["notes"] for label, _ in note["sections"]]
        self.assertIn("Procedimento clínico", history)
        self.assertNotIn("Plano de tratamento", history)  # the plan stays in its own card
        self.assertContains(page, "Versões salvas do plano (1)")
        self.assertContains(page, "Salvar alterações do plano")
        self.client.post(self.url(), {"action": "plan", "plan_tooth": ["16", ""], "plan_procedure": ["Restauração", "Canal"],
                                      "plan_price": ["150,00", "400"]})
        page = self.client.get(self.url())
        self.assertContains(page, "Removido: Limpeza · R$ 120,00")
        self.assertContains(page, "Total do plano: R$ 550,00")
        self.assertNotContains(page, 'value="Limpeza"')
        self.assertContains(page, 'value="Canal"')
        self.client.post(self.url(), {"action": "plan", "plan_procedure": [""], "plan_price": [""]})
        page = self.client.get(self.url())
        self.assertContains(page, "Todos os itens do plano foram removidos.")
        self.assertNotContains(page, 'value="Canal"')
        self.assertEqual(PatientNote.objects.filter(customer=self.patient).count(), 4)  # history is kept

    def test_reception_edits_saved_plan_unless_manager_turns_it_off(self):
        from finance import reception_permissions as perms
        self.client.post(self.url(), {"action": "plan", "plan_tooth": ["11"], "plan_procedure": ["Clareamento"], "plan_price": ["300"]})
        page = self.client.get(self.url())
        self.assertContains(page, 'value="Clareamento"')
        self.client.post(self.url(), {"action": "plan", "plan_tooth": ["11", ""], "plan_procedure": ["Clareamento", "Faceta"],
                                      "plan_price": ["250", "900"]})
        self.assertContains(self.client.get(self.url()), "Total do plano: R$ 1.150,00")
        values = perms.current(self.tenant)
        values.update(plano=False)
        perms.save(self.tenant, self.owner, values)
        page = self.client.get(self.url())
        self.assertNotContains(page, 'id="plano"')
        self.assertEqual(self.client.post(self.url(), {"action": "plan", "plan_procedure": ["X"], "plan_price": ["1"]}).status_code, 403)

    def test_payment_requires_method_and_open_cash(self):
        from finance.clinic_models import ClinicCashEntry
        response = self.client.post(self.url(), {
            "action": "receive", "request_id": str(uuid.uuid4()), "professional_name": "Dra. Volante Exemplo",
            "dentist_amount": "10", "clinic_amount": "0", "other_amount": "0", "method": ""})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ClinicCashEntry.objects.exists())

    def test_cash_sheet_payment_appears_in_patient_record(self):
        from finance import clinic_cash
        clinic_cash.add_entry(user=self.reception, session_id=self.session.pk, customer=self.patient, professional=None,
                              professional_name="Dr. Folha Exemplo", dentist_amount="80", clinic_amount="20", other_amount="0",
                              method=self.cash, notes="", request_id=uuid.uuid4())
        page = self.client.get(self.url())
        self.assertContains(page, "Dr. Folha Exemplo")
        self.assertContains(page, "Folha do caixa")


class BudgetRevisionTests(TestCase):
    def create(self, **kwargs):
        from . import test_document_delivery as delivery
        return delivery.fixtures.ClinicalSecurityTests.create(self, **kwargs)

    def setUp(self):
        from . import test_document_delivery as delivery
        delivery.ClinicalDocumentDeliveryTests.setUp(self)
        self.image = lambda: delivery.ClinicalDocumentDeliveryTests.image(self)

    def test_editing_issued_budget_creates_revision_and_flags_old_one(self):
        from .document_services import finalize_document, save_signature
        save_signature(self.doctor, self.image())
        draft = ClinicalIssuedDocument.objects.create(tenant=self.tenant, customer=self.patient, professional=self.professional,
                                                      kind="budget", title="Orçamento", body_encrypted=encrypt_text("Restauração: R$ 180,00"),
                                                      created_by=self.doctor)
        issued = finalize_document(user=self.doctor, document=draft, body="Restauração: R$ 180,00", title="Orçamento",
                                   version=1, confirmed=True)
        detail = reverse("clinical-document-detail", args=[issued.pk])
        self.assertContains(self.client.get(detail), "Editar orçamento")
        response = self.client.post(detail, {"action": "revise"})
        revision = ClinicalIssuedDocument.objects.get(replaces=issued)
        self.assertRedirects(response, reverse("clinical-document-detail", args=[revision.pk]), fetch_redirect_response=False)
        self.assertEqual(revision.status, "draft")
        self.assertEqual(self.client.post(detail, {"action": "revise"}).url, reverse("clinical-document-detail", args=[revision.pk]))
        self.assertIsNone(issued.replaced_by)
        new = finalize_document(user=self.doctor, document=revision, body="Restauração: R$ 150,00", title="Orçamento revisado",
                                version=1, confirmed=True)
        self.assertEqual(issued.replaced_by.pk, new.pk)
        self.assertNotEqual(new.verification_code, issued.verification_code)
        validation = self.client.get(reverse("clinical-document-validate", args=[issued.verification_code]))
        self.assertContains(validation, "este orçamento foi substituído")
        self.assertNotContains(self.client.get(reverse("clinical-document-validate", args=[new.verification_code])),
                               "este orçamento foi substituído")
        issued.refresh_from_db()
        self.assertEqual(issued.status, "finalized")

    def test_reception_and_other_kinds_cannot_revise(self):
        from .document_services import finalize_document, save_signature
        save_signature(self.doctor, self.image())
        draft = ClinicalIssuedDocument.objects.create(tenant=self.tenant, customer=self.patient, professional=self.professional,
                                                      kind="declaration", title="Declaração", body_encrypted=encrypt_text("Compareceu."),
                                                      created_by=self.doctor)
        issued = finalize_document(user=self.doctor, document=draft, body="Compareceu.", title="Declaração", version=1, confirmed=True)
        self.assertEqual(self.client.post(reverse("clinical-document-detail", args=[issued.pk]), {"action": "revise"}).status_code, 403)
        self.assertFalse(ClinicalIssuedDocument.objects.filter(replaces=issued).exists())


class BirthDateFormTests(TestCase):
    def test_generic_date_widget_keeps_saved_value_when_editing(self):
        from core.portal import _widgets_for
        widget = _widgets_for(Customer, ["birth_date"])["birth_date"]
        self.assertIn('value="1990-03-14"', widget.render("birth_date", date(1990, 3, 14)))


class DocumentPreviewTests(TestCase):
    def create(self, **kwargs):
        from . import test_document_delivery as delivery
        return delivery.fixtures.ClinicalSecurityTests.create(self, **kwargs)

    def setUp(self):
        from . import test_document_delivery as delivery
        delivery.ClinicalDocumentDeliveryTests.setUp(self)

    def test_editor_pages_show_live_preview_with_letterhead_data(self):
        for url in (reverse("clinical-documents") + f"?customer={self.patient.pk}&kind=certificate",
                    reverse("clinical-document-templates")):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'id="doc-preview-data"')
            self.assertContains(response, "data-paper")
            self.assertContains(response, "data-preview-body")
            self.assertContains(response, "CRO-PE 12345")
        draft = ClinicalIssuedDocument.objects.create(tenant=self.tenant, customer=self.patient, professional=self.professional,
                                                      kind="declaration", title="Declaração", body_encrypted=encrypt_text("Compareceu."),
                                                      created_by=self.doctor)
        response = self.client.get(reverse("clinical-document-detail", args=[draft.pk]))
        self.assertContains(response, "data-paper")
        self.assertContains(response, self.patient.name)
