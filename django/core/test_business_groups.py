from datetime import timedelta
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from tenants.models import Tenant
from tenants.groups import BusinessGroup, GroupCompany, GroupRoyalty
from finance.models import FinancialTransaction
from billing.models import Module, TenantModule


@override_settings(SUBSCRIPTION_ACCESS_ENFORCED=False)
class BusinessGroupTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Grupo raiz", slug="group-root", status="active"
        )
        self.other = Tenant.objects.create(
            name="Empresa participante",
            slug="group-member",
            status="active",
            public_enabled=True,
        )
        self.owner = User.objects.create_user(
            email="group-owner@example.test", tenant=self.tenant, role="owner"
        )
        self.other_owner = User.objects.create_user(
            email="member-owner@example.test", tenant=self.other, role="owner"
        )
        module = Module.objects.create(name="Financeiro", slug="finance")
        for tenant in [self.tenant, self.other]:
            TenantModule.objects.create(tenant=tenant, module=module, enabled=True)
        self.group = BusinessGroup.objects.create(name="Grupo teste", owner=self.owner)
        self.link = GroupCompany.objects.create(
            group=self.group, tenant=self.other, royalty_percent=10
        )
        self.today = timezone.localdate()
        FinancialTransaction.objects.create(
            tenant=self.other,
            type="income",
            description="Receita privada",
            amount=12345,
            competence_at=self.today,
            status="paid",
        )
        self.url = reverse("business-groups")
        self.client.force_login(self.owner)

    def test_group_cannot_see_indicators_before_company_authorization_and_after_revocation(
        self,
    ):
        self.assertEqual(self.client.get(self.url).context["rows"], [])
        self.client.force_login(self.other_owner)
        self.assertEqual(
            self.client.post(
                self.url, {"action": "accept", "company": self.link.pk}
            ).status_code,
            302,
        )
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).context["rows"][0]["revenue"], 12345)
        self.client.force_login(self.other_owner)
        self.client.post(self.url, {"action": "revoke", "company": self.link.pk})
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).context["rows"], [])

    def test_group_owner_cannot_accept_consent_on_behalf_of_another_company(self):
        self.assertEqual(
            self.client.post(
                self.url, {"action": "accept", "company": self.link.pk}
            ).status_code,
            404,
        )
        self.link.refresh_from_db()
        self.assertEqual(self.link.status, "pending")
        self.client.force_login(self.other_owner)
        self.assertEqual(
            self.client.get(self.url, {"group": self.group.pk}).status_code, 404
        )

    def test_royalty_proposal_requires_company_approval_and_cannot_duplicate(self):
        self.link.status = "active"
        self.link.save()
        day = self.today.replace(day=1) - timedelta(days=1)
        period = day.replace(day=1)
        FinancialTransaction.objects.create(
            tenant=self.other,
            type="income",
            description="Receita anterior",
            amount=100,
            competence_at=day,
            status="paid",
        )
        payload = {
            "action": "accrue",
            "group": self.group.pk,
            "company": self.link.pk,
            "period": day.strftime("%Y-%m"),
        }
        self.client.post(self.url, payload)
        self.client.post(self.url, payload)
        royalty = GroupRoyalty.objects.get()
        self.assertEqual(royalty.amount, 10)
        self.assertIsNone(royalty.expense_id)
        self.client.force_login(self.other_owner)
        self.client.post(
            self.url,
            {
                "action": "approve_royalty",
                "company": self.link.pk,
                "royalty": royalty.pk,
            },
        )
        self.client.post(
            self.url,
            {
                "action": "approve_royalty",
                "company": self.link.pk,
                "royalty": royalty.pk,
            },
        )
        royalty.refresh_from_db()
        self.assertEqual(royalty.expense.amount, 10)
        self.assertEqual(royalty.expense.status, "pending")
        self.assertEqual(
            FinancialTransaction.objects.filter(source_type="group_royalty").count(), 1
        )

    def test_invalid_period_does_not_cause_server_error(self):
        self.assertEqual(self.client.get(self.url, {"period": "bad"}).status_code, 200)
