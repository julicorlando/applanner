from datetime import timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from billing.models import Plan
from scheduling.models import Appointment,Customer,Service
from tenants.models import Tenant


class AgendaUXTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="UX",slug="ux-qa")
        self.owner=User.objects.create_user(email="ux@example.test",role="owner",tenant=self.tenant)
        self.client.force_login(self.owner)
        self.customer=Customer.objects.create(tenant=self.tenant,name="Nome único",phone="5581999999999")
        self.service=Service.objects.create(tenant=self.tenant,name="Corte",duration_minutes=30,price=45)

    def appointment(self,status,days=1):
        start=timezone.now()+timedelta(days=days)
        return Appointment.objects.create(tenant=self.tenant,customer=self.customer,customer_name_snapshot="Nome informado diferente",
            service=self.service,starts_at=start,ends_at=start+timedelta(minutes=30),status=status)

    def test_dashboard_excludes_cancelled_completed_and_past(self):
        confirmed=self.appointment("confirmed")
        self.appointment("cancelled")
        self.appointment("completed")
        self.appointment("confirmed",days=-1)
        response=self.client.get("/")
        self.assertEqual([a.pk for a in response.context["next_appointments"]],[confirmed.pk])
        self.assertContains(response,"Nome único")
        self.assertNotContains(response,"Nome informado diferente")
        self.assertContains(response,"?period=cancelled")

    def test_upcoming_cancelled_and_history_filters_are_separate(self):
        upcoming=self.appointment("confirmed")
        cancelled=self.appointment("cancelled")
        historical=self.appointment("completed",days=-1)
        url=reverse("portal-resource-list",args=["agenda","agendamentos"])
        for period,expected in (("upcoming",upcoming),("cancelled",cancelled),("history",historical)):
            response=self.client.get(url,{"period":period})
            self.assertEqual([row["obj"].pk for row in response.context["rows"]],[expected.pk])

    def test_arena_catalog_explains_segment_limits_without_inventing_them(self):
        Plan.objects.create(name="Arena",slug="arena-ux",features={"segments":["arena"],"professionals":3,"units":1})
        response=self.client.get(reverse("billing-plans"))
        rows={row["label"]:row["values"] for row in response.context["comparison"]}
        self.assertEqual(rows["Profissionais"],["Não se aplica"])
        self.assertEqual(rows["Quadras"],["Consultar"])
        self.assertEqual(rows["Reservas por mês"],["Consultar"])

    def test_signup_removes_test_account_instruction(self):
        response=self.client.get(reverse("billing-signup"))
        self.assertNotContains(response,"Em testes")
        self.assertContains(response,"Preencha somente se outra pessoa")
