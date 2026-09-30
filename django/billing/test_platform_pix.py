from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from tenants.models import Tenant
from .models import CheckoutSession,Payment,PaymentGateway,PixCharge,Plan,Subscription,WebhookEvent
from .payment_services import create_platform_pix_charge
from .webhooks import _reconcile_platform


class PlatformPixTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Empresa Pix",slug="empresa-pix")
        self.owner=User.objects.create_user(email="owner-pix@example.com",password="SenhaDeTeste123!",tenant=self.tenant,role="owner")
        plan=Plan.objects.create(name="Mensal",slug="mensal-pix",monthly_price="49.90")
        self.subscription=Subscription.objects.create(
            tenant=self.tenant,plan=plan,contracted_price="49.90",started_at=timezone.now(),
            status=Subscription.Status.PAST_DUE,
        )
        self.gateway=PaymentGateway.objects.create(
            environment="sandbox",active=True,last_test_status="validated",
            access_token_encrypted="not-used",webhook_secret_encrypted="not-used",
            webhook_url="https://example.test/webhooks/mercadopago/",
        )

    def _charge(self):
        class Provider:
            def create_pix_order(self,**kwargs):
                return {"order_id":"order-pix-1","payment_id":"pay-pix-1","status":"action_required",
                        "qr_code":"000201PIX-VALIDO","qr_code_base64":"cG5n","ticket_url":"https://example.test/pix"}
        with patch("billing.payment_services.platform_provider",return_value=Provider()):
            return create_platform_pix_charge(subscription=self.subscription,payer_email=self.owner.email)

    def _event(self):
        return WebhookEvent.objects.create(provider="mercadopago",event_id="order-1",resource_id="order-pix-1",payload_hash="a"*64)

    def _order(self,charge,paid="49.90"):
        return {"id":"order-pix-1","status":"processed","external_reference":charge.payment.provider_reference,
                "currency_id":"BRL","total_paid_amount":paid,
                "transactions":{"payments":[{"id":"pay-pix-1","status":"processed","payment_method":{"id":"pix"}}]}}

    def test_owner_can_choose_pix_and_reuse_pending_code(self):
        self.client.force_login(self.owner)
        with patch("billing.payment_services.platform_provider") as provider:
            provider.return_value.create_pix_order.return_value={
                "order_id":"order-pix-1","payment_id":"pay-pix-1","status":"action_required",
                "qr_code":"000201PIX-VALIDO","qr_code_base64":"cG5n","ticket_url":"https://example.test/pix",
            }
            response=self.client.post("/billing/assinatura/pix/")
            self.assertRedirects(response,"/billing/assinatura/pix/")
            self.assertContains(self.client.get("/billing/assinatura/pix/"),"000201PIX-VALIDO")
            self.client.post("/billing/assinatura/pix/")
            provider.return_value.create_pix_order.assert_called_once()
            self.assertRegex(
                provider.return_value.create_pix_order.call_args.kwargs["external_reference"],
                r"^[A-Za-z0-9_-]{1,64}$",
            )
        self.assertEqual(PixCharge.objects.count(),1)
        self.assertEqual(self.subscription.status,Subscription.Status.PAST_DUE)
        self.assertEqual(self.client.post("/billing/assinatura/pagar/").url,"/billing/assinatura/pix/")

    def test_separate_payer_email_is_sent_to_mercado_pago(self):
        self.client.force_login(self.owner)
        with patch("billing.payment_services.platform_provider") as provider:
            provider.return_value.create_pix_order.return_value={
                "order_id":"order-pix-1","payment_id":"pay-pix-1",
                "qr_code":"000201PIX-VALIDO","qr_code_base64":"","status":"action_required",
            }
            response=self.client.post("/billing/assinatura/pix/",{"payment_email":"buyer@testuser.com"})
        self.assertEqual(response.status_code,302)
        self.assertEqual(provider.return_value.create_pix_order.call_args.kwargs["payer_email"],"buyer@testuser.com")
        self.assertContains(self.client.get("/billing/assinatura/pix/"),"000201PIX-VALIDO")

    def test_invalid_payer_email_does_not_call_provider(self):
        self.client.force_login(self.owner)
        with patch("billing.payment_services.platform_provider") as provider:
            response=self.client.post("/billing/assinatura/pix/",{"payment_email":"invalido"})
        self.assertEqual(response.status_code,302)
        self.assertFalse(PixCharge.objects.exists())
        provider.assert_not_called()

    def test_only_verified_matching_order_activates_subscription(self):
        charge=self._charge()
        event=self._event()
        class Provider:
            def get_order(self,reference):
                return self.order
        provider=Provider()
        provider.order=self._order(charge,paid="0.01")
        with patch("billing.webhooks.platform_provider",return_value=provider):
            with self.assertRaisesMessage(ValueError,"Valor do Pix"):
                _reconcile_platform(event,self.gateway,{"type":"order","action":"order.processed"},"order-pix-1")
            self.subscription.refresh_from_db()
            self.assertEqual(self.subscription.status,Subscription.Status.PAST_DUE)
            provider.order=self._order(charge)
            _reconcile_platform(event,self.gateway,{"type":"order","action":"order.processed"},"order-pix-1")
            self.subscription.refresh_from_db()
            self.assertEqual(self.subscription.status,Subscription.Status.ACTIVE)
            self.assertGreater(self.subscription.next_billing_at,timezone.now()+timedelta(days=27))
            charge.refresh_from_db()
            self.assertEqual(charge.payment.status,Payment.Status.PAID)
            self.assertEqual(charge.checkout_session.status,CheckoutSession.Status.PAID)

    def test_pix_does_not_activate_on_notification_without_order_payment(self):
        charge=self._charge()
        event=self._event()
        class Provider:
            def get_order(self,reference):
                return {**self.order,"transactions":{"payments":[]}}
        provider=Provider()
        provider.order=self._order(charge)
        with patch("billing.webhooks.platform_provider",return_value=provider):
            _reconcile_platform(event,self.gateway,{"type":"order"},"order-pix-1")
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status,Subscription.Status.PAST_DUE)
