from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from accounts.models import User
from tenants.models import Tenant, TenantOnboarding
from operations.models import PlatformSMTPSettings
from core.crypto import decrypt_text


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
