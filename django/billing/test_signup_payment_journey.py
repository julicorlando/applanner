from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from tenants.models import Tenant, TenantOnboarding
from billing.access import subscription_allows_access
from billing.models import Plan, Subscription, PaymentGateway, WebhookEvent
from billing.payment_services import create_platform_pix_charge
from billing.webhooks import _reconcile_platform


@override_settings(SUBSCRIPTION_ACCESS_ENFORCED=True)
class SignupPaymentJourneyTests(TestCase):
    def test_new_company_trial_expiry_verified_payment_unlocks_access(self):
        plan=Plan.objects.create(name="Barbearia",slug="signup-payment-journey",monthly_price="99.90",
            public_visible=True,active=True,trial_days=7,trial_without_card=True,features={"segments":["barbearia"]})
        response=self.client.post("/cadastro/",{"plan":plan.pk,"billing_cycle":"monthly","payment_method":"pix",
            "business_name":"Homologação QA jornada","postal_code":"55818255","category":"barbearia",
            "owner_name":"Gestor QA","email":"journey@example.com","phone":"81999990042",
            "password":"SyntheticTest2026!","password_confirm":"SyntheticTest2026!"})
        self.assertEqual(response.status_code,302)
        tenant=Tenant.objects.get(name="Homologação QA jornada")
        subscription=Subscription.objects.get(tenant=tenant)
        self.assertEqual(subscription.plan,plan)
        self.assertEqual(subscription.contracted_price,Decimal("99.90"))
        self.assertEqual(tenant.units.count(),1)
        self.assertTrue(subscription_allows_access(subscription))
        subscription.trial_ends_at=timezone.now()-timedelta(seconds=1)
        subscription.next_billing_at=subscription.trial_ends_at
        subscription.save()
        self.assertEqual(self.client.get("/").url,"/billing/assinatura/")
        self.assertFalse(subscription_allows_access(subscription))
        gateway=PaymentGateway.objects.create(environment="sandbox",active=True,last_test_status="validated",
            access_token_encrypted="unused",webhook_secret_encrypted="unused",webhook_url="https://example.com/webhooks/")
        with patch("billing.payment_services.platform_provider") as provider:
            provider.return_value.create_pix_order.return_value={"order_id":"journey-order","payment_id":"journey-payment",
                "status":"action_required","qr_code":"synthetic","qr_code_base64":"","ticket_url":"https://example.com/pix"}
            charge=create_platform_pix_charge(subscription=subscription,payer_email="journey@example.com")
        self.assertFalse(subscription_allows_access(subscription))
        event=WebhookEvent.objects.create(provider="mercadopago",event_id="journey-event",resource_id="journey-order",payload_hash="a"*64)
        order={"id":"journey-order","status":"processed","external_reference":charge.payment.provider_reference,
            "currency_id":"BRL","total_paid_amount":"99.90","transactions":{"payments":[{
                "id":"journey-payment","status":"processed","payment_method":{"id":"pix"}}]}}
        with patch("billing.webhooks.platform_provider") as provider:
            provider.return_value.get_order.return_value=order
            _reconcile_platform(event,gateway,{"type":"order","action":"order.processed"},"journey-order")
        subscription.refresh_from_db()
        self.assertTrue(subscription_allows_access(subscription))
        self.assertEqual(subscription.status,"active")
        TenantOnboarding.objects.filter(tenant=tenant).update(required=False)
        tenant.onboarding_step=5
        tenant.save()
        self.assertEqual(self.client.get("/").status_code,200)
