from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from tenants.models import Tenant
from .models import PaymentGateway


class PlatformGatewayMasterTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Conta de teste",slug="conta-teste")
        self.user=User.objects.create_user(email="owner@exemplo.com",password="SenhaDeTeste123!",tenant=self.tenant)
        self.master=User.objects.create_superuser(email="master@exemplo.com",password="SenhaDeTeste123!")
        self.url=reverse("master-platform-payment")

    def test_only_master_can_view_or_edit_platform_credentials(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code,403)
        self.assertEqual(self.client.post(self.url,{}).status_code,403)

    @patch("billing.payment_services.MercadoPagoProvider.test_connection",return_value={"id":123})
    def test_master_validates_and_activates_gateway_without_showing_secrets(self,test_connection):
        self.client.force_login(self.master)
        data={"environment":"sandbox","public_key":"TEST-public",
              "access_token":"TEST-123456789012345","webhook_secret":"segredo-do-webhook-123"}
        response=self.client.post(self.url,data,secure=True)
        self.assertRedirects(response,self.url)
        gateway=PaymentGateway.objects.get(environment="sandbox")
        self.assertTrue(gateway.active)
        self.assertEqual(gateway.last_test_status,PaymentGateway.TestStatus.VALIDATED)
        self.assertEqual(gateway.webhook_url,"https://testserver/webhooks/mercadopago/")
        self.assertNotIn(data["access_token"],gateway.access_token_encrypted)
        self.assertNotIn(data["webhook_secret"],gateway.webhook_secret_encrypted)
        self.assertNotContains(self.client.get(self.url),data["access_token"])
        test_connection.assert_called_once()

    @patch("billing.payment_services.MercadoPagoProvider.test_connection",return_value={"id":123})
    def test_switching_environment_deactivates_previous_gateway(self,_):
        self.client.force_login(self.master)
        common={"public_key":"public","webhook_secret":"segredo-do-webhook-123"}
        self.client.post(self.url,{**common,"environment":"sandbox","access_token":"TEST-123456789012345"},secure=True)
        self.client.post(self.url,{**common,"environment":"production","access_token":"APP_USR-123456789012345"},secure=True)
        self.assertFalse(PaymentGateway.objects.get(environment="sandbox").active)
        self.assertTrue(PaymentGateway.objects.get(environment="production").active)

    @patch("billing.payment_services.MercadoPagoProvider.test_connection",side_effect=RuntimeError("provider failed"))
    def test_failed_validation_does_not_save_credentials(self,_):
        self.client.force_login(self.master)
        response=self.client.post(self.url,{"environment":"sandbox","access_token":"TEST-123456789012345",
            "webhook_secret":"segredo-do-webhook-123"},secure=True)
        self.assertEqual(response.status_code,200)
        self.assertFalse(PaymentGateway.objects.exists())
        self.assertNotContains(response,"provider failed")
