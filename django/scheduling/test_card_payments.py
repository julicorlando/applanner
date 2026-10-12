from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, Mock
from django.test import TestCase
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from core.crypto import encrypt_json
from finance import test_advanced_operations
from billing.models import TenantPaymentConnection, TenantPaymentTransaction
from billing.tenant_card_integrity import validate_card_event
from scheduling.models import TenantScheduleSettings
from scheduling.settlement import settle_appointment
from finance.advanced_services import cash_balance
from finance.dre import cash_flow


class CardBookingTests(TestCase):
    def setUp(self):
        cache.clear()
        test_advanced_operations.AdvancedOperationsTests.setUp(self)
        self.tenant.public_slug = "advanced-ops"
        self.tenant.save()
        self.customer.email = "card@example.test"
        self.customer.save()
        self.appt.customer = self.customer
        self.appt.starts_at = timezone.now() + timedelta(days=1)
        self.appt.ends_at = self.appt.starts_at + timedelta(minutes=30)
        self.appt.booking_payment = "full"
        self.appt.booking_payment_amount = 50
        import hashlib

        self.token = "synthetic-appointment-manage-card"
        self.appt.customer_manage_token_hash = hashlib.sha256(
            self.token.encode()
        ).hexdigest()
        self.appt.save()
        TenantScheduleSettings.objects.create(
            tenant=self.tenant,
            online_booking_payments_enabled=True,
            card_booking_payments_enabled=True,
        )
        self.connection = TenantPaymentConnection.objects.create(
            tenant=self.tenant,
            environment="sandbox",
            status="connected",
            metadata={"public_key": "TEST-public-key-for-card-ui", "user_id": 123},
            credentials_encrypted=encrypt_json(
                {
                    "access_token": "TEST-provider-credential-only",
                    "webhook_secret": "test-webhook-secret-123",
                }
            ),
        )
        self.url = reverse("public-appointment-card-submit", args=[self.token])
        self.data = {
            "card_token": "tokenized-card-test-only",
            "payment_method_id": "visa",
            "installments": 1,
            "attempt_id": "attempt-test-card-123456",
        }

    def remote(self):
        return {
            "id": "card-test-123",
            "status": "approved",
            "fee_amount": Decimal("1"),
            "net_received_amount": Decimal("49"),
            "transaction_amount": Decimal("50"),
        }

    def test_tokenized_card_is_charged_once_with_server_price(self):
        provider = Mock()
        provider.create_tokenized_card_payment.return_value = self.remote()
        with patch("billing.payment_services.tenant_provider", return_value=provider):
            first = self.client.post(
                self.url, self.data, content_type="application/json"
            )
            second = self.client.post(
                self.url, self.data, content_type="application/json"
            )
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(provider.create_tokenized_card_payment.call_count, 1)
        self.assertEqual(
            provider.create_tokenized_card_payment.call_args.kwargs["amount"], 50
        )
        self.assertEqual(TenantPaymentTransaction.objects.get().status, "paid")
        self.assertIsNotNone(TenantPaymentTransaction.objects.get().paid_at)

    def test_price_override_pan_or_unknown_token_are_rejected(self):
        for data in [
            {**self.data, "amount": 1},
            {**self.data, "card_number": "4111111111111111"},
            [1],
        ]:
            self.assertEqual(
                self.client.post(
                    self.url, data, content_type="application/json"
                ).status_code,
                400,
            )
        self.assertFalse(TenantPaymentTransaction.objects.exists())
        self.assertEqual(
            self.client.post(
                reverse("public-appointment-card-submit", args=["other-token"]),
                self.data,
                content_type="application/json",
            ).status_code,
            404,
        )

    def test_uncertain_charge_blocks_new_attempt_until_reconciliation(self):
        provider = Mock()
        provider.create_tokenized_card_payment.side_effect = TimeoutError
        with patch("billing.payment_services.tenant_provider", return_value=provider):
            self.assertEqual(
                self.client.post(
                    self.url, self.data, content_type="application/json"
                ).status_code,
                502,
            )
            self.assertEqual(
                self.client.post(
                    self.url,
                    {**self.data, "attempt_id": "second-attempt-test-1234"},
                    content_type="application/json",
                ).status_code,
                400,
            )
        self.assertEqual(provider.create_tokenized_card_payment.call_count, 1)
        self.assertEqual(TenantPaymentTransaction.objects.get().status, "pending")

    def test_webhook_integrity_validates_all_financial_identifiers(self):
        tx = TenantPaymentTransaction.objects.create(
            tenant=self.tenant,
            connection=self.connection,
            reference_type="appointment",
            reference_id=self.appt.pk,
            external_reference="CARD-REFERENCE",
            method="card",
            gross_amount=50,
            net_amount=50,
            idempotency_key="integrity-card",
        )
        data = {
            "id": "card-1",
            "transaction_amount": 50,
            "currency_id": "BRL",
            "external_reference": "CARD-REFERENCE",
            "live_mode": False,
            "collector_id": 123,
            "status": "approved",
        }
        validate_card_event(tx, data, "card-1")
        for override in [
            {"transaction_amount": 1},
            {"currency_id": "USD"},
            {"collector_id": 456},
            {"live_mode": True},
            {"external_reference": "else"},
            {"id": "other"},
        ]:
            with self.assertRaises(ValueError):
                validate_card_event(tx, {**data, **override}, "card-1")

    def test_partial_card_is_not_counted_as_cash_and_flow_does_not_duplicate(self):
        self.appt.booking_payment = "partial"
        self.appt.booking_payment_amount = 20
        self.appt.starts_at = timezone.now() - timedelta(minutes=15)
        self.appt.ends_at = timezone.now() + timedelta(minutes=15)
        self.appt.save()
        TenantPaymentTransaction.objects.create(
            tenant=self.tenant,
            connection=self.connection,
            reference_type="appointment",
            reference_id=self.appt.pk,
            external_reference="PREPAY-CARD",
            method="card",
            gross_amount=20,
            net_amount=19,
            fee_amount=1,
            status="paid",
            paid_at=timezone.now(),
            idempotency_key="paid-card",
        )
        settle_appointment(
            appointment_id=self.appt.pk,
            professional=self.pro,
            user=self.owner,
            attended=True,
            payment_method="cash",
        )
        self.assertEqual(cash_balance(self.session), 130)
        flow = cash_flow(
            self.tenant, timezone.localdate(), timezone.localdate(), self.unit
        )
        self.assertEqual(flow["income"], 50)
        self.assertEqual(flow["expense"], 1)

    def test_authorized_card_is_not_recognized_as_captured_payment(self):
        from billing.tenant_card_integrity import card_status

        self.assertEqual(card_status({"status": "authorized"}), "pending")
        self.assertEqual(card_status({"status": "approved"}), "paid")
