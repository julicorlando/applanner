from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.models import (
    Module, Plan, Subscription, TenantModuleAddon,
)
from billing.module_services import module_monthly_price, sync_per_unit_addon_pricing
from contenthub.models import FAQItem, PlatformHomepage
from core.portal import _role_resource_visible, _role_resource_write
from growth.attribution import infer_attribution
from legal.models import LegalDocument
from scheduling.models import Appointment, Customer, Professional, Service
from tenants.models import Tenant, Unit


class PublicLegalAndHomeTests(TestCase):
    def test_home_shows_faq_and_legal_links(self):
        FAQItem.objects.create(
            question="Como funciona o teste grátis?",
            answer="A empresa pode experimentar o ApPlanner antes da contratação.",
            sort_order=1,
        )
        response=self.client.get(reverse("home"))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"Como funciona o teste grátis?")
        self.assertContains(response,reverse("legal-public-document",args=["privacidade"]))
        self.assertContains(response,reverse("legal-public-document",args=["termos-empresas"]))
        self.assertContains(response,reverse("legal-public-document",args=["cancelamento-clientes"]))

    def test_public_privacy_document_does_not_force_authenticated_acceptance(self):
        doc=LegalDocument.objects.create(
            type=LegalDocument.Type.PRIVACY,version="public-test",
            title="Política de Privacidade pública",content="Conteúdo público.",
            status=LegalDocument.Status.PUBLISHED,published_at=timezone.now(),
            requires_acceptance=False,
        )
        response=self.client.get(reverse("legal-public-document",args=["privacidade"]))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,doc.title)

        tenant=Tenant.objects.create(name="Empresa",slug="empresa-legal",status=Tenant.Status.ACTIVE)
        owner=User.objects.create_user(
            email="owner-legal@example.test",password="StrongPassword123!",
            tenant=tenant,role="owner",
        )
        self.client.force_login(owner)
        dashboard=self.client.get(reverse("portal-home"))
        self.assertNotEqual(dashboard.status_code,302)

    def test_medical_segment_is_hidden_until_master_enables_it(self):
        Plan.objects.create(
            name="Médico / Clínica",slug="segment-medico",monthly_price=Decimal("99.00"),
            active=True,public_visible=True,
        )
        platform=PlatformHomepage.objects.create(pk=1,medical_segment_visible=False)
        response=self.client.get(reverse("home"))
        self.assertNotContains(response,"Agenda profissional, prontuário criptografado")

        platform.medical_segment_visible=True
        platform.save(update_fields=["medical_segment_visible","updated_at"])
        response=self.client.get(reverse("home"))
        self.assertContains(response,"Agenda profissional, prontuário criptografado")


class AttributionTests(TestCase):
    def test_social_and_paid_sources_are_inferred_automatically(self):
        factory=RequestFactory()
        social=factory.get("/",HTTP_REFERER="https://www.instagram.com/applanner/")
        social.session={}
        self.assertEqual(
            infer_attribution(social),
            {"source":"instagram","medium":"social"},
        )

        paid=factory.get("/?gclid=abc123")
        paid.session={}
        inferred=infer_attribution(paid)
        self.assertEqual(inferred["source"],"google_ads")
        self.assertEqual(inferred["medium"],"paid")

        organic=factory.get("/")
        organic.session={}
        self.assertEqual(
            infer_attribution(organic),
            {"source":"organic","medium":"organic"},
        )


class MultiunitBillingTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(
            name="Rede Multiunidade",slug="rede-multiunidade",status=Tenant.Status.ACTIVE
        )
        Unit.objects.create(tenant=self.tenant,name="Matriz",is_primary=True,active=True)
        Unit.objects.create(tenant=self.tenant,name="Unidade 2",active=True)
        self.plan=Plan.objects.create(
            name="Plano Base",slug="plano-multiunit-test",monthly_price=Decimal("50.00")
        )
        self.module=Module.objects.create(
            name="Multiunidade",slug="multiunit-test",addon_monthly_price=Decimal("10.00"),
            addon_sellable=True,per_unit_billing=True,active=True,
        )

    def test_module_price_is_per_active_unit_and_syncs_subscription(self):
        self.assertEqual(module_monthly_price(self.module,self.tenant),Decimal("20.00"))
        subscription=Subscription.objects.create(
            tenant=self.tenant,plan=self.plan,billing_cycle=Subscription.BillingCycle.MONTHLY,
            contracted_price=Decimal("60.00"),base_contracted_price=Decimal("50.00"),
            addon_contracted_price=Decimal("10.00"),status=Subscription.Status.ACTIVE,
            started_at=timezone.now(),
        )
        addon=TenantModuleAddon.objects.create(
            tenant=self.tenant,module=self.module,monthly_price=Decimal("10.00"),
            status=TenantModuleAddon.Status.ACTIVE,
            billing_mode=TenantModuleAddon.BillingMode.MERGED,
        )
        sync_per_unit_addon_pricing(self.tenant.pk)
        addon.refresh_from_db()
        subscription.refresh_from_db()
        self.assertEqual(addon.monthly_price,Decimal("20.00"))
        self.assertEqual(subscription.addon_contracted_price,Decimal("20.00"))
        self.assertEqual(subscription.contracted_price,Decimal("70.00"))


class ReceptionPolicyTests(TestCase):
    def test_reception_can_consult_unlisted_resources_but_only_write_authorized_ones(self):
        reception=SimpleNamespace(role="reception",is_superuser=False)
        self.assertTrue(_role_resource_visible(reception,"financeiro","lancamentos"))
        self.assertTrue(_role_resource_visible(reception,"auto","manutencoes"))
        self.assertTrue(_role_resource_write(reception,"agenda","clientes"))
        self.assertTrue(_role_resource_write(reception,"agenda","folgas"))
        self.assertTrue(_role_resource_write(reception,"barbearia","fila"))
        self.assertTrue(_role_resource_write(reception,"arena","espera-arena"))
        self.assertFalse(_role_resource_write(reception,"financeiro","lancamentos"))
        self.assertFalse(_role_resource_write(reception,"agenda","profissionais"))


class ProfessionalReturnScopeTests(TestCase):
    def test_professional_return_list_requires_two_completed_appointments_with_same_professional(self):
        tenant=Tenant.objects.create(
            name="Barbearia Retorno",slug="barbearia-retorno",status=Tenant.Status.ACTIVE
        )
        user=User.objects.create_user(
            email="prof-retorno@example.test",password="StrongPassword123!",
            tenant=tenant,role="professional",
        )
        professional=Professional.objects.create(
            tenant=tenant,name="Ana",user=user,public_slug="ana"
        )
        other=Professional.objects.create(tenant=tenant,name="Outra")
        service=Service.objects.create(
            tenant=tenant,name="Corte",duration_minutes=30,price=Decimal("50.00")
        )
        recurring=Customer.objects.create(tenant=tenant,name="Cliente recorrente")
        mixed=Customer.objects.create(tenant=tenant,name="Cliente não recorrente com Ana")
        now=timezone.now()
        for days in (60,30):
            start=now-timedelta(days=days)
            Appointment.objects.create(
                tenant=tenant,customer=recurring,professional=professional,service=service,
                starts_at=start,ends_at=start+timedelta(minutes=30),
                status=Appointment.Status.COMPLETED,
            )
        own_start=now-timedelta(days=40)
        Appointment.objects.create(
            tenant=tenant,customer=mixed,professional=professional,service=service,
            starts_at=own_start,ends_at=own_start+timedelta(minutes=30),
            status=Appointment.Status.COMPLETED,
        )
        for days in (20,10):
            start=now-timedelta(days=days)
            Appointment.objects.create(
                tenant=tenant,customer=mixed,professional=other,service=service,
                starts_at=start,ends_at=start+timedelta(minutes=30),
                status=Appointment.Status.COMPLETED,
            )

        self.client.force_login(user)
        response=self.client.get(reverse("professional-area"))
        self.assertEqual(response.status_code,200)
        names=[row.customer.name for row in response.context["return_rows"]]
        self.assertIn("Cliente recorrente",names)
        self.assertNotIn("Cliente não recorrente com Ana",names)
