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
        self.assertEqual(gateway.webhook_url,"https://testserver/webhooks/pagamentos/")
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

    def test_setup_errors_are_actionable_and_never_echo_provider_secrets(self):
        from requests.exceptions import Timeout, ConnectionError
        from .mercadopago import MercadoPagoError
        self.client.force_login(self.master)
        data={"environment":"production","public_key":"APP_USR-public",
              "access_token":"APP_USR-private-test-token","webhook_secret":"private-webhook-secret"}
        cases=[(MercadoPagoError(data['access_token'],http_status=401),'HTTP 401'),
               (MercadoPagoError(data['webhook_secret'],http_status=403),'HTTP 403'),
               (Timeout(data['access_token']),'demorou para responder'),
               (ConnectionError(data['access_token']),'saída HTTPS')]
        for error,message in cases:
            with self.subTest(message=message), patch('billing.payment_services.MercadoPagoProvider.test_connection',side_effect=error):
                response=self.client.post(self.url,data,secure=True)
                self.assertContains(response,message)
                self.assertNotContains(response,data['access_token'])
                self.assertNotContains(response,data['webhook_secret'])
                self.assertFalse(PaymentGateway.objects.exists())

    @patch('billing.payment_services.MercadoPagoProvider.test_connection',return_value={'id':123})
    def test_invalid_encryption_key_does_not_save_or_activate_gateway(self,_):
        self.client.force_login(self.master)
        with self.settings(FIELD_ENCRYPTION_KEY='invalid-key'):
            response=self.client.post(self.url,{'environment':'production','access_token':'APP_USR-private-test-token',
                'webhook_secret':'private-webhook-secret'},secure=True)
        self.assertContains(response,'DJANGO_FIELD_ENCRYPTION_KEY')
        self.assertFalse(PaymentGateway.objects.exists())
