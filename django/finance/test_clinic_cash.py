import uuid
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from scheduling.models import Professional
from . import clinic_cash as cash
from . import clinic_services as s
from . import test_clinic_desk as desk
from .clinic_models import ClinicCashEntry
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
        zero = self.entry(dentist_amount="0", clinic_amount="0")  # avaliação ou reparo sem custo
        self.assertEqual(zero.total, Decimal("0"))
        cash.cancel_entry(user=self.manager, entry_id=zero.pk, reason="Teste de valor zero")
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

    def test_reception_corrects_closed_day_directly_and_everything_is_audited(self):
        row = self.entry()
        s.close_clinic_cash(user=self.reception, unit=self.unit, amount="150", session_id=self.session.pk)
        self.session.refresh_from_db()
        self.assertEqual(self.session.difference_amount, Decimal("0.00"))
        cash.update_entry(user=self.reception, entry_id=row.pk, customer=self.patient, professional=self.dentist,
                          professional_name="", dentist_amount="60", clinic_amount="40", other_amount="0",
                          method=self.pix, notes="Era Pix")
        self.session.refresh_from_db()
        self.assertEqual(self.session.expected_amount, Decimal("50.00"))
        self.assertEqual(self.session.difference_amount, Decimal("100.00"))
        self.tenant.metadata = {"reception_permissions": {"apagar_lancamento": True}}
        self.tenant.save()
        self.reception.refresh_from_db()
        late = self.entry(dentist_amount="0", clinic_amount="0")
        self.assertEqual(late.total, Decimal("0"))
        cash.cancel_entry(user=self.reception, entry_id=late.pk, reason="Lançado em duplicidade")
        from core.models import AuditLog
        for action in ("clinic.cash_entry.updated", "clinic.cash_entry.created", "clinic.cash_entry.cancelled",
                       "clinic.cash_report.recalculated"):
            self.assertTrue(AuditLog.objects.filter(action=action).exists(), action)

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


class DailyCashByProfessionalTests(TestCase):
    setUp = ClinicCashSheetTests.setUp
    entry = ClinicCashSheetTests.entry

    def test_closing_is_split_per_professional(self):
        self.entry()
        self.entry(professional=None, professional_name="Dra. Volante Sem Cadastro", method="pix",
                   dentist_amount="30", clinic_amount="20")
        rows = {r["professional"]: r for r in cash.by_professional(self.session)}
        self.assertEqual(rows["Dr. Listado"]["total"], Decimal("100.00"))
        self.assertEqual(rows["Dr. Listado"]["dentist"], Decimal("60.00"))
        self.assertEqual(rows["Dra. Volante Sem Cadastro"]["total"], Decimal("50.00"))
        self.client.force_login(self.reception)
        sheet = self.client.get(reverse("clinic-cash-sheet-detail", args=[self.session.pk]))
        self.assertContains(sheet, "Fechamento do dia por profissional")
        closed = s.close_clinic_cash(user=self.reception, unit=self.unit, amount="150", session_id=self.session.pk)
        summary = {r["professional"]: r for r in closed.clinical_closing.summary["professionals"]}
        self.assertEqual(summary["Dr. Listado"]["total"], "100.00")

    def test_one_sheet_per_professional_per_day_and_earlier_days_stay_editable(self):
        from datetime import timedelta
        from django.db import transaction
        from django.utils import timezone
        with transaction.atomic():
            mine = s.day_sheet(self.tenant, self.unit, self.dentist, self.reception)
            again = s.day_sheet(self.tenant, self.unit, self.dentist, self.reception)
            theirs = s.day_sheet(self.tenant, self.unit, None, self.reception)
        self.assertEqual(mine.pk, again.pk)
        self.assertNotEqual(mine.pk, theirs.pk)
        self.assertEqual(mine.label, "Dr. Listado")
        yesterday = timezone.localdate() - timedelta(days=1)
        type(self.session).objects.filter(pk=self.session.pk).update(business_date=yesterday,
                                                                     opened_at=timezone.now() - timedelta(days=1))
        row = self.entry()
        self.assertEqual(row.transaction.competence_at, yesterday)
        self.assertEqual(timezone.localtime(row.transaction.paid_at).date(), yesterday)
        closed = s.close_clinic_cash(user=self.reception, unit=self.unit, amount="150", session_id=self.session.pk)
        self.assertEqual(closed.status, "closed")


class CashSheetExpensesTests(TestCase):
    def setUp(self):
        desk.ClinicDeskTests.setUp(self)
        self.session = s.open_clinic_cash(self.reception, self.unit, "50")

    def test_sheet_lists_expenses_and_the_result(self):
        s.expense(user=self.reception, unit=self.unit, description="Luvas e máscaras", amount="18.40", method=self.cash,
                  invoice="NF 123", items="2 caixas", image=None, request_id=uuid.uuid4())
        page = self.client.get(reverse("clinic-cash-sheet-detail", args=[self.session.pk]))
        self.assertContains(page, "Despesas pagas neste caixa")
        self.assertContains(page, "Luvas e máscaras")
        self.assertContains(page, "NF 123")
        self.assertContains(page, "Resultado do caixa")
        self.assertEqual(page.context["expenses_total"], Decimal("18.40"))
        self.assertEqual(page.context["net_total"], Decimal("-18.40"))
        self.assertTrue(page.context["can_expense"])
        self.assertContains(page, "Lançar despesa")


class CashWithdrawalTests(TestCase):
    """Retirada (sangria): sai da gaveta, não é despesa nem entra no resultado."""
    def setUp(self):
        desk.ClinicDeskTests.setUp(self)
        self.session = s.open_clinic_cash(self.reception, self.unit, "0")
        self.dentist = Professional.objects.create(tenant=self.tenant, name="Dr. Gaveta")
        cash.add_entry(user=self.reception, session_id=self.session.pk, customer=self.patient, professional=None,
                       professional_name="Avulso", dentist_amount="0", clinic_amount="1790", other_amount="0",
                       method=self.cash, notes="", request_id=uuid.uuid4())

    def expense(self, amount, method=None):
        return s.expense(user=self.reception, unit=self.unit, description="Caixa do consultório", amount=amount,
                         method=method or self.cash, invoice="", items="", image=None, request_id=uuid.uuid4())

    def withdraw(self, amount, user=None):
        return s.withdraw(user=user or self.reception, unit=self.unit, amount=amount, method=self.cash, withdrawn_by="Dr. Jairo",
                          destination="partner", notes="", request_id=uuid.uuid4())

    def test_drawer_counts_expense_and_withdrawal_but_result_ignores_withdrawal(self):
        self.expense("20")
        self.withdraw("1600")
        self.assertEqual(cash.expected_cash(self.session), Decimal("170"))
        data = cash.report(self.session)
        self.assertEqual(data["expenses_total"], Decimal("20"))
        self.assertEqual(data["withdrawals_total"], Decimal("1600"))
        self.assertEqual(data["columns"]["total"] - data["expenses_total"], Decimal("1770"))
        self.assertFalse(FinancialTransaction.objects.filter(type="expense", amount=Decimal("1600")).exists())
        with self.assertRaises(ValidationError):
            self.withdraw("999")  # more than what is left in the drawer

    def test_manager_converts_expense_keeping_drawer_and_fixing_result(self):
        self.expense("20")
        wrong = self.expense("1600")
        before = cash.expected_cash(self.session)
        with self.assertRaises(PermissionDenied):
            cash.convert_expense(user=self.reception, expense_id=wrong.pk, reason="Dinheiro levado no fechamento")
        s.close_clinic_cash(user=self.owner, unit=self.unit, amount="170", session_id=self.session.pk, notes="Conferido")
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, "closed")
        row = cash.convert_expense(user=self.owner, expense_id=wrong.pk, reason="Dinheiro levado no fechamento")
        self.session.refresh_from_db()
        self.assertEqual(cash.expected_cash(self.session), before)
        self.assertEqual(self.session.expected_amount, before)
        self.assertEqual(self.session.status, "closed")
        self.assertEqual((row.amount, row.recorded_by_id, row.occurred_at), (Decimal("1600"), wrong.recorded_by_id, wrong.created_at))
        data = cash.report(self.session)
        self.assertEqual(data["expenses_total"], Decimal("20"))
        self.assertEqual(data["columns"]["total"] - data["expenses_total"], Decimal("1770"))
        summary = self.session.clinical_closing.summary
        self.assertEqual((summary["expenses"], summary["net"], summary["withdrawals"]), ("20.00", "1770.00", "1600.00"))
        from core.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(action="clinic.expense.converted_to_withdrawal").exists())
        with self.assertRaises(ValidationError):
            cash.convert_expense(user=self.owner, expense_id=wrong.pk, reason="De novo, por engano")
        pix = self.expense("5", method=self.pix)
        with self.assertRaises(ValidationError):
            cash.convert_expense(user=self.owner, expense_id=pix.pk, reason="Pix não sai da gaveta")

    def test_only_manager_with_correction_cancels_withdrawal_on_closed_sheet(self):
        row = self.withdraw("100")
        s.close_clinic_cash(user=self.owner, unit=self.unit, amount="1690", session_id=self.session.pk, notes="ok")
        with self.assertRaises(PermissionDenied):
            cash.cancel_withdrawal(user=self.reception, withdrawal_id=row.pk, reason="Errado")
        with self.assertRaises(PermissionDenied):
            cash.cancel_withdrawal(user=self.owner, withdrawal_id=row.pk, reason="Errado")  # no correction open
        correction = cash.request_correction(user=self.owner, session_id=self.session.pk, reason="Retirada lançada errada")
        if correction.status != "approved":
            cash.decide_correction(user=self.owner, correction_id=correction.pk, approve=True, note="")
        cash.cancel_withdrawal(user=self.owner, withdrawal_id=row.pk, reason="Lançada errada")
        self.assertEqual(cash.expected_cash(self.session), Decimal("1790"))

    def test_sheet_and_desk_show_withdrawals(self):
        self.withdraw("1600")
        page = self.client.get(reverse("clinic-cash-sheet-detail", args=[self.session.pk]))
        self.assertContains(page, "Retiradas do caixa (sangria)")
        self.assertContains(page, "Retiradas em dinheiro: R$ 1.600,00 (já descontadas do valor em caixa)")
        self.assertContains(page, "Dr. Jairo")
        desk_page = self.client.get(reverse("clinic-finance-desk"))
        self.assertContains(desk_page, "Registrar retirada (sangria)")
        self.assertContains(desk_page, "Retirada não é gasto:")
        response = self.client.post(reverse("clinic-finance-desk"), {
            "action": "withdrawal", "request_id": str(uuid.uuid4()), "professional": "", "amount": "10", "method": self.cash.pk,
            "withdrawn_by": "Banco", "destination": "bank", "notes": "", "confirmed": "on"})
        self.assertEqual(response.status_code, 302)
