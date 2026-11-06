from unittest.mock import patch
import smtplib
import ssl
from django.test import TestCase,override_settings
from django.urls import reverse
from accounts.models import User
from tenants.models import Tenant, TenantOnboarding
from operations.models import PlatformSMTPSettings
from core.crypto import decrypt_text
from core.master_email import smtp_failure_reason


class MasterEmailTests(TestCase):
    def setUp(self):
        self.master=User.objects.create_superuser(email='master-smtp@teste.local',password='SenhaBemForte123!')
        self.tenant=Tenant.objects.create(name='Empresa',slug='email-waiver')
        self.owner=User.objects.create_user(email='owner-waiver@teste.local',password='SenhaBemForte123!',tenant=self.tenant,role='owner')

    def test_smtp_master_only_and_password_encrypted(self):
        url=reverse('master-smtp-settings')
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code,403)
        self.client.force_login(self.master)
        response=self.client.post(url,{'host':'smtp.test.local','port':'587','username':'smtp-user',
            'password':'senha-secreta','from_email':'app@test.local','use_tls':'on','enabled':'on'})
        self.assertEqual(response.status_code,302,response.content)
        config=PlatformSMTPSettings.objects.get(pk=1)
        self.assertNotIn('senha-secreta',config.password_encrypted)
        self.assertEqual(decrypt_text(config.password_encrypted),'senha-secreta')
        self.assertNotContains(self.client.get(url),'senha-secreta')

    def test_waiver_does_not_mark_email_verified(self):
        onboarding=TenantOnboarding.objects.create(tenant=self.tenant,required=True)
        url=reverse('master-onboarding-waive-email',args=[onboarding.pk])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(url,{'action':'grant'}).status_code,403)
        self.client.force_login(self.master)
        self.assertEqual(self.client.post(url,{'action':'grant'}).status_code,302)
        onboarding.refresh_from_db();self.owner.refresh_from_db()
        self.assertIsNotNone(onboarding.email_verification_waived_at)
        self.assertIsNone(self.owner.email_verified_at)

    @override_settings(EMAIL_BACKEND='applanner.email_backend.PlatformEmailBackend')
    def test_smtp_test_reports_authentication_failure_without_server_response(self):
        PlatformSMTPSettings.objects.create(pk=1,host='mail.applanner.com.br',port=465,
            username='naoresponda@applanner.com.br',password_encrypted='encrypted',
            from_email='naoresponda@applanner.com.br',use_tls=False,use_ssl=True,enabled=True)
        self.client.force_login(self.master)
        with patch('core.master_email.send_mail',side_effect=smtplib.SMTPAuthenticationError(535,b'secret server response')):
            response=self.client.post(reverse('master-smtp-settings'),{'action':'test'},follow=True)
        self.assertContains(response,'Autenticação SMTP recusada')
        self.assertNotContains(response,'secret server response')

    def test_saved_ssl_settings_are_restored_in_form(self):
        PlatformSMTPSettings.objects.create(pk=1,host='mail.applanner.com.br',port=465,
            username='naoresponda@applanner.com.br',from_email='naoresponda@applanner.com.br',
            use_tls=False,use_ssl=True,enabled=True)
        self.client.force_login(self.master)
        response=self.client.get(reverse('master-smtp-settings'))
        self.assertEqual(response.context['form']['port'].value(),465)
        self.assertEqual(response.context['form']['host'].value(),'mail.applanner.com.br')
        self.assertTrue(response.context['form']['use_ssl'].value())
        self.assertFalse(response.context['form']['use_tls'].value())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_smtp_test_rejects_backend_that_ignores_platform_settings(self):
        PlatformSMTPSettings.objects.create(pk=1,host='mail.applanner.com.br',
            from_email='naoresponda@applanner.com.br',enabled=True)
        self.client.force_login(self.master)
        with patch('core.master_email.send_mail') as send:
            response=self.client.post(reverse('master-smtp-settings'),{'action':'test'},follow=True)
        send.assert_not_called()
        self.assertContains(response,'backend de e-mail do Coolify não usa a configuração SMTP')

    def test_smtp_failure_diagnoses_ssl_and_sender_rejection(self):
        self.assertIn('SSL/TLS',smtp_failure_reason(ssl.SSLError('private detail')))
        self.assertIn('Remetente',smtp_failure_reason(smtplib.SMTPSenderRefused(553,b'private detail','sender@example.test')))
