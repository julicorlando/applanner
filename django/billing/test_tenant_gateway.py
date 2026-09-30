from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from tenants.models import Tenant
from scheduling.models import TenantScheduleSettings
from .models import TenantPaymentConnection


class TenantGatewayTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Empresa A",slug="empresa-a")
        self.other=Tenant.objects.create(name="Empresa B",slug="empresa-b")
        self.owner=User.objects.create_user(email="owner-a@test.local",password="StrongPassword123!",tenant=self.tenant,role="owner")
        self.manager=User.objects.create_user(email="manager-a@test.local",password="StrongPassword123!",tenant=self.tenant,role="manager")
        self.url=reverse("tenant-payment-gateway")
        self.data={"environment":"sandbox","public_key":"TEST-public",
                   "access_token":"TEST-123456789012345","webhook_secret":"segredo-do-webhook-123"}

    @patch("billing.payment_services.MercadoPagoProvider.test_connection",return_value={"id":123})
    def test_owner_connects_only_own_tenant_and_secrets_are_masked(self,test_connection):
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(self.url).status_code,403)
        self.client.force_login(self.owner)
        response=self.client.post(self.url,self.data,secure=True)
        self.assertRedirects(response,self.url)
        connection=TenantPaymentConnection.objects.get()
        self.assertEqual(connection.tenant,self.tenant)
        self.assertNotIn(self.data["access_token"],connection.credentials_encrypted)
        response=self.client.get(self.url,secure=True)
        self.assertContains(response,"https://testserver/webhooks/tenant/mercadopago/empresa-a/")
        self.assertNotContains(response,self.data["webhook_secret"])
        self.assertFalse(TenantPaymentConnection.objects.filter(tenant=self.other).exists())
        test_connection.assert_called_once()

    @patch("billing.payment_services.MercadoPagoProvider.test_connection",side_effect=RuntimeError("secret provider failure"))
    def test_invalid_provider_does_not_save_credentials(self,_):
        self.client.force_login(self.owner)
        response=self.client.post(self.url,self.data)
        self.assertEqual(response.status_code,200)
        self.assertFalse(TenantPaymentConnection.objects.exists())
        self.assertNotContains(response,"secret provider failure")

    @patch("billing.payment_services.MercadoPagoProvider.test_connection",return_value={"id":123})
    def test_owner_explicitly_enables_booking_pix_after_connecting(self,_):
        self.client.force_login(self.owner)
        self.client.post(self.url,{"action":"booking_payments","enabled":"on"})
        self.assertFalse(TenantScheduleSettings.objects.get(tenant=self.tenant).online_booking_payments_enabled)
        self.client.post(self.url,self.data,secure=True)
        self.client.post(self.url,{"action":"booking_payments","enabled":"on"})
        self.assertTrue(TenantScheduleSettings.objects.get(tenant=self.tenant).online_booking_payments_enabled)
        self.client.post(self.url,{"action":"booking_payments"})
        self.assertFalse(TenantScheduleSettings.objects.get(tenant=self.tenant).online_booking_payments_enabled)
