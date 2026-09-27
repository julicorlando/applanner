import hashlib
import hmac
import time
from unittest.mock import patch
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


from django.test import TestCase

from accounts.models import User
from tenants.models import Tenant,Unit
from .models import PaymentGateway,Plan,Subscription


class PublicSignupTests(TestCase):
    def setUp(self):
        self.plan=Plan.objects.create(
            name="Inicial",
            slug="signup-inicial",
            monthly_price=Decimal("49.90"),
            trial_days=14,
            trial_without_card=True,
            public_visible=True,
            active=True,
        )

    def test_public_plans_page_lists_plan(self):
        response=self.client.get("/planos/")
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"Inicial")
        self.assertContains(response,"49,90")

    def test_signup_creates_tenant_owner_unit_and_subscription(self):
        response=self.client.post("/cadastro/",{
            "plan":self.plan.pk,
            "billing_cycle":Subscription.BillingCycle.MONTHLY,
            "business_name":"Barbearia Teste",
            "category":"barbearia",
            "owner_name":"Responsável",
            "email":"owner-signup@example.com",
            "phone":"81999999999",
            "password":"StrongPassword!123",
            "password_confirm":"StrongPassword!123",
        })
        self.assertEqual(response.status_code,302)
        tenant=Tenant.objects.get(name="Barbearia Teste")
        user=User.objects.get(email="owner-signup@example.com")
        self.assertEqual(user.tenant,tenant)
        self.assertEqual(user.role,"owner")
        self.assertTrue(Unit.objects.filter(tenant=tenant,is_primary=True).exists())
        subscription=Subscription.objects.get(tenant=tenant)
        self.assertEqual(subscription.plan,self.plan)
        self.assertEqual(subscription.status,Subscription.Status.TRIAL)

    def test_owner_can_resume_secure_payment_link(self):
        from django.utils import timezone
        from .payment_services import create_platform_subscription

        tenant=Tenant.objects.create(name="Assinante",slug="assinante")
        owner=User.objects.create_user(email="pay@example.com",password="StrongPassword123!",role="owner",tenant=tenant)
        subscription=Subscription.objects.create(tenant=tenant,plan=self.plan,started_at=timezone.now(),contracted_price="49.90")
        PaymentGateway.objects.create(environment="sandbox",active=True,last_test_status="validated",
                                      access_token_encrypted="unused",webhook_secret_encrypted="unused",webhook_url="https://example.test/webhook")

        class Provider:
            def create_subscription(self,**kwargs):
                return {"reference":"preapproval-123","init_point":"https://example.test/pagar"}

        with patch("billing.payment_services.platform_provider",return_value=Provider()):
            create_platform_subscription(subscription=subscription,payer_email=owner.email,
                                         back_url="https://example.test/voltar",idempotency_key="idempotent")
        subscription.refresh_from_db()
        self.assertEqual(subscription.provider_checkout_url,"https://example.test/pagar")
        self.client.force_login(owner)
        response=self.client.post("/billing/assinatura/pagar/")
        self.assertRedirects(response,"https://example.test/pagar",fetch_redirect_response=False)
        self.assertContains(self.client.get("/billing/assinatura/"),"Continuar pagamento seguro")
