from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from tenants.models import Tenant,Unit
from billing.entitlements import professional_capacity
from billing.models import (
    Module,Plan,Subscription,TenantModule,TenantModuleAddon,
)
from billing.module_services import (
    activate_module_request,cancel_module_addon,request_module,review_module_request,
)


class ProfessionalCapacityAddonTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(
            name="Rede Teste",slug="rede-capacidade",status=Tenant.Status.ACTIVE
        )
        Unit.objects.create(
            tenant=self.tenant,name="Matriz",is_primary=True,active=True
        )
        self.owner=User.objects.create_user(
            email="owner-capacidade@example.test",password="StrongPassword123!",
            tenant=self.tenant,role="owner",
        )
        self.master=User.objects.create_superuser(
            email="master-capacidade@example.test",password="StrongPassword123!"
        )
        self.plan=Plan.objects.create(
            name="Plano 3 profissionais",slug="plan-capacity-v3",
            monthly_price=Decimal("29.90"),
            features={"professionals":3,"units":1},
        )
        self.subscription=Subscription.objects.create(
            tenant=self.tenant,plan=self.plan,
            billing_cycle=Subscription.BillingCycle.MONTHLY,
            contracted_price=Decimal("29.90"),
            base_contracted_price=Decimal("29.90"),
            addon_contracted_price=Decimal("0.00"),
            status=Subscription.Status.ACTIVE,
            started_at=timezone.now(),
        )
        self.multiunit=Module.objects.create(
            slug="multiunit",name="Multiunidade",active=True,
            addon_sellable=True,addon_monthly_price=Decimal("39.99"),
            per_unit_billing=True,
        )
        self.extra=Module.objects.create(
            slug="professional-extra",name="+1 profissional extra",active=True,
            addon_sellable=True,addon_monthly_price=Decimal("7.50"),
        )

    def test_each_additional_contracted_unit_adds_three_professionals(self):
        base=professional_capacity(self.tenant)
        self.assertEqual(base["limit"],3)
        self.assertEqual(base["unit_bonus"],0)

        Unit.objects.create(tenant=self.tenant,name="Unidade 2",active=True)
        # A unidade física sozinha não aumenta a franquia: o Multiunidade precisa estar contratado.
        without_multiunit=professional_capacity(self.tenant)
        self.assertEqual(without_multiunit["limit"],3)

        TenantModule.objects.create(
            tenant=self.tenant,module=self.multiunit,enabled=True
        )
        with_second_unit=professional_capacity(self.tenant)
        self.assertEqual(with_second_unit["additional_units"],1)
        self.assertEqual(with_second_unit["unit_bonus"],3)
        self.assertEqual(with_second_unit["limit"],6)

        Unit.objects.create(tenant=self.tenant,name="Unidade 3",active=True)
        with_third_unit=professional_capacity(self.tenant)
        self.assertEqual(with_third_unit["additional_units"],2)
        self.assertEqual(with_third_unit["unit_bonus"],6)
        self.assertEqual(with_third_unit["limit"],9)

    def _approve_extra(self):
        request=request_module(
            tenant=self.tenant,module=self.extra,user=self.owner,
            note="Preciso de mais uma vaga",
        )
        review_module_request(
            module_request=request,user=self.master,approved=True,
            note="Aprovado",
        )
        adjustment=activate_module_request(
            module_request=request,user=self.master
        )
        self.assertEqual(adjustment.status,adjustment.Status.APPLIED)
        return request

    def test_professional_extra_is_repeatable_and_price_comes_from_master_catalog(self):
        first=self._approve_extra()
        addon=TenantModuleAddon.objects.get(
            tenant=self.tenant,module=self.extra,status=TenantModuleAddon.Status.ACTIVE
        )
        self.assertEqual(addon.quantity,1)
        self.assertEqual(addon.monthly_price,Decimal("7.50"))
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.contracted_price,Decimal("37.40"))
        self.assertEqual(professional_capacity(self.tenant)["limit"],4)

        # O Master altera o preço do próximo +1 sem reprecificar retroativamente o já contratado.
        self.extra.addon_monthly_price=Decimal("9.90")
        self.extra.save(update_fields=["addon_monthly_price"])

        second=self._approve_extra()
        self.assertNotEqual(first.pk,second.pk)
        addon.refresh_from_db()
        self.assertEqual(addon.quantity,2)
        self.assertEqual(addon.pricing_components,["7.50","9.90"])
        self.assertEqual(addon.monthly_price,Decimal("17.40"))
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.contracted_price,Decimal("47.30"))
        self.assertEqual(professional_capacity(self.tenant)["extra_professionals"],2)
        self.assertEqual(professional_capacity(self.tenant)["limit"],5)

        cancel_module_addon(addon=addon,user=self.owner)
        addon.refresh_from_db()
        self.assertEqual(addon.quantity,1)
        self.assertEqual(addon.monthly_price,Decimal("7.50"))
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.contracted_price,Decimal("37.40"))
        self.assertEqual(professional_capacity(self.tenant)["limit"],4)
