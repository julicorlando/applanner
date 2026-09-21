import hashlib
import hmac
import time
from decimal import Decimal

from django.test import SimpleTestCase

from .mercadopago import MercadoPagoProvider


class MercadoPagoSignatureTests(SimpleTestCase):
    def test_valid_signature_matches_documented_manifest(self):
        secret="test-webhook-secret-123"
        request_id="request-123"
        data_id="PAYMENTABC123"
        ts=str(int(time.time()))
        manifest=f"id:{data_id.lower()};request-id:{request_id};ts:{ts};"
        digest=hmac.new(secret.encode(),manifest.encode(),hashlib.sha256).hexdigest()
        signature=f"ts={ts},v1={digest}"

        self.assertTrue(
            MercadoPagoProvider.valid_webhook_signature(
                signature,request_id,data_id,secret,now=int(ts)
            )
        )

    def test_stale_signature_is_rejected(self):
        secret="test-webhook-secret-123"
        request_id="request-123"
        data_id="payment-1"
        ts="1000"
        manifest=f"id:{data_id};request-id:{request_id};ts:{ts};"
        digest=hmac.new(secret.encode(),manifest.encode(),hashlib.sha256).hexdigest()
        self.assertFalse(
            MercadoPagoProvider.valid_webhook_signature(
                f"ts={ts},v1={digest}",request_id,data_id,secret,now=2000
            )
        )


class MercadoPagoProviderTests(SimpleTestCase):
    def test_subscription_payload_preserves_cycle_and_trial(self):
        calls=[]

        def transport(method,path,payload,idempotency,token):
            calls.append((method,path,payload,idempotency,token))
            return {"id":"preapproval-1","status":"pending","init_point":"https://example.test"}

        provider=MercadoPagoProvider("TEST-123456789012345",transport=transport)
        result=provider.create_subscription(
            reason="ApPlanner Pro",
            external_reference="subscription:99",
            payer_email="cliente@example.com",
            back_url="https://applanner.example/return",
            amount=Decimal("99.90"),
            frequency=3,
            trial_days=14,
            idempotency_key="idem-99",
        )

        self.assertEqual(result["reference"],"preapproval-1")
        method,path,payload,idempotency,_=calls[0]
        self.assertEqual((method,path),("POST","/preapproval"))
        self.assertEqual(payload["auto_recurring"]["frequency"],3)
        self.assertEqual(payload["auto_recurring"]["free_trial"]["frequency"],14)
        self.assertEqual(idempotency,"idem-99")
