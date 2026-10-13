from unittest.mock import patch

from django.test import TestCase,override_settings
from django.urls import reverse

from .models import EmailVerificationToken,User


class EmailVerificationDeliveryTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user(email="owner@example.com",password="SenhaDeTeste123!")
        self.client.force_login(self.user)
        self.url=reverse("accounts:send-verification")

    @override_settings(EMAIL_HOST="",EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend")
    @patch("accounts.views.send_mail")
    def test_missing_smtp_configuration_does_not_create_token(self,send):
        self.client.post(self.url)
        send.assert_not_called()
        self.assertFalse(EmailVerificationToken.objects.exists())

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    @patch("accounts.views.send_mail",return_value=0)
    def test_unconfirmed_delivery_does_not_claim_success(self,send):
        self.client.post(self.url)
        send.assert_called_once()
        self.assertFalse(EmailVerificationToken.objects.exists())

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_successful_delivery_creates_token(self):
        self.client.post(self.url)
        self.assertEqual(EmailVerificationToken.objects.count(),1)
