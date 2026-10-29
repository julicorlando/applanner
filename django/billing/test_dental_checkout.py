from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch,Mock
from django.test import TestCase,override_settings
from django.utils import timezone
from django.core.exceptions import PermissionDenied,ValidationError
from . import test_professional_capacity_addons as fixtures
from .models import Module,PaymentGateway,ModuleRequest,TenantModuleAddon,Payment
from .module_services import request_module,review_module_request
from .dental_seats import checkout_seats,quote_initial_charge
from .pix_reconciliation import reconcile_pix_charge


class DentalCheckoutTests(TestCase):
    def setUp(self):
        fixtures.ProfessionalCapacityAddonTests.setUp(self)
        self.module,_=Module.objects.get_or_create(slug="dental-professional-extra",defaults={"name":"Vaga"})
        self.module.active=True;self.module.addon_sellable=True;self.module.addon_monthly_price=Decimal("10.00");self.module.save()
        self.subscription.provider_environment="sandbox";self.subscription.next_billing_at=timezone.now()+timedelta(days=15);self.subscription.save()
        self.row=request_module(tenant=self.tenant,module=self.module,user=self.owner,quantity=2)
        self.row=review_module_request(module_request=self.row,user=self.master,approved=True,note="Aprovado")
        self.gateway=PaymentGateway.objects.create(provider="mercadopago",environment="sandbox",active=True,last_test_status="validated")
        self.provider=Mock()
        self.provider.create_pix_order.return_value={"order_id":"dental-order","payment_id":"dental-payment","qr_code":"test-qr","status":"pending"}

    def checkout(self):
        with patch("billing.dental_seats.platform_provider",return_value=self.provider):
            return checkout_seats(row=self.row,user=self.owner)

    def test_quantity_and_initial_proration_are_quoted_before_payment(self):
        self.assertEqual(self.row.quantity,2)
        self.assertGreater(self.row.initial_charge_amount,Decimal("9"));self.assertLess(self.row.initial_charge_amount,Decimal("11"))
        self.assertIsNotNone(self.row.proration_until)
        self.assertFalse(TenantModuleAddon.objects.filter(module=self.module).exists())

    def test_checkout_reuses_charge_and_provider_key(self):
        first=self.checkout();second=self.checkout()
        self.assertEqual(first.pk,second.pk);self.assertEqual(Payment.objects.filter(purpose="dental-seat").count(),1)
        self.provider.create_pix_order.assert_called_once()
        self.assertEqual(self.provider.create_pix_order.call_args.kwargs["amount"],self.row.initial_charge_amount)

    def test_unapproved_expired_and_other_tenant_checkout_are_denied(self):
        from accounts.models import User
        outsider=User.objects.create_user(email="other-dental-owner@example.test",role="owner")
        with self.assertRaises(PermissionDenied):checkout_seats(row=self.row,user=outsider)
        self.row.status="pending";self.row.save(update_fields=["status"])
        with self.assertRaises(ValidationError):self.checkout()
        self.row.status="approved";self.row.seat_quote_expires_at=timezone.now()-timedelta(seconds=1);self.row.save()
        with self.assertRaises(ValidationError):self.checkout()

    def test_order_reconciliation_activates_quantity_without_extending_subscription_cycle(self):
        charge=self.checkout();self.subscription.refresh_from_db();before=self.subscription.next_billing_at
        order={"id":"dental-order","external_reference":charge.payment.provider_reference,"currency_id":"BRL",
               "status":"processed","total_paid_amount":str(charge.amount),
               "transactions":{"payments":[{"id":"dental-payment","status":"approved","payment_method":{"id":"pix"}}]}}
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(reconcile_pix_charge(charge.pk,gateway=self.gateway,provider=self.provider,order=order))
        addon=TenantModuleAddon.objects.get(module=self.module,tenant=self.tenant)
        self.assertEqual(addon.quantity,2);self.assertEqual(addon.monthly_price,Decimal("20.00"))
        self.subscription.refresh_from_db();self.assertEqual(self.subscription.next_billing_at,before)
        self.assertEqual(self.subscription.contracted_price,Decimal("49.90"))
        with self.captureOnCommitCallbacks(execute=True):reconcile_pix_charge(charge.pk,gateway=self.gateway,provider=self.provider,order=order)
        addon.refresh_from_db();self.assertEqual(addon.quantity,2)

    def test_provider_amount_mismatch_does_not_release_seats(self):
        charge=self.checkout()
        order={"id":"dental-order","external_reference":charge.payment.provider_reference,"currency_id":"BRL","status":"processed","total_paid_amount":"0.01", "transactions":{"payments":[{"status":"approved","payment_method":{"id":"pix"}}]}}
        with self.assertRaises(ValueError):reconcile_pix_charge(charge.pk,gateway=self.gateway,provider=self.provider,order=order)
        self.assertFalse(TenantModuleAddon.objects.filter(module=self.module).exists())

    def test_price_change_does_not_reprice_approved_request(self):
        self.module.addon_monthly_price=Decimal("100.00");self.module.save()
        quote,until=quote_initial_charge(self.row)
        self.assertLess(quote,Decimal("11.00"));self.assertEqual(until,self.subscription.next_billing_at)

    @override_settings(DEPLOYMENT_ENVIRONMENT="homologacao")
    def test_homologation_rejects_production_provider(self):
        from .payment_services import platform_provider
        self.gateway.environment="production"
        with self.assertRaises(ValueError):platform_provider(self.gateway)

    def test_rejection_requires_recorded_justification(self):
        row=ModuleRequest.objects.create(public_id="reject-dental",tenant=self.tenant,module=self.module,requested_by=self.owner,quoted_monthly_price=10)
        with self.assertRaises(ValidationError):review_module_request(module_request=row,user=self.master,approved=False)
        rejected=review_module_request(module_request=row,user=self.master,approved=False,note="Justificativa fictícia")
        self.assertEqual(rejected.status,"rejected")

    def settle(self):
        charge=self.checkout()
        order={"id":"dental-order","external_reference":charge.payment.provider_reference,"currency_id":"BRL","status":"processed","total_paid_amount":str(charge.amount),"transactions":{"payments":[{"id":"dental-payment","status":"approved","payment_method":{"id":"pix"}}]}}
        with self.captureOnCommitCallbacks(execute=True):reconcile_pix_charge(charge.pk,gateway=self.gateway,provider=self.provider,order=order)
        charge.payment.refresh_from_db()
        return charge.payment

    def test_full_refund_removes_only_request_capacity_and_recurring_amount_once(self):
        from .dental_seats import reconcile_dental_refund
        payment=self.settle();payment.status="refunded";payment.save()
        self.assertTrue(reconcile_dental_refund(payment.pk));self.assertTrue(reconcile_dental_refund(payment.pk))
        addon=TenantModuleAddon.objects.get(module=self.module)
        self.assertEqual(addon.quantity,0);self.assertEqual(addon.status,"cancelled")
        self.subscription.refresh_from_db();self.assertEqual(self.subscription.contracted_price,Decimal("29.90"))

    def test_partial_refund_holds_new_capacity_for_financial_review(self):
        from .dental_seats import reconcile_dental_refund
        payment=self.settle();payment.status="partially_refunded";payment.save()
        self.assertFalse(reconcile_dental_refund(payment.pk))
        addon=TenantModuleAddon.objects.get(module=self.module)
        self.assertEqual(addon.quantity,2);self.assertEqual(addon.status,"past_due")
        self.subscription.refresh_from_db();self.assertEqual(self.subscription.contracted_price,Decimal("49.90"))

    def master_action(self):
        from django.test import RequestFactory
        from django.contrib.messages.storage.fallback import FallbackStorage
        from core.master import operational_action
        request=RequestFactory().post('/master/',{})
        request.user=self.master;request.session={};request._messages=FallbackStorage(request)
        return operational_action(request,'module-request-approve',self.row.pk)

    def test_master_can_renew_expired_quote_before_payment(self):
        self.row.seat_quote_expires_at=timezone.now()-timedelta(minutes=1);self.row.save()
        self.assertEqual(self.master_action().status_code,302)
        self.row.refresh_from_db();self.assertGreater(self.row.seat_quote_expires_at,timezone.now())
        self.assertEqual(self.row.quoted_monthly_price,Decimal('10.00'))
        self.assertFalse(Payment.objects.filter(purpose='dental-seat').exists())

    def test_master_reuses_paid_proof_after_activation_failure(self):
        charge=self.checkout();payment=charge.payment
        payment.status='paid';payment.paid_at=timezone.now();payment.provider_status='approved';payment.provider_payment_id='dental-payment';payment.save()
        self.row.status='payment_failed';self.row.save()
        self.assertEqual(self.master_action().status_code,302)
        self.row.refresh_from_db();self.assertEqual(self.row.status,'active')
        self.assertEqual(Payment.objects.filter(purpose='dental-seat').count(),1)
        self.assertEqual(TenantModuleAddon.objects.get(module=self.module).quantity,2)
