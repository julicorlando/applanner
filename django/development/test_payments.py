import hashlib
import hmac
import json
import time
import uuid
from datetime import date
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, Client as Browser, override_settings
from django.urls import reverse
from billing.models import PaymentGateway
from core.crypto import encrypt_text
from core.models import AuditLog
from .models import Client, Charge, OnlinePayment, Delivery
from .payments import start_payment, apply_remote, reconcile, configured_gateway


@override_settings(
    PUBLIC_BASE_URL="https://applanner.example",
    SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class PaymentTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "payer@example.com", None, role="development-client"
        )
        self.customer = Client.objects.create(
            user=self.user,
            kind="cpf",
            name="Cliente teste",
            document_encrypted=encrypt_text("52998224725"),
            document_hash="a" * 64,
            phone="5581999990000",
        )
        self.charge = Charge.objects.create(
            client=self.customer,
            description="Projeto",
            amount="250.00",
            due_date=date(2026, 11, 10),
        )
        self.gateway = PaymentGateway.objects.create(
            provider="mercadopago",
            environment="production",
            active=True,
            public_key="APP_USR-public",
            access_token_encrypted=encrypt_text("APP_USR-test"),
            webhook_secret_encrypted=encrypt_text("test-secret"),
            last_test_status="validated",
        )
        self.client.force_login(self.user)

    def attempt(self, method="pix", **kwargs):
        return OnlinePayment.objects.create(
            charge=self.charge,
            gateway=self.gateway,
            method=method,
            amount=self.charge.amount,
            charge_revision=self.charge.revision,
            collector_id="321",
            **kwargs,
        )

    def remote(self, row, **changes):
        data = {
            "id": "12345",
            "transaction_amount": "250.00",
            "currency_id": "BRL",
            "external_reference": row.reference,
            "live_mode": True,
            "collector_id": "321",
            "payment_method_id": "pix" if row.method == "pix" else "visa",
            "payment_type_id": "bank_transfer"
            if row.method == "pix"
            else "credit_card",
            "status": "approved",
        }
        data.update(changes)
        return data

    @patch("development.payments.platform_provider")
    def test_card_page_only_renders_secure_form(self, provider):
        response = self.client.get(reverse("development-card", args=[self.charge.pk]))
        self.assertContains(response, "sdk.mercadopago.com")
        self.assertContains(response, "APP_USR-public")
        self.assertContains(response, '"amount": "250.00"')
        self.assertNotContains(response, "APP_USR-test")
        self.assertEqual(OnlinePayment.objects.count(), 0)
        provider.assert_not_called()

    @patch("development.payments.platform_provider")
    def test_pix_uses_existing_gateway_and_is_idempotent(self, mocked):
        provider = mocked.return_value
        provider.test_connection.return_value = {"id": 321}

        def response(*args):
            row = OnlinePayment.objects.get()
            self.assertEqual(row.collector_id, "321")
            self.assertEqual(
                args[2]["payer"]["identification"]["number"], "52998224725"
            )
            self.assertEqual(args[2]["transaction_amount"], 250)
            return self.remote(
                row,
                status="pending",
                point_of_interaction={"transaction_data": {"qr_code": "PIX-CODE"}},
            )

        provider._request.side_effect = response
        key = uuid.uuid4()
        row = start_payment(self.charge.pk, "pix", key)
        self.assertEqual(row.status, "pending")
        self.assertEqual(row.pix_code, "PIX-CODE")
        self.assertEqual(row.gateway_id, self.gateway.pk)
        self.assertEqual(start_payment(self.charge.pk, "pix", key).pk, row.pk)
        self.assertEqual(start_payment(self.charge.pk, "card", uuid.uuid4()).pk, row.pk)
        self.assertEqual(provider._request.call_count, 1)
        page = self.client.get(reverse("development-charge", args=[self.charge.pk]))
        self.assertContains(page, "PIX-CODE")
        self.assertNotContains(page, "Pagar com cartão")

    def test_only_active_validated_production_gateway(self):
        for field, value in [
            ("active", False),
            ("environment", "sandbox"),
            ("last_test_status", "failed"),
        ]:
            with self.subTest(field=field):
                original = getattr(self.gateway, field)
                setattr(self.gateway, field, value)
                self.gateway.save()
                self.assertIsNone(configured_gateway())
                with (
                    patch("development.payments.platform_provider") as provider,
                    self.assertRaises(ValidationError),
                ):
                    start_payment(self.charge.pk, "pix", uuid.uuid4())
                provider.assert_not_called()
                setattr(self.gateway, field, original)
                self.gateway.save()

    @patch("development.payments.platform_provider")
    def test_timeout_blocks_new_payment_and_later_reconciles(self, mocked):
        mocked.return_value.test_connection.return_value = {"id": 321}
        mocked.return_value._request.side_effect = TimeoutError
        row = start_payment(self.charge.pk, "pix", uuid.uuid4())
        self.assertEqual(row.status, "unknown")
        self.assertEqual(row.collector_id, "321")
        self.assertEqual(start_payment(self.charge.pk, "pix", uuid.uuid4()).pk, row.pk)
        self.assertEqual(mocked.return_value._request.call_count, 1)
        mocked.return_value.search_payments.return_value = {
            "results": [self.remote(row)]
        }
        self.assertEqual(reconcile(row.pk).status, "paid")
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status, "paid")

    def test_verified_approval_stops_reminders_once(self):
        row = self.attempt()
        delivery = Delivery.objects.create(
            client=self.customer,
            charge=self.charge,
            channel="whatsapp",
            key="reminder",
            payload_encrypted="secret",
        )
        apply_remote(row.pk, self.remote(row))
        apply_remote(row.pk, self.remote(row))
        self.charge.refresh_from_db()
        delivery.refresh_from_db()
        self.assertEqual(self.charge.status, "paid")
        self.assertEqual(delivery.status, "cancelled")
        self.assertEqual(delivery.payload_encrypted, "")
        self.assertEqual(
            AuditLog.objects.filter(action="development.online-payment-paid").count(), 1
        )

    def test_authorized_is_not_paid_and_stale_events_do_not_revert(self):
        row = self.attempt("card")
        self.assertEqual(
            apply_remote(row.pk, self.remote(row, status="authorized")).status,
            "pending",
        )
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status, "open")
        apply_remote(row.pk, self.remote(row))
        self.assertEqual(
            apply_remote(row.pk, self.remote(row, status="pending")).status, "paid"
        )
        self.assertEqual(
            apply_remote(row.pk, self.remote(row, status="refunded")).status, "refunded"
        )
        self.assertEqual(apply_remote(row.pk, self.remote(row)).status, "refunded")
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status, "paid")

    def test_rejects_mismatched_provider_data(self):
        row = self.attempt()
        for values in [
            {"transaction_amount": "0.01"},
            {"transaction_amount": "NaN"},
            {"currency_id": "USD"},
            {"external_reference": "wrong"},
            {"live_mode": False},
            {"collector_id": "999"},
            {"id": "invalid"},
            {"payment_method_id": "visa"},
        ]:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                apply_remote(row.pk, self.remote(row, **values))
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status, "open")

    def test_late_payment_needs_master_review(self):
        row = self.attempt()
        self.charge.status = "cancelled"
        self.charge.save()
        self.assertEqual(apply_remote(row.pk, self.remote(row)).status, "attention")
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status, "cancelled")

    @patch("development.payments.platform_provider")
    def test_card_uses_server_amount_and_identity_without_storing_token(self, mocked):
        provider = mocked.return_value
        provider.test_connection.return_value = {"id": 321}
        provider.create_tokenized_card_payment.side_effect = lambda **kwargs: (
            self.remote(OnlinePayment.objects.get())
        )
        response = self.client.post(
            reverse("development-card", args=[self.charge.pk]),
            data=json.dumps(
                {
                    "card_token": "mock-token-123",
                    "payment_method_id": "visa",
                    "installments": 1,
                    "issuer_id": "123",
                    "attempt_id": uuid.uuid4().hex,
                    "amount": "0.01",
                    "identification": {"number": "evil"},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "paid")
        args = provider.create_tokenized_card_payment.call_args.kwargs
        self.assertEqual(str(args["amount"]), "250.00")
        self.assertEqual(args["identification"]["number"], "52998224725")
        row = OnlinePayment.objects.get()
        self.assertNotIn("mock-token-123", str(row.__dict__))

    @patch("development.payments.platform_provider")
    def test_csrf_and_ownership_and_get_cannot_start_payment(self, provider):
        url = reverse("development-pix", args=[self.charge.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        secure = Browser(enforce_csrf_checks=True)
        secure.force_login(self.user)
        self.assertEqual(secure.post(url).status_code, 403)
        other = get_user_model().objects.create_user(
            "other@example.com", None, role="development-client"
        )
        Client.objects.create(
            user=other,
            kind="cpf",
            name="Outro",
            document_hash="b" * 64,
            document_encrypted=encrypt_text("52998224725"),
        )
        self.client.force_login(other)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertEqual(
            self.client.get(
                reverse("development-card", args=[self.charge.pk])
            ).status_code,
            404,
        )
        provider.assert_not_called()

    @patch("development.payments.platform_provider")
    def test_signed_webhook_fetches_remote_and_rejects_forged_status(self, mocked):
        row = self.attempt()
        url = (
            reverse("development-payment-webhook", args=[row.public_id])
            + "?data.id=12345"
        )
        anonymous = Browser()
        self.assertEqual(
            anonymous.post(url, data="{}", content_type="application/json").status_code,
            403,
        )
        mocked.assert_not_called()
        ts = str(int(time.time()))
        manifest = f"id:12345;request-id:test-request;ts:{ts};"
        sig = hmac.new(b"test-secret", manifest.encode(), hashlib.sha256).hexdigest()
        mocked.return_value.get_payment.return_value = self.remote(
            row, status="pending"
        )
        response = anonymous.post(
            url,
            data='{"status":"approved"}',
            content_type="application/json",
            HTTP_X_REQUEST_ID="test-request",
            HTTP_X_SIGNATURE=f"ts={ts},v1={sig}",
        )
        self.assertEqual(response.status_code, 200)
        mocked.return_value.get_payment.assert_called_once_with("12345")
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status, "open")
