from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.models import Payment, Plan, Subscription
from core.audit import append_audit
from core.audit_labels import category, describe
from operations.models import SupportTicket
from tenants.models import Tenant


@override_settings(SUBSCRIPTION_ACCESS_ENFORCED=False)
class MasterBoardTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.master = User.objects.create_superuser(email="master-board@example.test", password="SyntheticPassword123!")
        self.company = Tenant.objects.create(name="Clínica Painel Exemplo", slug="painel-exemplo", status="active",
                                             category="odontologia", phone="81988887777", document="12345678000199")
        self.owner = User.objects.create_user(email="dona-painel@example.test", tenant=self.company, role="owner", first_name="Dona")
        plan = Plan.objects.create(name="Plano Painel", slug="plano-painel", monthly_price=100)
        sub = Subscription.objects.create(tenant=self.company, plan=plan, status="active", started_at=now)
        Payment.objects.create(tenant=self.company, subscription=sub, purpose="subscription", provider="mercadopago",
                               environment="production", amount=100, status="pending", due_at=now - timedelta(days=2),
                               provider_reference="painel-ref", provider_payment_id="p1")
        self.ticket = SupportTicket.objects.create(tenant=self.company, user=self.owner, protocol="PAINEL-001",
                                                   category="agenda", subject="Ajuda com agenda", description="Teste")
        self.other = Tenant.objects.create(name="Outra Empresa Em Dia", slug="outra-em-dia", status="active")
        self.client.force_login(self.master)

    def test_home_lists_what_needs_attention_and_platform_search(self):
        response = self.client.get(reverse("master-home"))
        self.assertContains(response, "Pede sua atenção agora")
        self.assertContains(response, "Chamados de suporte em aberto")
        self.assertContains(response, 'action="%s"' % reverse("master-global-search"))
        self.assertContains(response, "Configurações da plataforma")

    def test_companies_board_filters_overdue_tickets_and_search(self):
        url = reverse("master-companies")
        page = self.client.get(url)
        self.assertContains(page, "Clínica Painel Exemplo")
        self.assertContains(page, "Vencida")
        overdue = self.client.get(url, {"situacao": "inadimplente"})
        self.assertContains(overdue, "Clínica Painel Exemplo")
        self.assertNotContains(overdue, "Outra Empresa Em Dia")
        self.assertContains(self.client.get(url, {"situacao": "suporte"}), "1 aberto(s)")
        self.assertContains(self.client.get(url, {"q": "8888-7777"}), "Clínica Painel Exemplo")
        self.assertContains(self.client.get(url, {"q": "dona-painel"}), "Clínica Painel Exemplo")
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_company_page_tabs_and_readable_history(self):
        append_audit(tenant=self.company, user=self.master, action="master.patient_record.viewed", entity_type="Customer", entity_id=1)
        url = reverse("master-company-detail", args=[self.company.pk])
        for tab in ["geral", "acessos", "plano", "clinica", "suporte", "historico"]:
            with self.subTest(tab=tab):
                self.assertEqual(self.client.get(url, {"aba": tab}).status_code, 200)
        self.assertContains(self.client.get(url), "Zona de risco")
        self.assertContains(self.client.get(url), "Entrar no ambiente da empresa")
        self.assertContains(self.client.get(url, {"aba": "acessos"}), "Responsável")
        history = self.client.get(url, {"aba": "historico", "tipo": "prontuario"})
        self.assertContains(history, "Master abriu um prontuário")
        self.assertEqual(category("clinic.cash.closed"), "caixa")
        self.assertEqual(describe("clinic.cash_entry.updated"), "Lançamento do caixa alterado")
        self.assertNotIn(".", describe("billing.subscription.cancelled"))

    def test_search_finds_companies_users_and_tickets(self):
        url = reverse("master-global-search")
        self.assertContains(self.client.get(url, {"q": "dona-painel"}), "?aba=acessos")
        self.assertContains(self.client.get(url, {"q": "PAINEL-001"}), "Ajuda com agenda")
        self.assertContains(self.client.get(url, {"q": "12345678"}), reverse("master-company-detail", args=[self.company.pk]))

    def test_operating_banner_and_leaving_the_company(self):
        session = self.client.session
        session["portal_tenant_id"] = self.company.pk
        session.save()
        self.assertContains(self.client.get(reverse("portal-home"), follow=True), "Sair do ambiente")
        response = self.client.post(reverse("master-leave-company"))
        self.assertRedirects(response, reverse("master-home"), fetch_redirect_response=False)
        self.assertNotIn("portal_tenant_id", self.client.session)
