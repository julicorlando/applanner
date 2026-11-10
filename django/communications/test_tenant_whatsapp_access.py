from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.entitlements import module_enabled
from billing.models import Module,Plan,Subscription,TenantModule
from communications.models import TenantWhatsAppConnection
from tenants.models import Tenant


class TenantWhatsAppAccessTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Barbearia QR",slug="barbearia-qr",status=Tenant.Status.ACTIVE)
        self.owner=User.objects.create_user(email="owner-qr@example.test",password="StrongPassword123!",
            role="owner",tenant=self.tenant)
        self.master=User.objects.create_superuser(email="master-qr@example.test",password="StrongPassword123!")
        self.plan=Plan.objects.create(name="Plano sem WhatsApp",slug="sem-whatsapp",active=True)
        Subscription.objects.create(tenant=self.tenant,plan=self.plan,status=Subscription.Status.ACTIVE,
            started_at=timezone.now())
        self.url=reverse("tenant-whatsapp-settings")

    def test_master_selects_tenant_and_enables_module_explicitly(self):
        Module.objects.create(slug="whatsapp",name="WhatsApp",active=False)
        call_command("seed_modules",verbosity=0)
        self.assertTrue(Module.objects.get(slug="whatsapp").active)
        self.client.force_login(self.master)
        self.assertEqual(self.client.get(self.url).status_code,302)
        session=self.client.session
        session["portal_tenant_id"]=self.tenant.pk
        session.save()
        self.assertContains(self.client.get(self.url),"Liberar WhatsApp para")
        self.assertEqual(self.client.post(self.url,{"action":"grant"}).status_code,302)
        self.assertTrue(TenantModule.objects.get(tenant=self.tenant,module__slug="whatsapp").enabled)
        self.assertTrue(module_enabled(self.tenant,"whatsapp"))
        with patch("communications.tenant_whatsapp.gateway",return_value={"state":"connecting"}) as gateway:
            self.assertEqual(self.client.post(self.url,{"action":"connect"}).status_code,302)
            gateway.assert_called_once_with(self.tenant,"POST","connect")
        self.assertTrue(TenantWhatsAppConnection.objects.get(tenant=self.tenant).enabled)
        with patch("communications.tenant_whatsapp.gateway",return_value={"state":"qr","qr":"data:image/png;base64,abc"}):
            self.assertContains(self.client.get(self.url),"escaneie")

    def test_owner_sees_reason_instead_of_403_and_cannot_connect_without_entitlement(self):
        Module.objects.create(slug="whatsapp",name="WhatsApp",active=True)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(self.url),"não está liberado no plano")
        with patch("communications.tenant_whatsapp.gateway") as gateway:
            self.assertEqual(self.client.post(self.url,{"action":"connect"}).status_code,302)
            gateway.assert_not_called()
        self.assertFalse(TenantWhatsAppConnection.objects.get(tenant=self.tenant).enabled)
        self.assertEqual(self.client.post(self.url,{"action":"grant"}).status_code,302)
        self.assertFalse(TenantModule.objects.exists())
        TenantModule.objects.create(tenant=self.tenant,module=Module.objects.get(slug="whatsapp"),enabled=True)
        with patch("communications.tenant_whatsapp.gateway",return_value={"state":"qr","qr":"data:image/png;base64,abc"}):
            self.assertEqual(self.client.post(self.url,{"action":"connect"}).status_code,302)
            self.assertContains(self.client.get(self.url),"escaneie")
