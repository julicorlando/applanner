"""Painel do caixa do dia, fechamento com conferência por forma de pagamento e relatório do caixa."""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog
from scheduling.models import Professional

from . import clinic_cash as cash
from . import clinic_services as s
from . import reception_permissions as perms
from . import test_clinic_desk as desk
from .clinic_models import ClinicCashClosing, ClinicCashEntry
from .models import CashSession


class CashPanelTests(TestCase):
    def setUp(self):
        desk.ClinicDeskTests.setUp(self)
        from billing.models import Module, TenantModuleAddon
        extra, _ = Module.objects.get_or_create(slug="dental-professional-extra", defaults={"name": "Dentista extra", "active": True})
        TenantModuleAddon.objects.create(tenant=self.tenant, module=extra, monthly_price=0, quantity=2,
                                         status=TenantModuleAddon.Status.ACTIVE)  # a second dentist seat
        self.ana = Professional.objects.create(tenant=self.tenant, name="Dra. Ana Exemplo")
        self.bruno = Professional.objects.create(tenant=self.tenant, name="Dr. Bruno Exemplo")
        self.today = s.business_today(self.tenant)
        self.url = reverse("clinic-cash-panel")

    def sheet(self, professional, opening="0", day=None):
        return s.open_clinic_cash(self.owner, self.unit, opening, professional=professional, day=day)

    def line(self, session, total="100", method="cash", professional=None):
        return cash.add_entry(user=self.reception, session_id=session.pk, customer=self.patient,
                              professional=professional or session.professional, professional_name="",
                              dentist_amount=total, clinic_amount="0", other_amount="0",
                              method=getattr(self, method) if method else None, notes="", request_id=uuid.uuid4())

    def set_perms(self, **values):
        base = perms.current(self.tenant)
        base.update(values)
        perms.save(self.tenant, self.owner, base)
        self.reception.refresh_from_db()

    # ------------------------------------------------------------ painel do dia

    def test_empty_day_shows_empty_state_and_open_action(self):
        page = self.client.get(self.url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Nenhum caixa aberto hoje")
        self.assertContains(page, "data-open-cash")
        self.assertEqual(page.context["kpis"]["sheets"], 0)
        self.assertEqual({p.name for p in page.context["without_sheet"]}, {"Dra. Ana Exemplo", "Dr. Bruno Exemplo"})

    def test_day_groups_cards_by_professional_with_kpis_and_methods(self):
        ana, bruno = self.sheet(self.ana, "20"), self.sheet(self.bruno)
        self.line(ana, "100", "cash")
        self.line(ana, "50", "pix")
        self.line(bruno, "80", "card")
        self.line(bruno, "40", None)  # em aberto
        page = self.client.get(self.url)
        cards = {c["label"]: c for c in page.context["cards"]}
        self.assertEqual(cards["Dra. Ana Exemplo"]["received"], Decimal("150"))
        self.assertEqual(cards["Dra. Ana Exemplo"]["drawer_expected"], Decimal("120"))
        self.assertEqual(cards["Dr. Bruno Exemplo"]["open_total"], Decimal("40"))
        kpis = page.context["kpis"]
        self.assertEqual((kpis["received"], kpis["open_total"], kpis["open"], kpis["sheets"]),
                         (Decimal("230"), Decimal("40"), 2, 2))
        self.assertEqual({m["kind"]: m["amount"] for m in page.context["methods"]},
                         {"cash": Decimal("100"), "pix": Decimal("50"), "card": Decimal("80")})
        self.assertContains(page, "Conferir e fechar")
        self.assertEqual([p.name for p in page.context["without_sheet"]], [])

    def test_day_navigation_never_goes_to_the_future(self):
        yesterday = self.today - timedelta(days=1)
        page = self.client.get(self.url + f"?dia={yesterday.isoformat()}")
        self.assertEqual(page.context["day"], yesterday)
        self.assertEqual(page.context["next_day"], self.today)
        future = self.client.get(self.url + f"?dia={(self.today + timedelta(days=3)).isoformat()}")
        self.assertEqual(future.context["day"], self.today)
        self.assertIsNone(future.context["next_day"])
        self.assertEqual(self.client.get(self.url + "?dia=lixo").context["day"], self.today)

    # ------------------------------------------------------------ abertura

    def test_open_from_panel_per_professional_and_no_duplicate(self):
        response = self.client.post(self.url, {"action": "open", "professional": self.ana.pk, "opening": "30", "notes": "Troco"})
        self.assertEqual(response.status_code, 302)
        row = CashSession.objects.get(professional=self.ana)
        self.assertEqual((row.opening_amount, row.business_date, row.status), (Decimal("30"), self.today, "open"))
        self.client.post(self.url, {"action": "open", "professional": self.ana.pk, "opening": "0"})
        self.assertEqual(CashSession.objects.filter(professional=self.ana).count(), 1)
        with self.assertRaises(ValidationError):
            s.open_clinic_cash(self.owner, self.unit, "0", day=self.today + timedelta(days=1))

    def test_opening_an_earlier_day_follows_reception_permission(self):
        yesterday = self.today - timedelta(days=1)
        self.set_perms(dias_anteriores=False)
        page = self.client.get(self.url + f"?dia={yesterday.isoformat()}")
        self.assertNotContains(page, 'id="cp-open"')
        refused = self.client.post(self.url, {"action": "open", "dia": yesterday.isoformat(), "professional": self.ana.pk, "opening": "0"})
        self.assertEqual(refused.status_code, 403)
        self.set_perms(dias_anteriores=True)
        self.client.post(self.url, {"action": "open", "dia": yesterday.isoformat(), "professional": self.ana.pk, "opening": "0"})
        self.assertTrue(CashSession.objects.filter(professional=self.ana, business_date=yesterday).exists())

    def test_without_open_close_permission_the_panel_is_read_only(self):
        self.sheet(self.ana)
        self.set_perms(abrir_fechar=False)
        page = self.client.get(self.url)
        self.assertNotContains(page, 'id="cp-open"')
        self.assertNotContains(page, 'id="cp-close"')
        self.assertEqual(self.client.post(self.url, {"action": "open", "opening": "0"}).status_code, 403)

    # ------------------------------------------------------------ fechamento

    def test_closing_with_matching_conference_saves_every_method(self):
        session = self.sheet(self.ana, "20")
        self.line(session, "100", "cash")
        self.line(session, "50", "pix")
        self.client.post(self.url, {"action": "close", "session": session.pk, "counted_cash": "120",
                                    "counted_pix": "50", "counted_card": "0"})
        session.refresh_from_db()
        self.assertEqual((session.status, session.difference_amount), ("closed", Decimal("0")))
        summary = ClinicCashClosing.objects.get(session=session).summary
        self.assertEqual(summary["conference"]["pix"], {"expected": "50.00", "informed": "50.00", "difference": "0.00"})
        self.assertEqual(summary["divergent"], [])
        card = self.client.get(self.url).context["cards"][0]
        self.assertEqual(card["status"], "closed")
        self.assertEqual([label for label, _ in card["conference_rows"]], ["Dinheiro", "Pix", "Débito/Crédito"])

    def test_divergence_needs_a_note_and_is_flagged(self):
        session = self.sheet(self.ana)
        self.line(session, "80", "card")
        post = {"action": "close", "session": session.pk, "counted_cash": "0", "counted_pix": "0", "counted_card": "70"}
        response = self.client.post(self.url, post, follow=True)
        self.assertContains(response, "Explique na observação")
        session.refresh_from_db()
        self.assertEqual(session.status, "open")
        self.client.post(self.url, {**post, "notes": "Maquininha recusou uma parcela"})
        session.refresh_from_db()
        self.assertEqual(session.status, "closed")
        summary = ClinicCashClosing.objects.get(session=session).summary
        self.assertEqual((summary["divergent"], summary["conference"]["card"]["difference"]), (["card"], "-10.00"))
        page = self.client.get(self.url)
        self.assertEqual(page.context["cards"][0]["status"], "divergent")
        self.assertEqual(page.context["kpis"]["divergent"], 1)
        self.assertTrue(AuditLog.objects.filter(action="clinic.cash.closed", entity_id=session.pk).exists())

    def test_legacy_close_without_conference_still_works(self):
        session = self.sheet(self.ana, "10")
        closed = s.close_clinic_cash(user=self.reception, unit=self.unit, amount="5", session_id=session.pk)
        self.assertEqual(closed.difference_amount, Decimal("-5"))  # no note required outside the new flow

    # ------------------------------------------------------------ folha: caixa fechado

    def test_changing_a_closed_sheet_requires_explicit_confirmation(self):
        session = self.sheet(self.ana)
        s.close_clinic_cash(user=self.owner, unit=self.unit, amount="0", session_id=session.pk)
        url = reverse("clinic-cash-sheet-detail", args=[session.pk])
        page = self.client.get(url)
        self.assertContains(page, 'name="confirm_closed"')
        self.assertContains(page, "Fechado")
        data = {"action": "add", "request_id": str(uuid.uuid4()), "customer": self.patient.pk, "professional": self.ana.pk,
                "professional_name": "", "dentist_amount": "30", "clinic_amount": "0", "other_amount": "0",
                "method": self.cash.pk, "notes": ""}
        refused = self.client.post(url, data)
        self.assertContains(refused, "Este caixa já foi fechado")
        self.assertFalse(ClinicCashEntry.objects.exists())
        self.client.post(url, {**data, "confirm_closed": "1"})
        self.assertEqual(ClinicCashEntry.objects.get().session_id, session.pk)
        self.assertTrue(AuditLog.objects.filter(action="clinic.cash_report.recalculated", entity_id=session.pk).exists())

    # ------------------------------------------------------------ relatório

    def test_report_filters_kpis_and_groupings(self):
        ana, bruno = self.sheet(self.ana), self.sheet(self.bruno)
        self.line(ana, "100", "cash")
        self.line(ana, "60", "pix")
        self.line(bruno, "90", "card")
        s.close_clinic_cash(user=self.owner, unit=self.unit, amount="10", session_id=ana.pk, notes="Faltou troco")
        report_url = reverse("clinic-cash-report")
        page = self.client.get(report_url)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["kpis"]["received"], Decimal("250"))
        self.assertEqual({p["label"]: p["received"] for p in page.context["by_professional"]},
                         {"Dra. Ana Exemplo": Decimal("160"), "Dr. Bruno Exemplo": Decimal("90")})
        self.assertEqual(len(page.context["by_day"]), 1)
        only_ana = self.client.get(report_url, {"profissional": self.ana.pk})
        self.assertEqual([r["label"] for r in only_ana.context["sheets"]], ["Dra. Ana Exemplo"])
        divergent = self.client.get(report_url, {"status": "divergent"})
        self.assertEqual([r["session"].pk for r in divergent.context["sheets"]], [ana.pk])
        opened = self.client.get(report_url, {"status": "open"})
        self.assertEqual([r["session"].pk for r in opened.context["sheets"]], [bruno.pk])
        pix = self.client.get(report_url, {"forma": "pix"})
        self.assertEqual(pix.context["kpis"]["received"], Decimal("60"))
        empty = self.client.get(report_url, {"periodo": "mes-passado", "profissional": self.bruno.pk})
        self.assertContains(empty, "Nenhum caixa encontrado")
        self.assertTrue(AuditLog.objects.filter(action="clinic.cash_report.viewed").exists())

    def test_report_csv_export(self):
        session = self.sheet(self.ana)
        self.line(session, "123.45", "pix")
        response = self.client.get(reverse("clinic-cash-report"), {"formato": "csv"})
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment;", response["Content-Disposition"])
        body = response.content.decode("utf-8-sig")
        self.assertIn("Data;Caixa;Situação", body)
        self.assertIn("Dra. Ana Exemplo;Aberto;1;123,45", body)

    def test_report_period_is_capped_and_custom_range_is_read(self):
        page = self.client.get(reverse("clinic-cash-report"), {"de": "2020-01-01", "ate": self.today.isoformat()})
        filters = page.context["filters"]
        self.assertEqual(filters["preset"], "personalizado")
        self.assertLessEqual((filters["end"] - filters["start"]).days, 366)

    def test_desk_points_to_the_new_panel(self):
        page = self.client.get(reverse("clinic-finance-desk"))
        self.assertContains(page, reverse("clinic-cash-panel"))
        self.assertContains(page, reverse("clinic-cash-report"))
