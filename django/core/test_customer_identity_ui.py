from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.models import Plan, Subscription
from scheduling.models import Appointment, Customer, Professional, Service
from tenants.models import Tenant


class CustomerIdentityUITests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Identificação",slug="identity-ui")
        self.owner=User.objects.create_user(email="identity@example.test",role="owner",tenant=self.tenant)
        self.client.force_login(self.owner)
        self.professional=Professional.objects.create(tenant=self.tenant,name="Ana")
        self.customer=Customer.objects.create(tenant=self.tenant,name="Nome cadastrado",phone="5581999999999")
        self.service=Service.objects.create(tenant=self.tenant,name="Corte",price=50,duration_minutes=30)
        start=timezone.now()+timedelta(days=2)
        self.appointment=Appointment.objects.create(tenant=self.tenant,customer=self.customer,
            professional=self.professional,service=self.service,starts_at=start,
            ends_at=start+timedelta(minutes=30),status="confirmed",customer_name_snapshot="Nome da reserva")

    def set_limit(self,limit):
        plan=Plan.objects.create(name="Plano",slug="identity-quota",features={"professionals":limit})
        Subscription.objects.create(tenant=self.tenant,plan=plan,started_at=timezone.now(),status="trial",
            trial_ends_at=timezone.now()+timedelta(days=7))

    def test_limit_visible_before_submit_and_edit_keeps_existing_active(self):
        self.set_limit(1)
        url=reverse("portal-resource-create",args=["agenda","profissionais"])
        response=self.client.get(url)
        self.assertContains(response,"1 profissionais ativos de 1 autorizados")
        self.assertContains(response,"0 vagas disponíveis")
        self.assertContains(response,"Não há vagas para ativar outro profissional")
        self.assertContains(response,"Profissionais inativos não ocupam vagas")
        response=self.client.get(reverse("portal-resource-edit",args=["agenda","profissionais",self.professional.pk]))
        self.assertContains(response,"Você pode editar este profissional ativo")

    def test_capacity_uses_master_override_and_tenant_only(self):
        self.set_limit(1)
        self.tenant.metadata={"professional_limit_override":2}
        self.tenant.save()
        other=Tenant.objects.create(name="Outra",slug="another-identity")
        Professional.objects.create(tenant=other,name="Outro profissional")
        response=self.client.get(reverse("portal-resource-create",args=["agenda","profissionais"]))
        self.assertContains(response,"1 vaga disponível")
        self.assertContains(response,"Liberação especial do Master aplicada")
        self.assertNotContains(response,"Não há vagas")
        self.tenant.metadata={"professional_limit_override":0}
        self.tenant.save()
        response=self.client.get(reverse("portal-resource-create",args=["agenda","profissionais"]))
        self.assertContains(response,"Sem limite autorizado pelo Master")
        self.assertNotContains(response,"0 vagas disponíveis")

    def test_both_names_visible_in_internal_views_without_changing_customer(self):
        urls=["/",reverse("portal-resource-list",args=["agenda","agendamentos"]),
              reverse("portal-resource-edit",args=["agenda","agendamentos",self.appointment.pk])]
        for url in urls:
            with self.subTest(url=url):
                response=self.client.get(url)
                self.assertContains(response,"Nome no cadastro: Nome cadastrado")
                self.assertContains(response,"Nome informado na reserva: Nome da reserva")
        self.customer.refresh_from_db()
        self.appointment.refresh_from_db()
        self.assertEqual(self.customer.name,"Nome cadastrado")
        self.assertEqual(self.customer.phone,"5581999999999")
        self.assertEqual(self.appointment.customer_id,self.customer.pk)

    def test_equal_or_empty_snapshot_does_not_show_difference(self):
        url=reverse("portal-resource-list",args=["agenda","agendamentos"])
        for name in ("", " Nome cadastrado "):
            self.appointment.customer_name_snapshot=name
            self.appointment.save()
            self.assertNotContains(self.client.get(url),"Nome informado na reserva:")

    def test_professional_sees_identity_difference_only_in_own_appointments(self):
        user=User.objects.create_user(email="professional-identity@example.test",role="professional",tenant=self.tenant)
        self.professional.user=user
        self.professional.save()
        other=Tenant.objects.create(name="Outra",slug="identity-other")
        customer=Customer.objects.create(tenant=other,name="Cliente confidencial")
        Appointment.objects.create(tenant=other,customer=customer,customer_name_snapshot="Reserva confidencial",
            service=Service.objects.create(tenant=other,name="Outro",price=20,duration_minutes=30),
            starts_at=self.appointment.starts_at,ends_at=self.appointment.ends_at,status="confirmed")
        self.client.force_login(user)
        for url in (reverse("professional-area"),reverse("professional-appointment",args=[self.appointment.pk])):
            response=self.client.get(url)
            self.assertContains(response,"Nome informado na reserva: Nome da reserva")
            self.assertNotContains(response,"Reserva confidencial")
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(reverse("portal-resource-list",args=["agenda","agendamentos"])),"Reserva confidencial")
