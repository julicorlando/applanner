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

    def test_one_clinic_sheet_per_day_and_earlier_days_stay_editable(self):
        from datetime import timedelta
        from django.db import transaction
        from django.utils import timezone
        with transaction.atomic():
            mine = s.day_sheet(self.tenant, self.unit, self.dentist, self.reception)
            again = s.day_sheet(self.tenant, self.unit, self.dentist, self.reception)
            theirs = s.day_sheet(self.tenant, self.unit, None, self.reception)
        self.assertEqual({mine.pk, again.pk, theirs.pk}, {self.session.pk})
        self.assertEqual(mine.label, "Caixa da clínica")
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


class UnifiedClinicCashTests(TestCase):
    """Um caixa da clínica por dia: despesa com data escolhida e unificação dos caixas antigos por profissional."""
    setUp = ClinicCashSheetTests.setUp
    entry = ClinicCashSheetTests.entry

    def second_dentist(self):
        from billing.models import Module, TenantModuleAddon
        extra, _ = Module.objects.get_or_create(slug="dental-professional-extra", defaults={"name": "Dentista extra", "active": True})
        TenantModuleAddon.objects.create(tenant=self.tenant, module=extra, monthly_price=0, quantity=2,
                                         status=TenantModuleAddon.Status.ACTIVE)
        return Professional.objects.create(tenant=self.tenant, name="Dra. Segunda")

    def legacy_sheet(self, professional, day=None, opening="0"):
        from django.utils import timezone
        from .models import CashSession
        return CashSession.objects.create(tenant=self.tenant, unit=self.unit, professional=professional,
                                          business_date=day or s.business_today(self.tenant), opened_by=self.reception,
                                          opened_at=timezone.now(), opening_amount=Decimal(opening))

    def test_expense_on_an_earlier_day_goes_to_that_day_clinic_sheet(self):
        from datetime import timedelta
        from django.utils import timezone
        yesterday = s.business_today(self.tenant) - timedelta(days=1)
        row = s.expense(user=self.owner, unit=self.unit, description="Conta de luz", amount="80", method=self.pix,
                        invoice="", items="", image=None, request_id=uuid.uuid4(), day=yesterday)
        self.assertEqual(row.session.business_date, yesterday)
        self.assertIsNone(row.session.professional_id)
        self.assertEqual(row.transaction.competence_at, yesterday)
        self.assertEqual(timezone.localtime(row.transaction.paid_at).date(), yesterday)
        with self.assertRaises(ValidationError):
            s.expense(user=self.owner, unit=self.unit, description="Futuro", amount="1", method=self.pix, invoice="",
                      items="", image=None, request_id=uuid.uuid4(), day=yesterday + timedelta(days=5))
        from . import reception_permissions as perms
        values = perms.current(self.tenant)
        values.update(dias_anteriores=False)
        perms.save(self.tenant, self.owner, values)
        self.reception.refresh_from_db()
        with self.assertRaises(PermissionDenied):
            s.expense(user=self.reception, unit=self.unit, description="Atrasada", amount="1", method=self.pix, invoice="",
                      items="", image=None, request_id=uuid.uuid4(), day=yesterday)

    def test_desk_expense_with_a_chosen_date_opens_that_day_sheet(self):
        from datetime import timedelta
        from .clinic_models import ClinicExpense
        self.client.force_login(self.owner)
        yesterday = s.business_today(self.tenant) - timedelta(days=1)
        response = self.client.post(reverse("clinic-finance-desk"), {
            "action": "expense", "request_id": str(uuid.uuid4()), "day": yesterday.isoformat(), "description": "Gás",
            "amount": "35", "method": self.cash.pk, "professional": "", "confirmed": "on"})
        row = ClinicExpense.objects.get(transaction__description="Gás")
        self.assertRedirects(response, reverse("clinic-cash-sheet-detail", args=[row.session_id]), fetch_redirect_response=False)
        self.assertEqual(row.session.business_date, yesterday)
        page = self.client.get(reverse("clinic-finance-desk"), {"day": yesterday.isoformat()})
        self.assertContains(page, "Gás")
        self.assertContains(page, "Data da despesa")

    def test_merge_day_joins_professional_sheets_without_changing_totals(self):
        from django.utils import timezone
        from .clinic_models import ClinicCashMerge, ClinicCashWithdrawal, ClinicExpense
        from .models import CashSession
        other = self.second_dentist()
        self.entry(method="pix")  # clinic sheet: Dr. Listado R$ 100
        legacy = self.legacy_sheet(other, opening="20")
        cash.add_entry(user=self.reception, session_id=legacy.pk, customer=self.patient, professional=other,
                       professional_name="", dentist_amount="70", clinic_amount="30", other_amount="0", method=self.cash,
                       notes="", request_id=uuid.uuid4())
        expense = s.expense(user=self.reception, unit=self.unit, description="Broca", amount="10", method=self.cash,
                            invoice="", items="", image=None, request_id=uuid.uuid4())
        ClinicExpense.objects.filter(pk=expense.pk).update(session=legacy, professional=None)
        ClinicCashWithdrawal.objects.create(session=legacy, amount=Decimal("5"), method=self.cash, method_name="Dinheiro",
                                            withdrawn_by="Dra. Segunda", destination="partner", recorded_by=self.reception,
                                            occurred_at=timezone.now(), request_id=uuid.uuid4())
        drawer = cash.expected_cash(self.session) + cash.expected_cash(legacy)
        with self.assertRaises(PermissionDenied):
            cash.merge_day(user=self.reception, unit=self.unit, day=self.session.business_date)
        target = cash.merge_day(user=self.owner, unit=self.unit, day=self.session.business_date)
        self.assertEqual(target.pk, self.session.pk)
        self.assertEqual(list(CashSession.objects.filter(tenant=self.tenant, deleted_at__isnull=True)), [target])
        legacy.refresh_from_db()
        self.assertIsNotNone(legacy.deleted_at)
        self.assertEqual(sorted(target.clinical_entries.values_list("number", flat=True)), [1, 2])
        self.assertEqual(target.opening_amount, Decimal("70"))
        self.assertEqual(cash.expected_cash(target), drawer)
        expense.refresh_from_db()
        self.assertEqual((expense.session_id, expense.professional_id), (target.pk, other.pk))
        rows = {r["professional"]: r for r in cash.by_professional(target)}
        self.assertEqual(rows["Dra. Segunda"]["total"], Decimal("100"))
        self.assertEqual(rows["Dra. Segunda"]["expenses"], Decimal("10"))
        self.assertEqual(rows["Dr. Listado"]["total"], Decimal("100"))
        merge = ClinicCashMerge.objects.get(source=legacy)
        self.assertEqual(len(merge.moved["entries"]), 1)
        self.assertIsNone(cash.merge_day(user=self.owner, unit=self.unit, day=self.session.business_date))

    def test_merge_of_a_closed_day_sums_the_counted_cash(self):
        from datetime import timedelta
        from .models import CashSession
        yesterday = s.business_today(self.tenant) - timedelta(days=1)
        other = self.second_dentist()
        first, second = self.legacy_sheet(self.dentist, yesterday, "10"), self.legacy_sheet(other, yesterday, "0")
        for sheet, value in ((first, "40"), (second, "25")):
            cash.add_entry(user=self.owner, session_id=sheet.pk, customer=self.patient, professional=sheet.professional,
                           professional_name="", dentist_amount=value, clinic_amount="0", other_amount="0",
                           method=self.cash, notes="", request_id=uuid.uuid4())
        s.close_clinic_cash(user=self.owner, unit=self.unit, amount="50", session_id=first.pk)   # exato
        s.close_clinic_cash(user=self.owner, unit=self.unit, amount="20", session_id=second.pk)  # faltam 5
        target = cash.merge_day(user=self.owner, unit=self.unit, day=yesterday)
        self.assertEqual(target.status, "closed")
        self.assertIsNone(target.professional_id)
        self.assertEqual((target.closing_amount, target.expected_amount, target.difference_amount),
                         (Decimal("70"), Decimal("75"), Decimal("-5")))
        summary = target.clinical_closing.summary
        self.assertEqual(summary["unified_from"], 2)
        self.assertEqual({p["professional"] for p in summary["professionals"]}, {"Dr. Listado", "Dra. Segunda"})
        self.assertEqual(CashSession.objects.filter(business_date=yesterday, deleted_at__isnull=True).count(), 1)

    def test_cash_days_page_offers_and_runs_the_unification(self):
        other = self.second_dentist()
        self.legacy_sheet(other)
        self.client.force_login(self.owner)
        url = reverse("clinic-cash-days")
        self.assertContains(self.client.get(url), "Unificar todos os dias")
        response = self.client.post(url, {"action": "merge-all"}, follow=True)
        self.assertContains(response, "unificados no caixa da clínica")
        self.assertNotContains(self.client.get(url), "Unificar todos os dias")
