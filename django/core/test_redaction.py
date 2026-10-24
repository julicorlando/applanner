from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from billing.mercadopago import MercadoPagoError, MercadoPagoProvider
from communications.whatsapp import WhatsAppProviderError, send_text
from core.redaction import redact_sensitive_text


@override_settings(EMAIL_HOST_PASSWORD="synthetic-smtp-password")
class RedactionTests(SimpleTestCase):
    def test_credentials_are_removed_but_diagnostic_remains(self):
        message = redact_sensitive_text(
            "HTTP 401 password=synthetic-smtp-password access_token=example-sensitive-value "
            "Bearer example-bearer-value redis://user:example-password@redis:6379/0"
        )
        self.assertIn("HTTP 401", message)
        for secret in (
            "synthetic-smtp-password",
            "example-sensitive-value",
            "example-bearer-value",
            "example-password",
        ):
            self.assertNotIn(secret, message)

    def test_arbitrary_provider_token_is_redacted(self):
        token = "TEST-" + "synthetic-token-for-unit-test"
        response = Mock(status_code=401)
        response.json.return_value = {"message": "Authentication rejected: " + token}
        with patch("billing.mercadopago.requests.request", return_value=response):
            with self.assertRaises(MercadoPagoError) as exc:
                MercadoPagoProvider(token).test_connection()
        self.assertNotIn(token, str(exc.exception))
        self.assertIn("HTTP 401", str(exc.exception))

    @override_settings(
        WHATSAPP_GRAPH_BASE_URL="https://example.test",
        WHATSAPP_ACCESS_TOKEN="synthetic-cloud-token",
        WHATSAPP_PHONE_NUMBER_ID="test-id",
    )
    def test_cloud_error_cannot_echo_token(self):
        response = Mock(ok=False, text="invalid")
        response.json.return_value = {
            "error": {"message": "Rejected synthetic-cloud-token"}
        }
        with patch("communications.whatsapp.requests.post", return_value=response):
            with self.assertRaises(WhatsAppProviderError) as exc:
                send_text("5581999999999", "Teste")
        self.assertNotIn("synthetic-cloud-token", str(exc.exception))

    @override_settings(
        MASTER_WHATSAPP_GATEWAY_TOKEN="synthetic-gateway-token",
        MASTER_WHATSAPP_GATEWAY_URL="https://example.test",
    )
    def test_qr_gateway_rejects_malformed_provider_response(self):
        from communications.master_whatsapp import _gateway

        response = Mock(ok=True)
        response.json.return_value = []
        with patch(
            "communications.master_whatsapp.requests.request", return_value=response
        ):
            with self.assertRaisesMessage(ValueError, "Resposta inválida"):
                _gateway("GET", "/status")
