import base64
import hashlib
import json
import uuid
from datetime import datetime, time, timedelta
from unittest.mock import patch
from urllib.parse import urlsplit
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client as Browser, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from billing.models import PaymentGateway
from core.crypto import encrypt_text, decrypt_json
from .models import Charge, Client, PaymentLink
from .payment_links import create_payment_link, find_link, SESSION_KEY
from .services import queue_reminder
from .tasks import deliver


@override_settings(
    PUBLIC_BASE_URL="https://applanner.example",
    ALLOWED_HOSTS=["applanner.example", "testserver"],
    SECURE_SSL_REDIRECT=False,
    TIME_ZONE="America/Recife",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class PaymentLinkTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            "linkpayer@example.test", None, role="development-client"
        )
        self.customer = Client.objects.create(
            user=self.user,
            kind="cpf",
            name="Nome privado",
            phone="5581999990000",
            document_hash=hashlib.sha256(b"52998224725").hexdigest(),
            document_encrypted=encrypt_text("52998224725"),
        )
        self.charge = Charge.objects.create(
            client=self.customer,
            description="Projeto privado",
            amount="250.00",
            due_date=timezone.localdate(),
            boleto_encrypted=encrypt_text(base64.b64encode(b"%PDF-1.7\nDEMO").decode()),
        )
        self.link, url = create_payment_link(self.charge, self.customer)
        self.path = urlsplit(url).path
        self.detail = reverse("development-charge", args=[self.charge.pk])

    def unlock(self, browser=None):
        return (browser or self.client).post(self.path, {"document": "529.982.247-25"})

    def test_document_unlock_is_invoice_scoped_and_does_not_log_in(self):
        page = self.client.get(self.path)
        self.assertNotContains(page, "Nome privado")
        self.assertNotContains(page, "Projeto privado")
        self.assertNotContains(page, "250,00")
        self.assertEqual(self.client.get(self.detail).status_code, 302)
        wrong = self.client.post(self.path, {"document": "11111111111"})
        self.assertEqual(wrong.status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(self.unlock().status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(self.client.get(self.detail), "Projeto privado")
        self.assertNotContains(self.client.get(self.detail), "Meus pagamentos")
        file = self.client.get(reverse("development-boleto", args=[self.charge.pk]))
        self.assertEqual(file.content, b"%PDF-1.7\nDEMO")
        other = Charge.objects.create(
            client=self.customer,
            description="Outra cobrança",
            amount="10.00",
            due_date=self.charge.due_date,
        )
        self.assertEqual(
            self.client.get(reverse("development-charge", args=[other.pk])).status_code,
            302,
        )
        self.assertEqual(
            self.client.get(reverse("development-payments")).status_code, 302
        )
        self.assertEqual(
            self.client.get(reverse("development-clients")).status_code, 302
        )

    def test_revocation_expiry_document_and_client_changes_invalidate_grants(self):
        self.unlock()
        token = self.path.rstrip("/").rsplit("/", 1)[-1]
        self.assertNotIn(token, str(self.link.__dict__))
        self.assertIsNotNone(find_link(token))
        for changes in [
            {"charge_revision": 99},
            {"document_hash": "wrong"},
            {"expires_at": timezone.now() - timedelta(seconds=1)},
        ]:
            original = {key: getattr(self.link, key) for key in changes}
            PaymentLink.objects.filter(pk=self.link.pk).update(**changes)
            self.assertEqual(self.client.get(self.detail).status_code, 302)
            self.assertEqual(self.client.get(self.path).status_code, 404)
            PaymentLink.objects.filter(pk=self.link.pk).update(**original)
        self.customer.active = False
        self.customer.save()
        self.assertEqual(self.client.get(self.detail).status_code, 302)

    def test_grant_expires_and_signed_session_cannot_be_tampered(self):
        self.unlock()
        with patch(
            "django.core.signing.time.time",
            return_value=timezone.now().timestamp() + 13 * 3600,
        ):
            self.assertEqual(self.client.get(self.detail).status_code, 302)
        session = self.client.session
        session[SESSION_KEY] = {str(self.charge.pk): "tampered"}
        session.save()
        self.assertEqual(self.client.get(self.detail).status_code, 302)

    def test_https_csrf_is_required_and_correct_document_still_works(self):
        browser = Browser(enforce_csrf_checks=True)
        page = browser.get(self.path, secure=True, HTTP_HOST="applanner.example")
        self.assertContains(page, '<meta name="referrer" content="same-origin">')
        self.assertEqual(
            browser.post(
                self.path,
                {"document": "52998224725"},
                secure=True,
                HTTP_HOST="applanner.example",
                HTTP_ORIGIN="https://applanner.example",
            ).status_code,
            403,
        )
        response = browser.post(
            self.path,
            {
                "document": "52998224725",
                "csrfmiddlewaretoken": browser.cookies["csrftoken"].value,
            },
            secure=True,
            HTTP_HOST="applanner.example",
            HTTP_ORIGIN="https://applanner.example",
        )
        self.assertEqual(response.status_code, 302)

    def test_budget_blocks_bruteforce_across_links_without_blocking_other_clients(self):
        for _ in range(5):
            self.client.post(self.path, {"document": "00000000000"})
        _, url = create_payment_link(self.charge, self.customer)
        self.assertEqual(
            self.client.post(
                urlsplit(url).path, {"document": "52998224725"}
            ).status_code,
            429,
        )
        self.assertNotIn(SESSION_KEY, self.client.session)
        other_user = get_user_model().objects.create_user(
            "second-link@example.test", None
        )
        other = Client.objects.create(
            user=other_user,
            name="Outro cliente",
            kind="cpf",
            document_hash=hashlib.sha256(b"11144477735").hexdigest(),
        )
        other_charge = Charge.objects.create(
            client=other,
            amount="1.00",
            description="Outro projeto",
            due_date=self.charge.due_date,
        )
        _, other_url = create_payment_link(other_charge, other)
        self.assertEqual(
            self.client.post(
                urlsplit(other_url).path, {"document": "11144477735"}
            ).status_code,
            302,
        )

    @patch("development.tasks._gateway")
    def test_reminder_sends_private_link_and_pdf_once(self, gateway):
        now = timezone.make_aware(
            datetime.combine(self.charge.due_date, time(12)),
            timezone.get_current_timezone(),
        )
        gateway.return_value = {
            "id": "dev-pdf-link-test",
            "to": self.customer.phone + "@s.whatsapp.net",
        }
        with patch("development.tasks.timezone.now", return_value=now):
            row = queue_reminder(self.charge.pk, self.charge.due_date)
            self.assertEqual(
                queue_reminder(self.charge.pk, self.charge.due_date).pk, row.pk
            )
            self.assertEqual(PaymentLink.objects.count(), 2)  # fixture + one notice
            payload = decrypt_json(row.payload_encrypted)
            self.assertIn("/desenvolvimento/cobranca/", payload["text"])
            self.assertNotIn("52998224725", payload["text"])
            deliver(row.pk)
            deliver(row.pk)
        self.assertEqual(gateway.call_count, 1)
        sent = gateway.call_args.args[2]
        self.assertIn("/desenvolvimento/cobranca/", sent["text"])
        self.assertEqual(sent["file"]["mime"], "application/pdf")
        self.assertEqual(base64.b64decode(sent["file"]["base64"]), b"%PDF-1.7\nDEMO")

    def test_cnpj_unlock(self):
        self.customer.kind = "cnpj"
        self.customer.document_hash = hashlib.sha256(b"11222333000181").hexdigest()
        self.customer.document_encrypted = encrypt_text("11222333000181")
        self.customer.save()
        _, url = create_payment_link(self.charge, self.customer)
        response = self.client.post(
            urlsplit(url).path, {"document": "11.222.333/0001-81"}
        )
        self.assertEqual(response.status_code, 302)

    @patch("development.payments.start_payment")
    def test_pix_and_card_are_scoped_and_use_registered_payer(self, start):
        self.unlock()
        PaymentGateway.objects.create(
            provider="mercadopago",
            environment="production",
            active=True,
            last_test_status="validated",
            public_key="APP_USR-public",
        )
        start.return_value.status = "pending"
        start.return_value.get_status_display.return_value = "Aguardando pagamento"
        response = self.client.post(reverse("development-pix", args=[self.charge.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(start.call_args.args[:2], (self.charge.pk, "pix"))
        page = self.client.get(reverse("development-card", args=[self.charge.pk]))
        self.assertContains(page, self.user.email)
        response = self.client.post(
            reverse("development-card", args=[self.charge.pk]),
            json.dumps(
                {
                    "card_token": "fake-token-123",
                    "payment_method_id": "visa",
                    "installments": 1,
                    "attempt_id": "12345678123456781234567812345678",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(start.call_args.args[:2], (self.charge.pk, "card"))
        self.assertEqual(start.call_args.kwargs["access_link_id"], self.link.pk)

    @patch("development.payments.platform_provider")
    def test_payment_rechecks_link_under_locks_before_requesting_money(self, provider):
        from .payments import start_payment

        PaymentGateway.objects.create(
            provider="mercadopago",
            environment="production",
            active=True,
            last_test_status="validated",
            public_key="APP_USR-public",
        )
        PaymentLink.objects.filter(pk=self.link.pk).update(charge_revision=99)
        with self.assertRaises(ValidationError):
            start_payment(
                self.charge.pk, "pix", uuid.uuid4(), access_link_id=self.link.pk
            )
        provider.assert_not_called()
        PaymentLink.objects.filter(pk=self.link.pk).update(charge_revision=1)

        def identity():
            PaymentLink.objects.filter(pk=self.link.pk).update(
                expires_at=timezone.now() - timedelta(seconds=1)
            )
            return {"id": 321}

        provider.return_value.test_connection.side_effect = identity
        payment = start_payment(
            self.charge.pk, "pix", uuid.uuid4(), access_link_id=self.link.pk
        )
        self.assertEqual(payment.status, "cancelled")
        provider.return_value._request.assert_not_called()
