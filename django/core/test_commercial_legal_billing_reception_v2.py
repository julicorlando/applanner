from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.models import (
    Module, Payment, Plan, Subscription, TenantBankAccount, TenantModuleAddon,
)
from billing.module_services import module_monthly_price, sync_per_unit_addon_pricing
from contenthub.models import FAQItem, PlatformHomepage
from core.portal import _role_resource_visible, _role_resource_write
from accounts.route_middleware import _reception_mutation_allowed
from growth.attribution import infer_attribution
from communications.models import Notification
from engagement.models import ReferralIncentiveCampaign, ReferralReward
from engagement.referrals import (
    finalize_company_referral_discounts, qualify_referral_rewards_for_tenant,
)
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
        self.assertTrue(_reception_mutation_allowed("/app/financeiro/pdv/"))
        self.assertTrue(_reception_mutation_allowed("/app/relacionamento/inteligencia/"))
        self.assertFalse(_reception_mutation_allowed("/app/auto/os/10/acao/"))
        self.assertFalse(_reception_mutation_allowed("/app/barbearia/comandas/10/acao/"))


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


class BankAccountRegistrationTests(TestCase):
    def test_company_can_register_multiple_banks_and_keeps_details_encrypted(self):
        tenant=Tenant.objects.create(
            name="Empresa Bancária",slug="empresa-bancaria",status=Tenant.Status.ACTIVE
        )
        owner=User.objects.create_user(
            email="bank-owner@example.test",password="StrongPassword123!",
            tenant=tenant,role="owner",
        )
        self.client.force_login(owner)
        url=reverse("tenant-payment-gateway")

        first={
            "action":"bank_add","bank-bank_code":"001","bank-bank_name":"Banco do Brasil",
            "bank-holder_name":"Empresa Bancária","bank-holder_document":"12345678000199",
            "bank-branch":"1234","bank-account_number":"123456-7",
            "bank-account_type":"checking","bank-pix_key_type":"email",
            "bank-pix_key":"financeiro@empresa.test","bank-is_primary":"on",
        }
        second={
            "action":"bank_add","bank-bank_code":"077","bank-bank_name":"Banco Inter",
            "bank-holder_name":"Empresa Bancária","bank-holder_document":"12345678000199",
            "bank-branch":"0001","bank-account_number":"987654-3",
            "bank-account_type":"payment","bank-pix_key_type":"phone",
            "bank-pix_key":"+5581999999999",
        }
        self.assertEqual(self.client.post(url,first).status_code,302)
        self.assertEqual(self.client.post(url,second).status_code,302)

        rows=list(TenantBankAccount.objects.filter(tenant=tenant).order_by("id"))
        self.assertEqual(len(rows),2)
        self.assertTrue(rows[0].is_primary)
        self.assertFalse(rows[1].is_primary)
        self.assertNotIn("123456-7",rows[0].details_encrypted)
        self.assertNotIn("financeiro@empresa.test",rows[0].details_encrypted)


class ReferralRewardTests(TestCase):
    def _paid(self,tenant,subscription,amount="100.00"):
        return Payment.objects.create(
            tenant=tenant,subscription=subscription,purpose="subscription",
            amount=Decimal(amount),status=Payment.Status.PAID,paid_at=timezone.now(),
        )

    def test_company_reward_qualifies_only_after_second_payment_and_is_one_cycle_discount(self):
        referrer_tenant=Tenant.objects.create(
            name="Indicadora",slug="indicadora",status=Tenant.Status.ACTIVE
        )
        referred_tenant=Tenant.objects.create(
            name="Indicada",slug="indicada",status=Tenant.Status.ACTIVE
        )
        plan=Plan.objects.create(
            name="Plano indicação",slug="plano-indicacao-test",monthly_price=Decimal("100.00")
        )
        referrer_subscription=Subscription.objects.create(
            tenant=referrer_tenant,plan=plan,status=Subscription.Status.ACTIVE,
            started_at=timezone.now(),contracted_price=Decimal("100.00"),
            base_contracted_price=Decimal("100.00"),
        )
        referred_subscription=Subscription.objects.create(
            tenant=referred_tenant,plan=plan,status=Subscription.Status.ACTIVE,
            started_at=timezone.now(),contracted_price=Decimal("100.00"),
            base_contracted_price=Decimal("100.00"),
        )
        owner=User.objects.create_user(
            email="indicador@example.test",password="StrongPassword123!",
            tenant=referrer_tenant,role="owner",
        )
        campaign=ReferralIncentiveCampaign.objects.create(
            name="Campanha R$ 10",reward_type=ReferralIncentiveCampaign.RewardType.FIXED,
            reward_value=Decimal("10.00"),active=True,
        )
        reward=ReferralReward.objects.create(
            campaign=campaign,referrer_user=owner,referred_tenant=referred_tenant,
            referrer_kind=ReferralReward.ReferrerKind.COMPANY,
        )

        self._paid(referred_tenant,referred_subscription)
        qualify_referral_rewards_for_tenant(referred_tenant.pk)
        reward.refresh_from_db()
        referrer_subscription.refresh_from_db()
        self.assertEqual(reward.status,ReferralReward.Status.PENDING)
        self.assertEqual(referrer_subscription.contracted_price,Decimal("100.00"))

        self._paid(referred_tenant,referred_subscription)
        qualify_referral_rewards_for_tenant(referred_tenant.pk)
        reward.refresh_from_db()
        referrer_subscription.refresh_from_db()
        self.assertEqual(reward.status,ReferralReward.Status.APPLIED)
        self.assertEqual(reward.reward_amount,Decimal("10.00"))
        self.assertEqual(referrer_subscription.contracted_price,Decimal("90.00"))

        self._paid(referrer_tenant,referrer_subscription,amount="90.00")
        finalize_company_referral_discounts(referrer_tenant.pk)
        reward.refresh_from_db()
        referrer_subscription.refresh_from_db()
        self.assertEqual(reward.status,ReferralReward.Status.PAID)
        self.assertEqual(referrer_subscription.contracted_price,Decimal("100.00"))

    def test_professional_reward_requests_pix_after_second_payment(self):
        referrer_tenant=Tenant.objects.create(
            name="Empresa do profissional",slug="empresa-profissional",status=Tenant.Status.ACTIVE
        )
        referred_tenant=Tenant.objects.create(
            name="Indicada Profissional",slug="indicada-profissional",status=Tenant.Status.ACTIVE
        )
        plan=Plan.objects.create(
            name="Plano profissional",slug="plano-prof-ref-test",monthly_price=Decimal("80.00")
        )
        referred_subscription=Subscription.objects.create(
            tenant=referred_tenant,plan=plan,status=Subscription.Status.ACTIVE,
            started_at=timezone.now(),contracted_price=Decimal("80.00"),
            base_contracted_price=Decimal("80.00"),
        )
        professional=User.objects.create_user(
            email="prof-indicador@example.test",password="StrongPassword123!",
            tenant=referrer_tenant,role="professional",
        )
        campaign=ReferralIncentiveCampaign.objects.create(
            name="Campanha Profissional",reward_type=ReferralIncentiveCampaign.RewardType.PERCENT,
            reward_value=Decimal("10.00"),active=True,
        )
        reward=ReferralReward.objects.create(
            campaign=campaign,referrer_user=professional,referred_tenant=referred_tenant,
            referrer_kind=ReferralReward.ReferrerKind.PROFESSIONAL,
        )
        self._paid(referred_tenant,referred_subscription,amount="80.00")
        self._paid(referred_tenant,referred_subscription,amount="80.00")
        qualify_referral_rewards_for_tenant(referred_tenant.pk)

        reward.refresh_from_db()
        self.assertEqual(reward.status,ReferralReward.Status.PIX_REQUIRED)
        self.assertEqual(reward.reward_amount,Decimal("8.00"))
        self.assertTrue(Notification.objects.filter(
            tenant=referrer_tenant,destination=professional.email,
            template_key="referral_pix_request",
        ).exists())

        self.client.force_login(professional)
        response=self.client.post(reverse("professional-referrals"),{
            "reward":reward.pk,"pix_key":"prof-indicador@example.test",
        })
        self.assertEqual(response.status_code,302)
        reward.refresh_from_db()
        self.assertEqual(reward.status,ReferralReward.Status.READY)
        self.assertEqual(reward.pix_key_last4,"test")
        self.assertNotIn("prof-indicador@example.test",reward.pix_key_encrypted)
