import hashlib
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from billing.models import PaymentGateway
from core.crypto import encrypt_text
from .models import Client, Charge, OnlinePayment
from .revenue import financial_report


@override_settings(SECURE_SSL_REDIRECT=False, TIME_ZONE="America/Recife")
class RevenueTests(TestCase):
    def setUp(self):
        self.master = get_user_model().objects.create_superuser(
            "master-revenue@example.test", None
        )
        user = get_user_model().objects.create_user(
            "revenue@example.test", None, role="development-client"
        )
        self.customer = Client.objects.create(
            user=user,
            kind="cpf",
            name="Cliente projeto",
            document_hash=hashlib.sha256(b"52998224725").hexdigest(),
            document_encrypted=encrypt_text("52998224725"),
        )
        self.month, self.today = date(2026, 10, 1), date(2026, 10, 23)

    def charge(self, amount, due, status="open", paid_at=None, **kwargs):
        return Charge.objects.create(
            client=self.customer,
            description="Projeto",
            amount=amount,
            due_date=due,
            status=status,
            paid_at=paid_at,
            **kwargs,
        )

    def test_totals_use_receipt_date_and_do_not_assume_overdue_recovery(self):
        self.charge(
            "100.11",
            date(2026, 9, 1),
            "paid",
            datetime(2026, 10, 20, 15, tzinfo=dt_timezone.utc),
        )
        self.charge(
            "15.01",
            date(2026, 10, 1),
            "paid",
            datetime(2026, 9, 30, 15, tzinfo=dt_timezone.utc),
        )
        self.charge("200.22", self.today)
        self.charge("300.33", date(2026, 11, 1))
        self.charge("50.44", date(2026, 10, 22))
        self.charge("60.55", date(2026, 9, 1))
        self.charge("9999.99", self.today, "cancelled")
        report = financial_report(self.month, today=self.today)
        totals = report["totals"]
        self.assertEqual(totals["received_month"], Decimal("100.11"))
        self.assertEqual(totals["received"], Decimal("115.12"))
        self.assertEqual(totals["due_month"], Decimal("200.22"))
        self.assertEqual(totals["overdue"], Decimal("110.99"))
        self.assertEqual(totals["to_receive"], Decimal("611.54"))
        self.assertEqual(totals["forecast_month"], Decimal("300.33"))
        self.assertEqual(report["months"][0]["overdue"], Decimal("50.44"))
        self.assertEqual(report["months"][1]["forecast"], Decimal("300.33"))
        self.assertEqual(report["months"][-1]["month"], date(2027, 9, 1))

    def test_review_excluded_without_duplicate_join_or_invented_refund_amount(self):
        paid = self.charge(
            "500.00",
            self.today,
            "paid",
            datetime(2026, 10, 23, 15, tzinfo=dt_timezone.utc),
        )
        valid = self.charge("123.45", self.today, "paid")
        gateway = PaymentGateway.objects.create(environment="production")
        for state in ["failed", "refunded"]:
            OnlinePayment.objects.create(
                charge=paid,
                gateway=gateway,
                method="card",
                amount=paid.amount,
                charge_revision=1,
                status=state,
            )
        for _ in range(2):
            OnlinePayment.objects.create(
                charge=valid,
                gateway=gateway,
                method="card",
                amount=valid.amount,
                charge_revision=1,
                status="failed",
            )
        report = financial_report(self.month, today=self.today)
        self.assertEqual(report["totals"]["received"], Decimal("123.45"))
        self.assertEqual(report["totals"]["received_month"], 0)
        self.assertEqual(report["totals"]["undated_paid"], 1)
        self.assertEqual(report["totals"]["review_count"], 1)

    def test_date_timezone_filter_inactive_client_and_empty_state(self):
        self.customer.active = False
        self.customer.save()
        self.charge(
            "0.01", self.today, "paid", datetime(2026, 10, 1, 1, tzinfo=dt_timezone.utc)
        )
        report = financial_report(self.month, self.customer, today=self.today)
        self.assertEqual(report["totals"]["received"], Decimal("0.01"))
        self.assertEqual(report["totals"]["received_month"], 0)
        self.assertFalse(list(report["customers"])[0]["client__active"])
        self.client.force_login(self.master)
        response = self.client.get(
            reverse("development-revenue"),
            {"month": "2026-10", "client": self.customer.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Projeção de 12 meses")

    def test_master_only_and_invalid_filter_never_exposes_other_totals(self):
        url = reverse("development-revenue")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.customer.user)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.master)
        for data in [
            {"month": "garbage"},
            {"month": "9999-12"},
            {"month": "2026-10", "client": "999999"},
        ]:
            response = self.client.get(url, data)
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.context["report"])
        response = self.client.get(url)
        self.assertEqual(response.context["report"]["totals"]["received"], 0)
        self.assertContains(response, "R$ 0,00")

    def test_client_filter_isolates_every_total(self):
        other_user = get_user_model().objects.create_user(
            "other-revenue@example.test", None
        )
        other = Client.objects.create(
            user=other_user, name="Outro", kind="cpf", document_hash="other"
        )
        self.charge("19.99", self.today)
        Charge.objects.create(
            client=other,
            description="Outro projeto",
            amount="999.00",
            due_date=self.today,
        )
        report = financial_report(self.month, self.customer, today=self.today)
        self.assertEqual(report["totals"]["to_receive"], Decimal("19.99"))
        self.assertEqual(len(list(report["customers"])), 1)
