from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from tenants.models import Tenant
from .models import (Module, ModuleRequest, PaymentGateway, Plan, Subscription,
                     SubscriptionModuleAdjustment, TenantModule, TenantModuleAddon)


class ModuleApprovalTests(TestCase):
    def setUp(self):
        self.master=User.objects.create_superuser(email="master-modulo@example.test",password="SenhaForte123!")
        self.tenant=Tenant.objects.create(name="Arena Centro",slug="arena-centro-modulo")
        self.owner=User.objects.create_user(email="owner-modulo@example.test",password="SenhaForte123!",
                                            tenant=self.tenant,role="owner")
        self.plan=Plan.objects.create(name="Arena",slug="arena-modulo",monthly_price=Decimal("49.90"))
        self.subscription=Subscription.objects.create(
            tenant=self.tenant,plan=self.plan,started_at=timezone.now(),
            status=Subscription.Status.ACTIVE,billing_cycle=Subscription.BillingCycle.QUARTERLY,
            contracted_price=Decimal("135.00"),base_contracted_price=Decimal("135.00"),
        )
        self.module=Module.objects.create(slug="products",name="Produtos",active=True,
                                          addon_sellable=True,addon_monthly_price=Decimal("10.00"))
        self.request=ModuleRequest.objects.create(
            public_id="module-request-approval",tenant=self.tenant,module=self.module,
            requested_by=self.owner,quoted_monthly_price=Decimal("10.00"),
        )
        self.url=reverse("master-operational-object-action",args=["module-request-approve",self.request.pk])
        self.client.force_login(self.master)

    def test_approval_updates_local_subscription_and_does_not_charge_twice(self):
        self.assertRedirects(self.client.post(self.url),reverse("master-resource-list",args=["solicitacoes-modulos"]))
        self.subscription.refresh_from_db()
        self.request.refresh_from_db()
        self.assertEqual(self.subscription.contracted_price,Decimal("165.00"))
        self.assertEqual(self.subscription.addon_contracted_price,Decimal("30.00"))
        self.assertEqual(self.request.status,ModuleRequest.Status.ACTIVE)
        self.assertTrue(TenantModule.objects.get(tenant=self.tenant,module=self.module).enabled)
        self.assertEqual(self.client.post(self.url).status_code,302)
        self.assertEqual(TenantModuleAddon.objects.filter(tenant=self.tenant).count(),1)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.contracted_price,Decimal("165.00"))

    @patch("billing.module_services.platform_provider")
    def test_provider_rejection_persists_failure_and_retry_updates_amount(self,provider):
        self.subscription.provider_subscription_id="preapproval-123"
        self.subscription.provider_environment="production"
        self.subscription.save()
        PaymentGateway.objects.create(provider="mercadopago",environment="production",active=False,
                                      last_test_status=PaymentGateway.TestStatus.VALIDATED)
        PaymentGateway.objects.create(provider="mercadopago",environment="sandbox",active=True,
                                      last_test_status=PaymentGateway.TestStatus.VALIDATED)
        provider.return_value.update_subscription_amount.side_effect=RuntimeError("Mercado Pago HTTP 400")
        self.assertRedirects(self.client.post(self.url),reverse("master-resource-list",args=["solicitacoes-modulos"]))
        self.request.refresh_from_db()
        self.subscription.refresh_from_db()
        self.assertEqual(self.request.status,ModuleRequest.Status.PAYMENT_FAILED)
        self.assertEqual(self.subscription.contracted_price,Decimal("135.00"))
        self.assertFalse(TenantModuleAddon.objects.filter(tenant=self.tenant).exists())
        adjustment=SubscriptionModuleAdjustment.objects.get(module_request=self.request)
        self.assertEqual(adjustment.status,SubscriptionModuleAdjustment.Status.FAILED)
        self.assertContains(self.client.get(reverse("master-resource-list",args=["solicitacoes-modulos"])),
                            "Tentar ativar novamente")
        provider.return_value.update_subscription_amount.side_effect=None
        self.client.post(self.url)
        self.subscription.refresh_from_db()
        self.request.refresh_from_db()
        adjustment.refresh_from_db()
        self.assertEqual(adjustment.status,SubscriptionModuleAdjustment.Status.APPLIED)
        self.assertEqual(self.request.status,ModuleRequest.Status.ACTIVE)
        self.assertEqual(self.subscription.contracted_price,Decimal("165.00"))
        used_gateway=provider.call_args.args[0]
        self.assertEqual(used_gateway.environment,"production")
        provider.return_value.update_subscription_amount.assert_called_with("preapproval-123",Decimal("165.00"))

    def test_missing_original_gateway_does_not_unlock_module(self):
        self.subscription.provider_subscription_id="preapproval-123"
        self.subscription.provider_environment="production"
        self.subscription.save()
        self.client.post(self.url)
        self.request.refresh_from_db()
        self.subscription.refresh_from_db()
        self.assertEqual(self.request.status,ModuleRequest.Status.PAYMENT_FAILED)
        self.assertEqual(self.subscription.contracted_price,Decimal("135.00"))
        self.assertFalse(TenantModule.objects.filter(tenant=self.tenant,module=self.module).exists())
