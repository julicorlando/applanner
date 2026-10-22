import base64
import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as Browser, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from core.crypto import encrypt_text, decrypt_json
from core.models import AuditLog
from finance.models import PlatformBankAccount
from .forms import ClientForm, ChargeForm, validate_document, validate_template
from .models import Client, Charge, Delivery, Invitation, DEFAULT_MESSAGE
from .services import invite, queue_reminder, reminder_stage, save_charge, settle
from .tasks import deliver, process_development_billing


@override_settings(
    PUBLIC_BASE_URL="https://applanner.example",
    SECURE_SSL_REDIRECT=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    TIME_ZONE="America/Recife",
)
class DevelopmentTests(TestCase):
    def setUp(self):
        self.master = get_user_model().objects.create_superuser(
            "master@example.com", "test-master-password"
        )
        self.owner = get_user_model().objects.create_user(
            "dev@example.com", None, role="development-client"
        )
        self.customer = Client.objects.create(
            user=self.owner,
            kind="cpf",
            name="Cliente demonstração",
            document_encrypted=encrypt_text("52998224725"),
            document_hash=hashlib.sha256(b"52998224725").hexdigest(),
            phone="5581999990001",
        )
        self.bank = PlatformBankAccount.objects.create(
            bank_name="Banco demonstração",
            bank_code="000",
            account_type="checking",
            agency_encrypted=encrypt_text("1234"),
            account_encrypted=encrypt_text("56789"),
            holder_document_encrypted=encrypt_text("52998224725"),
            holder_name="Desenvolvimento",
            person_type="individual",
            pix_key_encrypted=encrypt_text("financeiro@example.com"),
            is_default=True,
        )
        self.charge = Charge.objects.create(
            client=self.customer,
            description="Desenvolvimento do projeto",
            amount="250.00",
            due_date=date(2026, 11, 10),
            bank=self.bank,
            boleto_encrypted=encrypt_text(base64.b64encode(b"%PDF-1.7\nDEMO").decode()),
        )
        self.now = datetime(2026, 11, 10, 13, tzinfo=dt_timezone.utc)

    def request(self):
        from django.test import RequestFactory

        request = RequestFactory().post("/")
        request.user = self.master
        return request

    def client_data(self, **changes):
        result = {
            "kind": "cnpj",
            "document": "11.222.333/0001-81",
            "name": "Empresa demonstração LTDA",
            "company_name": "Projeto exemplo",
            "email": "empresa@example.com",
            "phone": "81999990002",
            "website": "",
            "active": "on",
            "reminders_enabled": "on",
            "message_template": DEFAULT_MESSAGE,
        }
        result.update(changes)
        return result

    def test_document_and_template_validation(self):
        self.assertEqual(validate_document("529.982.247-25", "cpf"), "52998224725")
        self.assertEqual(
            validate_document("11.222.333/0001-81", "cnpj"), "11222333000181"
        )
        for invalid, kind in [
            ("11111111111", "cpf"),
            ("52998224724", "cpf"),
            ("11222333000180", "cnpj"),
        ]:
            with self.assertRaises(ValidationError):
                validate_document(invalid, kind)
        for text in [
            "sem link",
            "{nome.__class__} {link}",
            "{valor:1000000} {link}",
            "{link!r}",
        ]:
            with self.assertRaises(ValidationError):
                validate_template(text)

    def test_master_creates_account_and_queues_two_private_invitations(self):
        self.client.force_login(self.master)
        response = self.client.post(
            reverse("development-client-create"), self.client_data()
        )
        self.assertEqual(response.status_code, 302)
        row = Client.objects.get(user__email="empresa@example.com")
        self.assertIsNone(row.user.tenant_id)
        self.assertEqual(row.user.role, "development-client")
        self.assertFalse(row.user.has_usable_password())
        self.assertNotIn("11222333000181", row.document_encrypted)
        self.assertEqual(row.phone, "5581999990002")
        self.assertEqual(row.deliveries.count(), 2)
        self.assertNotIn("ativar/", row.deliveries.first().payload_encrypted)
        self.assertTrue(
            AuditLog.objects.filter(
                action="development.client-created", entity_id=row.pk
            ).exists()
        )
        # A repeated submit never creates a second account or repurposes an old one.
        self.assertEqual(
            self.client.post(
                reverse("development-client-create"), self.client_data()
            ).status_code,
            200,
        )
        self.assertEqual(Client.objects.count(), 2)

    def test_existing_platform_email_is_never_converted(self):
        form = ClientForm(self.client_data(email=self.master.email))
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)
        self.master.refresh_from_db()
        self.assertTrue(self.master.is_superuser)

    def test_https_required_for_invitation_and_transaction_rolls_back(self):
        self.client.force_login(self.master)
        with override_settings(PUBLIC_BASE_URL=""):
            response = self.client.post(
                reverse("development-client-create"), self.client_data()
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            get_user_model().objects.filter(email="empresa@example.com").exists()
        )

    def test_activation_uses_password_validation_and_is_single_use(self):
        invitation = invite(self.customer)
        text = decrypt_json(self.customer.deliveries.first().payload_encrypted)["text"]
        url = text.split("https://applanner.example", 1)[1].split("\n", 1)[0]
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertContains(
            self.client.post(url, {"password": "123", "confirmation": "123"}), "curta"
        )
        response = self.client.post(
            url,
            {
                "password": "Nova-senha-forte!2026",
                "confirmation": "Nova-senha-forte!2026",
            },
        )
        self.assertRedirects(
            response, reverse("accounts:login"), fetch_redirect_response=False
        )
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password("Nova-senha-forte!2026"))
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.used_at)
        self.assertEqual(self.client.get(url).status_code, 400)
        self.assertFalse(self.customer.deliveries.exclude(status="cancelled").exists())

    def test_activation_expiration_and_reissue_invalidate_previous_token(self):
        old = invite(self.customer)
        old.created_at = timezone.now() - timedelta(minutes=2)
        old.save(update_fields=["created_at"])
        new = invite(self.customer)
        old.refresh_from_db()
        self.assertIsNotNone(old.used_at)
        self.assertNotEqual(old.token_hash, new.token_hash)
        Invitation.objects.filter(pk=new.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        text = decrypt_json(
            Delivery.objects.filter(invitation=new).first().payload_encrypted
        )["text"]
        url = text.split("https://applanner.example", 1)[1].split("\n", 1)[0]
        self.assertEqual(self.client.get(url).status_code, 400)

    def test_customer_login_redirect_and_access_boundaries(self):
        self.owner.set_password("Customer-strong-password!9")
        self.owner.save(update_fields=["password"])
        response = self.client.post(
            reverse("accounts:login"),
            {"email": self.owner.email, "password": "Customer-strong-password!9"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            self.client.get("/"),
            reverse("development-payments"),
            fetch_redirect_response=False,
        )
        for url in [
            "/master/",
            "/master/clientes-desenvolvimento/",
            "/app/agenda/",
            "/app/calendario/",
            "/api/scheduling/",
            "/account/documentacao-api/",
        ]:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertContains(
            self.client.get(reverse("development-payments")),
            "Desenvolvimento do projeto",
        )
        self.assertEqual(
            self.client.post(reverse("development-payments"), {}).status_code, 405
        )

    def test_customer_cannot_read_other_boleto_or_bank_data(self):
        second = get_user_model().objects.create_user(
            "second@example.com", None, role="development-client"
        )
        Client.objects.create(
            user=second,
            kind="cpf",
            document_encrypted=encrypt_text("111"),
            document_hash="other",
            name="Outro",
            phone="5581999990003",
        )
        self.client.force_login(second)
        for name in ["development-charge", "development-boleto"]:
            self.assertEqual(
                self.client.get(reverse(name, args=[self.charge.pk])).status_code, 404
            )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("development-charge", args=[self.charge.pk]))
        self.assertContains(response, "financeiro@example.com")
        response = self.client.get(reverse("development-boleto", args=[self.charge.pk]))
        self.assertEqual(response.content, b"%PDF-1.7\nDEMO")
        self.assertIn("private", response.headers["Cache-Control"])
        self.assertIn("attachment", response.headers["Content-Disposition"])

    def test_tenant_and_platform_operator_cannot_access_module(self):
        regular = get_user_model().objects.create_user(
            "regular@example.com", "strong-password"
        )
        self.client.force_login(regular)
        for route in [
            "development-clients",
            "development-client-create",
            "development-payments",
        ]:
            self.assertIn(self.client.get(reverse(route)).status_code, [403, 404])
        self.assertEqual(
            self.client.post(
                reverse("development-client-invite", args=[self.customer.pk])
            ).status_code,
            403,
        )

    def test_csrf_protects_master_mutations(self):
        browser = Browser(enforce_csrf_checks=True)
        browser.force_login(self.master)
        self.assertEqual(
            browser.post(
                reverse("development-client-invite", args=[self.customer.pk])
            ).status_code,
            403,
        )

    def test_inactive_customer_cannot_login_to_payments(self):
        self.customer.active = False
        self.customer.save(update_fields=["active"])
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.get(reverse("development-payments")).status_code, 403
        )

    def test_reminder_calendar_exact_days_and_idempotency(self):
        due = self.charge.due_date
        expected = {-10, -5, 0, 2, 4, 6, 8, 10, 12}
        for offset in range(-11, 14):
            self.assertEqual(
                bool(reminder_stage(due, due + timedelta(days=offset))),
                offset in expected,
            )
        one = queue_reminder(self.charge.pk, due)
        two = queue_reminder(self.charge.pk, due)
        self.assertEqual(one.pk, two.pk)
        self.assertEqual(Delivery.objects.filter(charge=self.charge).count(), 1)

    @patch("development.tasks._gateway")
    def test_whatsapp_attaches_pdf_and_duplicate_execution_does_not_resend(
        self, gateway
    ):
        gateway.return_value = {
            "id": "dev-test-send-1",
            "to": self.customer.phone + "@s.whatsapp.net",
        }
        with patch("development.tasks.timezone.now", return_value=self.now):
            row = queue_reminder(self.charge.pk, self.charge.due_date)
            deliver(row.pk)
            deliver(row.pk)
        self.assertEqual(gateway.call_count, 1)
        payload = gateway.call_args.args[2]
        self.assertEqual(payload["idempotencyKey"], row.key)
        self.assertEqual(base64.b64decode(payload["file"]["base64"]), b"%PDF-1.7\nDEMO")
        row.refresh_from_db()
        self.assertEqual(row.status, "sent")
        self.assertEqual(row.payload_encrypted, "")

    @patch("development.tasks._gateway")
    def test_settlement_stops_pending_reminders_and_is_audited(self, gateway):
        row = queue_reminder(self.charge.pk, self.charge.due_date)
        settle(self.charge.pk, "paid", "Comprovante TESTE", self.request())
        with patch("development.tasks.timezone.now", return_value=self.now):
            deliver(row.pk)
        gateway.assert_not_called()
        self.assertIsNone(
            queue_reminder(self.charge.pk, self.charge.due_date + timedelta(days=2))
        )
        self.assertTrue(
            AuditLog.objects.filter(action="development.charge-paid").exists()
        )
        with self.assertRaises(ValidationError):
            settle(self.charge.pk, "paid", "duplicado", self.request())

    @patch(
        "development.tasks._gateway",
        side_effect=ValueError("do not expose private provider detail"),
    )
    def test_gateway_failure_is_recorded_and_retry_reuses_idempotency_key(
        self, gateway
    ):
        with patch("development.tasks.timezone.now", return_value=self.now):
            row = queue_reminder(self.charge.pk, self.charge.due_date)
            deliver(row.pk)
        row.refresh_from_db()
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.error_code, "check_master_whatsapp")
        key = gateway.call_args.args[2]["idempotencyKey"]
        gateway.side_effect = None
        gateway.return_value = {
            "id": "dev-retry",
            "to": self.customer.phone + "@s.whatsapp.net",
        }
        with patch(
            "development.tasks.timezone.now",
            return_value=self.now + timedelta(minutes=6),
        ):
            deliver(row.pk)
        self.assertEqual(gateway.call_args.args[2]["idempotencyKey"], key)
        row.refresh_from_db()
        self.assertEqual(row.status, "sent")

    @patch("development.tasks._gateway")
    def test_stale_day_and_disabled_reminders_never_send(self, gateway):
        row = queue_reminder(self.charge.pk, self.charge.due_date)
        with patch(
            "development.tasks.timezone.now", return_value=self.now + timedelta(days=1)
        ):
            deliver(row.pk)
        row.refresh_from_db()
        self.assertEqual(row.status, "cancelled")
        gateway.assert_not_called()
        self.customer.reminders_enabled = False
        self.customer.save(update_fields=["reminders_enabled"])
        self.assertIsNone(
            queue_reminder(self.charge.pk, self.charge.due_date + timedelta(days=2))
        )

    def test_email_invitation_uses_existing_backend(self):
        invite(self.customer)
        row = self.customer.deliveries.get(channel="email")
        deliver(row.pk)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.owner.email])
        self.assertIn("/desenvolvimento/ativar/", mail.outbox[0].body)

    @patch(
        "development.tasks.send_mail", side_effect=TimeoutError("private SMTP error")
    )
    def test_smtp_uncertainty_is_not_automatically_resent(self, sender):
        invite(self.customer)
        row = self.customer.deliveries.get(channel="email")
        deliver(row.pk)
        deliver(row.pk)
        row.refresh_from_db()
        self.assertEqual(row.status, "uncertain")
        self.assertEqual(sender.call_count, 1)

    def test_charge_form_limits_and_creation_idempotency(self):
        data = {
            "description": "Projeto",
            "amount": "100.00",
            "due_date": "2026-11-10",
            "bank": self.bank.pk,
            "creation_key": str(uuid.uuid4()),
        }
        form = ChargeForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        row = save_charge(form, self.customer, self.request())
        other = ChargeForm(data)
        self.assertTrue(other.is_valid(), other.errors)
        self.assertEqual(save_charge(other, self.customer, self.request()).pk, row.pk)
        for changes in [
            {"amount": "-1"},
            {"boleto_url": "http://example.com/boleto"},
            {"barcode": "123"},
        ]:
            self.assertFalse(ChargeForm(data | changes).is_valid())
        file = SimpleUploadedFile(
            "boleto.pdf", b"not pdf", content_type="application/pdf"
        )
        self.assertFalse(ChargeForm(data, {"boleto_pdf": file}).is_valid())

    @patch("development.tasks._gateway")
    def test_edited_due_date_cancels_old_notice(self, gateway):
        row = queue_reminder(self.charge.pk, self.charge.due_date)
        data = {
            "description": "Alterada",
            "amount": "100.00",
            "due_date": "2026-12-10",
            "bank": self.bank.pk,
            "creation_key": str(self.charge.creation_key),
        }
        form = ChargeForm(data, instance=self.charge)
        self.assertTrue(form.is_valid(), form.errors)
        save_charge(form, self.customer, self.request())
        with patch("development.tasks.timezone.now", return_value=self.now):
            deliver(row.pk)
        gateway.assert_not_called()
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.revision, 2)

    @patch("development.tasks._gateway")
    def test_scheduler_does_not_send_billing_at_night(self, gateway):
        with patch(
            "development.tasks.timezone.now", return_value=self.now.replace(hour=2)
        ):
            process_development_billing()
        gateway.assert_not_called()
        self.assertFalse(Delivery.objects.filter(charge=self.charge).exists())

    def test_new_pages_render_and_other_pages_preserved(self):
        from billing.models import Plan, Module

        plan = Plan.objects.create(name="Plano personalizado", slug="preservado-dev", monthly_price="147.33")
        module = Module.objects.create(name="Módulo personalizado", slug="preservado-dev", addon_monthly_price="23.45")
        self.client.force_login(self.master)
        for route, args in [
            ("development-clients", []),
            ("development-client", [self.customer.pk]),
            ("development-client-edit", [self.customer.pk]),
            ("development-charge-create", [self.customer.pk]),
            ("development-settlement", [self.charge.pk, "paid"]),
        ]:
            self.assertEqual(
                self.client.get(reverse(route, args=args)).status_code, 200, route
            )
        # Existing catalogue entries keep their configured prices and names.
        plan.refresh_from_db()
        module.refresh_from_db()
        self.assertEqual(str(plan.monthly_price), "147.33")
        self.assertEqual(str(module.addon_monthly_price), "23.45")
        self.assertEqual(plan.name, "Plano personalizado")
        self.assertEqual(module.name, "Módulo personalizado")
        self.assertContains(
            self.client.get(reverse("master-home")), "Clientes de desenvolvimento"
        )

    def test_cancelled_boleto_is_not_downloadable(self):
        settle(self.charge.pk, "cancelled", "Projeto cancelado", self.request())
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("development-boleto", args=[self.charge.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("development-charge", args=[self.charge.pk])), "financeiro@example.com")

    def test_inactive_bank_is_not_exposed_in_portal(self):
        self.bank.status = "inactive"
        self.bank.save(update_fields=["status"])
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(reverse("development-charge", args=[self.charge.pk])), "financeiro@example.com")

    def test_all_mutations_require_post_and_support_impersonation_is_denied(self):
        self.client.force_login(self.master)
        self.assertEqual(self.client.get(reverse("development-client-invite", args=[self.customer.pk])).status_code, 405)
        from .views import client_detail
        request = self.request()
        request.method = "GET"
        request.support_actor = self.master
        from django.core.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):
            client_detail(request, self.customer.pk)
