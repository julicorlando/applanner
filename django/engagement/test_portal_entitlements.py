from types import SimpleNamespace

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, TestCase
from django.utils import timezone

from accounts.models import User
from billing.models import Module, Plan, PlanModule, Subscription
from engagement.portal import _tenant
from tenants.models import Tenant


class PortalEntitlementsTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Empresa", slug="portal-entitlements")
        self.owner = User.objects.create_user(
            email="entitlements@example.test", tenant=self.tenant, role="owner"
        )
        self.plan = Plan.objects.create(
            name="Plano", slug="portal-entitlements", monthly_price="99.90"
        )
        Subscription.objects.create(
            tenant=self.tenant,
            plan=self.plan,
            status="active",
            started_at=timezone.now(),
        )
        self.request = RequestFactory().get("/")
        self.request.user = self.owner
        self.request.session = {}

    def test_uncontracted_modules_are_denied(self):
        for route in (
            "engagement-domains",
            "engagement-packages",
            "engagement-loyalty",
            "engagement-waitlist",
            "engagement-intelligence",
        ):
            with self.subTest(route=route):
                self.request.resolver_match = SimpleNamespace(url_name=route)
                with self.assertRaises(PermissionDenied):
                    _tenant(self.request)

    def test_contracted_module_keeps_tenant_scope(self):
        module = Module.objects.create(name="Pacotes", slug="packages", active=True)
        PlanModule.objects.create(plan=self.plan, module=module, enabled=True)
        other = Tenant.objects.create(
            name="Outra empresa", slug="other-portal-entitlements"
        )
        self.request.session["portal_tenant_id"] = other.pk
        self.request.resolver_match = SimpleNamespace(url_name="engagement-packages")
        self.assertEqual(_tenant(self.request).pk, self.tenant.pk)

    def test_master_still_uses_explicit_company_selection(self):
        self.request.user = User.objects.create_superuser(
            email="entitlements-master@example.test", password="SyntheticPassword123!"
        )
        self.request.session["portal_tenant_id"] = self.tenant.pk
        self.assertEqual(_tenant(self.request), self.tenant)
