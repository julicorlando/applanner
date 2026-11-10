from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.models import Plan
from billing.views import SignupForm
from communications.models import Notification
from legal.models import LegalAcceptance, LegalDocument
from tenants.models import Tenant


class PlanNamesAndTenantTermsTests(TestCase):
    def setUp(self):
        self.master = User.objects.create_superuser(
            email="master-planos@example.test", password="SenhaDeTeste123!"
        )
        self.tenant = Tenant.objects.create(name="Oficina Recife", slug="oficina-recife")
        self.owner = User.objects.create_user(
            email="responsavel@example.test", password="SenhaDeTeste123!",
            tenant=self.tenant, role="owner",
        )
        self.other = Tenant.objects.create(name="Outra empresa", slug="outra-empresa")
        self.plan = Plan.objects.create(name="Plano Oficina Completa", slug="oficina-completa")
        self.client.force_login(self.master)

    def _publish(self, version):
        document = LegalDocument.objects.create(
            type=LegalDocument.Type.TERMS, version=version, title="Termos de Uso",
            content="Regras da plataforma", status=LegalDocument.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        LegalAcceptance.objects.create(user=self.master, document=document)
        return document

    def test_plan_name_appears_in_signup_and_master_selection(self):
        self.assertEqual(str(self.plan), "Plano Oficina Completa")
        self.assertIn("Plano Oficina Completa", str(SignupForm()["plan"]))
        self.assertNotIn("Plan object", str(SignupForm()["plan"]))
        response = self.client.get(reverse("master-resource-create", args=["assinaturas"]))
        self.assertContains(response, "Plano Oficina Completa")

    def test_master_sees_pending_and_acceptance_for_current_version(self):
        doc = self._publish("v1")
        url = reverse("master-tenant-access", args=[self.tenant.pk])
        response = self.client.get(url)
        self.assertContains(response, self.owner.email)
        self.assertContains(response, "Pendente")
        self.assertContains(response, "v1")
        self.client.post(reverse("master-send-tenant-terms", args=[self.tenant.pk]))
        notice = Notification.objects.get(template_key="tenant_terms_acceptance")
        self.assertEqual(notice.status, Notification.Status.QUEUED)
        self.assertEqual(notice.payload["document_id"], doc.pk)
        self.assertContains(self.client.get(url), "Na fila")
        LegalAcceptance.objects.create(user=self.owner, tenant=self.tenant, document=doc)
        self.assertContains(self.client.get(url), "Aceito")
        self.client.post(reverse("master-send-tenant-terms", args=[self.tenant.pk]))
        self.assertEqual(Notification.objects.count(), 1)

    def test_new_version_requires_new_acceptance_and_new_invitation(self):
        old = self._publish("v1")
        LegalAcceptance.objects.create(user=self.owner, document=old, tenant=self.tenant)
        self.client.post(reverse("master-send-tenant-terms", args=[self.tenant.pk]))
        self.assertFalse(Notification.objects.exists())
        current = self._publish("v2")
        response = self.client.get(reverse("master-tenant-access", args=[self.tenant.pk]))
        self.assertContains(response, "Pendente")
        self.assertContains(response, "v2")
        self.client.post(reverse("master-send-tenant-terms", args=[self.tenant.pk]))
        self.assertEqual(Notification.objects.get().payload["document_id"], current.pk)

    def test_invites_are_scoped_to_tenant_and_need_published_terms(self):
        url = reverse("master-send-tenant-terms", args=[self.tenant.pk])
        self.client.post(url)
        self.assertFalse(Notification.objects.exists())
        self._publish("v1")
        self.client.post(url)
        self.assertEqual(list(Notification.objects.values_list("tenant_id", flat=True)), [self.tenant.pk])
        self.assertNotContains(
            self.client.get(reverse("master-tenant-access", args=[self.other.pk])),
            self.owner.email,
        )
