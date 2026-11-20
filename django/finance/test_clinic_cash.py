import uuid
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from scheduling.models import Professional
from . import clinic_cash as cash
from . import clinic_services as s
from . import test_clinic_desk as desk
from .clinic_models import ClinicCashEntry, ClinicCashCorrection
from .models import FinancialTransaction


class ClinicCashSheetTests(TestCase):
    def setUp(self):
        desk.ClinicDeskTests.setUp(self)
        self.manager = self.owner
        self.dentist = Professional.objects.create(tenant=self.tenant, name="Dr. Listado")
        self.session = s.open_clinic_cash(self.reception, self.unit, "50")

    def entry(self, user=None, method="cash", **kw):
        values = dict(customer=self.patient, professional=self.dentist, professional_name="", dentist_amount="60",
                      clinic_amount="40", other_amount="0", method=getattr(self, method) if method else None, notes="",
                      request_id=uuid.uuid4())
        values.update(kw)
        return cash.add_entry(user=user or self.reception, session_id=self.session.pk, **values)

    def test_entry_splits_amount_links_patient_and_enters_cash_drawer(self):
        row = self.entry()
        self.assertEqual(row.number, 1)
        self.assertEqual(row.total, Decimal("100.00"))
        self.assertEqual(row.transaction.status, "paid")
        self.assertEqual(row.transaction.payment_method, "cash")
        self.assertEqual(row.customer, self.patient)
        manual = self.entry(professional=None, professional_name="Dra. Volante Sem Cadastro", method="pix",
                            dentist_amount="0", clinic_amount="80")
        self.assertEqual(manual.number, 2)
        self.assertEqual(manual.professional_name, "Dra. Volante Sem Cadastro")
        with self.assertRaises(ValidationError):
            self.entry(professional=None, professional_name="")
        with self.assertRaises(ValidationError):
            self.entry(dentist_amount="0", clinic_amount="0")
        data = cash.report(self.session)
        self.assertEqual(dict(data["kinds"]), {"Dinheiro": Decimal("100.00"), "Pix": Decimal("80.00"), "Débito/Crédito": Decimal("0")})
        self.assertEqual(data["columns"]["total"], Decimal("180.00"))
        self.assertEqual(data["drawer_expected"], Decimal("150.00"))

    def test_open_entries_are_listed_as_pending_and_not_counted_as_received(self):
        row = self.entry(method=None)
        self.assertEqual(row.status, "open")
        self.assertEqual(row.transaction.status, "pending")
        data = cash.report(self.session)
        self.assertEqual(data["open_total"], Decimal("100.00"))
        self.assertEqual(data["columns"]["total"], Decimal("0"))
        cash.update_entry(user=self.reception, entry_id=row.pk, customer=self.patient, professional=self.dentist,
                          professional_name="", dentist_amount="60", clinic_amount="40", other_amount="0",
                          method=self.card, notes="Pagou no fim do dia")
        row.refresh_from_db()
        self.assertEqual(row.status, "paid")
        self.assertEqual(FinancialTransaction.objects.get(pk=row.transaction_id).status, "paid")

    def test_closed_sheet_is_locked_until_manager_authorizes_and_changes_are_audited(self):
        row = self.entry()
        s.close_clinic_cash(user=self.reception, unit=self.unit, amount="150")
        self.session.refresh_from_db()
        self.assertTrue(cash.report(self.session)["locked"])
        with self.assertRaises(PermissionDenied):
            cash.cancel_entry(user=self.reception, entry_id=row.pk, reason="Valor errado")
        with self.assertRaises(PermissionDenied):
            self.entry()
        request = cash.request_correction(user=self.reception, session_id=self.session.pk, reason="Pix lançado como dinheiro")
        self.assertEqual(request.status, "requested")
        with self.assertRaises(PermissionDenied):
            cash.decide_correction(user=self.reception, correction_id=request.pk, approve=True)
        with self.assertRaises(PermissionDenied):
            cash.cancel_entry(user=self.reception, entry_id=row.pk, reason="Ainda bloqueado")
        cash.decide_correction(user=self.manager, correction_id=request.pk, approve=True)
        cash.update_entry(user=self.reception, entry_id=row.pk, customer=self.patient, professional=self.dentist,
                          professional_name="", dentist_amount="60", clinic_amount="40", other_amount="0",
                          method=self.pix, notes="")
        cash.finish_correction(user=self.reception, correction_id=request.pk)
        self.session.refresh_from_db()
        self.assertEqual(self.session.expected_amount, Decimal("50.00"))
        self.assertEqual(self.session.difference_amount, Decimal("100.00"))
        self.assertTrue(cash.report(self.session)["locked"])
        self.assertEqual(ClinicCashCorrection.objects.get().status, "done")
        from core.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(action="clinic.cash_entry.updated", entity_id=row.pk).exists())
        with self.assertRaises(PermissionDenied):
            cash.cancel_entry(user=self.reception, entry_id=row.pk, reason="Depois de concluir")

    def test_manager_can_open_correction_directly_and_rejection_keeps_lock(self):
        s.close_clinic_cash(user=self.reception, unit=self.unit, amount="50")
        rejected = cash.request_correction(user=self.reception, session_id=self.session.pk, reason="Quero mudar")
        cash.decide_correction(user=self.manager, correction_id=rejected.pk, approve=False, note="Sem motivo")
        self.session.refresh_from_db()
        self.assertTrue(cash.report(self.session)["locked"])
        direct = cash.request_correction(user=self.manager, session_id=self.session.pk, reason="Ajuste da gestão")
        self.assertEqual(direct.status, "approved")
        late = self.entry(user=self.manager)
        self.assertEqual(late.transaction.paid_at, self.session.closed_at)

    def test_sheet_page_renders_model_layout_and_reception_adds_line(self):
        response = self.client.get(reverse("clinic-cash-sheet"))
        self.assertRedirects(response, reverse("clinic-cash-sheet-detail", args=[self.session.pk]), fetch_redirect_response=False)
        url = reverse("clinic-cash-sheet-detail", args=[self.session.pk])
        page = self.client.get(url)
        for text in ("Nome do Paciente", "Consultório", "Forma de pagamento", "Débito/Crédito", "Valores em aberto do dia", "RECEPCIONISTA"):
            self.assertContains(page, text)
        result = self.client.post(url, {"action": "add", "request_id": str(uuid.uuid4()), "customer": self.patient.pk,
                                        "professional": "", "professional_name": "Dr. Avulso Teste", "dentist_amount": "30",
                                        "clinic_amount": "20", "other_amount": "0", "method": self.pix.pk, "notes": ""})
        self.assertEqual(result.status_code, 302)
        self.assertEqual(ClinicCashEntry.objects.get().professional_name, "Dr. Avulso Teste")
        self.assertContains(self.client.get(url), "Dr. Avulso Teste")
