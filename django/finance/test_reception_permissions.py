import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog
from scheduling.models import Professional

from . import clinic_cash as cash
from . import clinic_services as s
from . import reception_permissions as perms
from . import test_clinic_desk as desk
from .clinic_models import ClinicCashEntry, ClinicCashEntryRemoval
from .models import CashSession


class ReceptionPermissionTests(TestCase):
    def setUp(self):
        desk.ClinicDeskTests.setUp(self)
        self.dentist = Professional.objects.create(tenant=self.tenant, name="Dra. Permissão")
        self.session = s.open_clinic_cash(self.reception, self.unit, "0")

    def entry(self, user=None):
        return cash.add_entry(user=user or self.reception, session_id=self.session.pk, customer=self.patient,
                              professional=self.dentist, professional_name="", dentist_amount="30", clinic_amount="20",
                              other_amount="0", method=self.cash, notes="", request_id=uuid.uuid4())

    def set_perms(self, **values):
        base = perms.current(self.tenant)
        base.update(values)
        perms.save(self.tenant, self.owner, base)
        self.reception.refresh_from_db()

    def test_only_manager_saves_permissions_and_it_is_audited(self):
        with self.assertRaises(PermissionDenied):
            perms.save(self.tenant, self.reception, {"caixa": True})
        self.set_perms(despesas=False)
        self.assertFalse(perms.current(self.tenant)["despesas"])
        self.assertTrue(AuditLog.objects.filter(action="clinic.reception_permissions.updated").exists())
        self.assertEqual(self.client.get(reverse("clinic-reception-permissions")).status_code, 403)
        self.client.force_login(self.owner)
        page = self.client.get(reverse("clinic-reception-permissions"))
        self.assertContains(page, "Apagar lançamento do caixa sem pedir ao gestor")
        self.client.post(reverse("clinic-reception-permissions"), {"caixa": "on", "abrir_fechar": "on"})
        self.tenant.refresh_from_db()
        self.assertFalse(perms.current(self.tenant)["prontuarios"])
        self.assertTrue(perms.current(self.tenant)["caixa"])

    def test_reception_asks_to_delete_line_and_manager_approves(self):
        row = self.entry()
        with self.assertRaises(PermissionDenied):
            cash.cancel_entry(user=self.reception, entry_id=row.pk, reason="Duplicado")
        ask = cash.request_removal(user=self.reception, entry_id=row.pk, reason="Lançado duas vezes")
        self.assertEqual(cash.request_removal(user=self.reception, entry_id=row.pk, reason="de novo").pk, ask.pk)
        with self.assertRaises(PermissionDenied):
            cash.decide_removal(user=self.reception, removal_id=ask.pk, approve=True)
        cash.decide_removal(user=self.owner, removal_id=ask.pk, approve=True, note="ok")
        row.refresh_from_db()
        ask.refresh_from_db()
        self.assertEqual(row.status, ClinicCashEntry.Status.CANCELLED)
        self.assertEqual(ask.status, ClinicCashEntryRemoval.Status.APPROVED)
        other = self.entry()
        no = cash.request_removal(user=self.reception, entry_id=other.pk, reason="Errado")
        cash.decide_removal(user=self.owner, removal_id=no.pk, approve=False)
        other.refresh_from_db()
        self.assertNotEqual(other.status, ClinicCashEntry.Status.CANCELLED)
        self.set_perms(apagar_lancamento=True)
        cash.cancel_entry(user=self.reception, entry_id=other.pk, reason="Liberado pelo gestor")

    def test_manager_deletes_sheet_and_it_leaves_the_by_date_list(self):
        self.entry()
        self.client.force_login(self.owner)
        page = self.client.get(reverse("clinic-cash-days"))
        self.assertContains(page, self.session.label)
        with self.assertRaises(PermissionDenied):
            cash.delete_sheet(user=self.reception, session_id=self.session.pk, reason="Errado")
        with self.assertRaises(ValidationError):
            cash.delete_sheet(user=self.owner, session_id=self.session.pk, reason="")
        response = self.client.post(reverse("clinic-cash-days"), {"action": "delete-sheet", "session": self.session.pk,
                                                                  "reason": "Caixa aberto por engano"})
        self.assertEqual(response.status_code, 302)
        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.deleted_at)
        self.assertFalse(self.session.clinical_entries.exclude(status="cancelled").exists())
        self.assertTrue(AuditLog.objects.filter(action="clinic.cash.deleted").exists())
        self.assertNotContains(self.client.get(reverse("clinic-cash-days")), "Caixa aberto por engano")
        self.assertFalse(CashSession.objects.filter(pk=self.session.pk, deleted_at__isnull=True).exists())

    def test_closed_sheet_needs_earlier_days_permission(self):
        s.close_clinic_cash(user=self.reception, unit=self.unit, amount="50", session_id=self.session.pk)
        self.set_perms(dias_anteriores=False)
        with self.assertRaises(PermissionDenied):
            self.entry()
        self.entry(user=self.owner)

    def test_switches_block_record_cash_and_registration(self):
        self.set_perms(prontuarios=False, caixa=False, cadastro=False)
        self.assertEqual(self.client.get(reverse("dental-patient-record", args=[self.patient.pk])).status_code, 403)
        with self.assertRaises(PermissionDenied):
            self.entry()
        self.set_perms(caixa=False, despesas=False, abrir_fechar=False)
        self.assertEqual(self.client.get(reverse("clinic-finance-desk")).status_code, 403)
