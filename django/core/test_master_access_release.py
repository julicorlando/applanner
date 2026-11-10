import re
import smtplib
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import PasswordResetToken, User
from communications.models import Notification
from core.models import AuditLog
from tenants.models import Tenant


@override_settings(PUBLIC_BASE_URL="https://applanner.test")
class MasterAccessReleaseTests(TestCase):
    def setUp(self):
        self.master = User.objects.create_superuser(email="master-release@teste.local", password="SenhaBemForte123!")
        self.tenant = Tenant.objects.create(name="Clínica Sorriso", slug="clinica-release")
        self.other = Tenant.objects.create(name="Outra empresa", slug="outra-release")
        self.owner = User.objects.create_user(email="dona@sorriso.local", tenant=self.tenant, role="owner", first_name="Ana")
        self.owner.set_unusable_password()
        self.owner.save()
        self.staff = User.objects.create_user(email="recepcao@sorriso.local", tenant=self.tenant, role="user")
        self.foreign = User.objects.create_user(email="fora@outra.local", tenant=self.other, role="owner")

    def url(self, user, tenant=None):
        return reverse("master-access-release-user", args=[(tenant or self.tenant).pk, user.pk])

    def test_only_master_can_open_and_release(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("master-access-release")).status_code, 403)
        self.assertEqual(self.client.get(reverse("master-access-release-company", args=[self.tenant.pk])).status_code, 403)
        self.assertEqual(self.client.post(self.url(self.staff)).status_code, 403)
        self.assertEqual(len(mail.outbox), 0)

    def test_company_list_and_user_list(self):
        self.client.force_login(self.master)
        response = self.client.get(reverse("master-access-release"), {"q": "sorriso"})
        self.assertContains(response, "Clínica Sorriso")
        self.assertNotContains(response, "Outra empresa")
        response = self.client.get(reverse("master-access-release-company", args=[self.tenant.pk]))
        self.assertContains(response, "dona@sorriso.local")
        self.assertContains(response, "recepcao@sorriso.local")
        self.assertNotContains(response, "fora@outra.local")
        self.assertContains(response, "Liberar acesso")
        self.assertContains(self.client.get(reverse("master-home")), "Liberar acesso empresa")

    def test_release_sends_welcome_email_and_link_creates_password(self):
        self.client.force_login(self.master)
        response = self.client.post(self.url(self.owner), follow=True)
        self.assertContains(response, "E-mail de boas-vindas enviado para dona@sorriso.local")
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["dona@sorriso.local"])
        self.assertIn("Bem-vindo ao ApPlanner, Ana", message.subject)
        html = message.alternatives[0][0]
        self.assertIn("Clique aqui para gerar sua senha", html)
        self.assertIn("https://applanner.test/static/images/applanner-logo", html)
        self.assertIn("welcome-dashboard", html)
        self.assertIn("Clínica Sorriso", message.body)
        link = re.search(r"https://applanner\.test/account/password-reset/([^/\s]+)/", message.body)
        self.assertIsNotNone(link)
        notice = Notification.objects.get(template_key="access_release", destination="dona@sorriso.local")
        self.assertEqual(notice.status, Notification.Status.SENT)
        self.assertNotIn(link.group(1), str(notice.payload))
        self.assertTrue(AuditLog.objects.filter(action="MASTER_ACCESS_RELEASED", entity_id=self.owner.pk).exists())
        self.assertContains(response, "Enviado em")

        self.client.logout()
        page = self.client.get(link.group(0).replace("https://applanner.test", ""))
        self.assertContains(page, "Crie sua senha do ApPlanner")
        self.client.post(link.group(0).replace("https://applanner.test", ""),
                         {"password": "NovaSenhaForte123!", "password_confirmation": "NovaSenhaForte123!"})
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password("NovaSenhaForte123!"))
        self.assertIsNotNone(self.owner.email_verified_at)

    def test_resend_is_paused_and_invalidates_previous_link(self):
        self.client.force_login(self.master)
        self.client.post(self.url(self.staff))
        response = self.client.post(self.url(self.staff), follow=True)
        self.assertContains(response, "Aguarde um minuto")
        self.assertEqual(len(mail.outbox), 1)
        Notification.objects.filter(template_key="access_release").update(sent_at="2026-01-01T00:00:00Z")
        self.client.post(self.url(self.staff))
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(PasswordResetToken.objects.filter(user=self.staff, used_at__isnull=True).count(), 1)

    def test_user_from_another_company_or_inactive_is_refused(self):
        self.client.force_login(self.master)
        self.assertEqual(self.client.post(self.url(self.foreign)).status_code, 404)
        self.staff.is_active = False
        self.staff.save(update_fields=["is_active"])
        response = self.client.post(self.url(self.staff), follow=True)
        self.assertContains(response, "inativo ou sem e-mail")
        self.assertEqual(len(mail.outbox), 0)

    def test_smtp_failure_is_reported_and_token_discarded(self):
        self.client.force_login(self.master)
        with patch("django.core.mail.EmailMultiAlternatives.send",
                   side_effect=smtplib.SMTPAuthenticationError(535, b"server secret")):
            response = self.client.post(self.url(self.staff), follow=True)
        self.assertContains(response, "Não foi possível enviar o e-mail")
        self.assertContains(response, "Autenticação SMTP recusada")
        self.assertNotContains(response, "server secret")
        self.assertFalse(PasswordResetToken.objects.filter(user=self.staff).exists())
        notice = Notification.objects.get(template_key="access_release")
        self.assertEqual(notice.status, Notification.Status.FAILED)
