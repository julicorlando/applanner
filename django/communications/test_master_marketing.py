import secrets
from unittest.mock import patch

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase,override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from tenants.models import Tenant
from .models import MarketingCampaign,MarketingDelivery,MarketingLead
from .tasks import send_marketing_delivery


@override_settings(PUBLIC_BASE_URL="https://app.example.test")
class MasterMarketingTests(TestCase):
    def setUp(self):
        self.master=User.objects.create_superuser(email="master-marketing@test.local",password="StrongPassword123!")
        tenant=Tenant.objects.create(name="Empresa",slug="marketing-tenant")
        self.owner=User.objects.create_user(email="marketing-owner@test.local",password="StrongPassword123!",tenant=tenant,role="owner")
        self.active=MarketingLead.objects.create(name="Autorizado",email="yes@test.local",consent_at=timezone.now(),unsubscribe_token=secrets.token_hex(32))
        self.no_consent=MarketingLead.objects.create(name="Sem aceite",email="no@test.local",unsubscribe_token=secrets.token_hex(32))
        self.opted_out=MarketingLead.objects.create(name="Saiu",email="out@test.local",status="unsubscribed",consent_at=timezone.now(),unsubscribe_token=secrets.token_hex(32))

    def test_master_only_campaign_consent_and_unsubscribe(self):
        url=reverse("master-marketing-create")
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(url,{}).status_code,403)
        self.client.force_login(self.master)
        response=self.client.post(url,{"subject":"Novidades","body":"Novos horários","confirm":"on"})
        self.assertRedirects(response,reverse("master-marketing"))
        campaign=MarketingCampaign.objects.get()
        self.assertEqual(campaign.total_count,1)
        self.assertEqual(list(campaign.deliveries.values_list("lead_id",flat=True)),[self.active.pk])
        with override_settings(PUBLIC_BASE_URL="https://app.example.test"):
            send_marketing_delivery(campaign.deliveries.get().pk)
        self.assertEqual(len(mail.outbox),1)
        self.assertIn(self.active.unsubscribe_token,mail.outbox[0].body)
        unsubscribe=reverse("marketing-unsubscribe",args=[self.active.unsubscribe_token])
        self.assertEqual(self.client.get(unsubscribe).status_code,200)
        self.assertEqual(self.active.status,MarketingLead.Status.ACTIVE)
        self.client.post(unsubscribe)
        self.active.refresh_from_db()
        self.assertEqual(self.active.status,MarketingLead.Status.UNSUBSCRIBED)

    def test_import_does_not_reactivate_opted_out_and_requires_confirmation(self):
        self.client.force_login(self.master)
        url=reverse("master-marketing-import")
        content=b"nome,email\nNova,nova@test.local\nSaiu,out@test.local\n"
        self.assertEqual(self.client.post(url,{"file":SimpleUploadedFile("x.csv",content)}).status_code,200)
        self.assertFalse(MarketingLead.objects.filter(email="nova@test.local").exists())
        response=self.client.post(url,{"file":SimpleUploadedFile("x.csv",content),"confirm":"on"})
        self.assertRedirects(response,reverse("master-marketing"))
        self.assertEqual(MarketingLead.objects.get(email="out@test.local").status,MarketingLead.Status.UNSUBSCRIBED)
        self.assertIsNotNone(MarketingLead.objects.get(email="nova@test.local").consent_at)

    def test_cancellation_prevents_queued_delivery(self):
        self.client.force_login(self.master)
        self.client.post(reverse("master-marketing-create"),{"subject":"Oferta","body":"Texto","confirm":"on"})
        campaign=MarketingCampaign.objects.get()
        self.client.post(reverse("master-marketing-cancel",args=[campaign.pk]))
        send_marketing_delivery(campaign.deliveries.get().pk)
        self.assertEqual(len(mail.outbox),0)
        self.assertEqual(MarketingDelivery.objects.get().status,MarketingDelivery.Status.SKIPPED)

    @override_settings(PUBLIC_BASE_URL="")
    def test_campaign_requires_https_public_url_for_opt_out(self):
        self.client.force_login(self.master)
        response=self.client.post(reverse("master-marketing-create"),{"subject":"Oferta","body":"Texto","confirm":"on"})
        self.assertEqual(response.status_code,200)
        self.assertFalse(MarketingCampaign.objects.exists())
        self.assertContains(response,"PUBLIC_BASE_URL")
