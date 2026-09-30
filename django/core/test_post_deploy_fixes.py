from datetime import datetime,time,timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import TestCase
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.models import Module,Plan,PlanModule,Subscription
from core.portal import _value
from scheduling.models import Appointment,Customer,Professional,ProfessionalAvailability,Service,TenantScheduleSettings
from scheduling.public_views import _candidates
from tenants.models import Tenant


class PostDeployFixesTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Empresa teste",slug="post-deploy-fixes",category="barbearia",
            public_enabled=True,public_booking_enabled=True,status=Tenant.Status.ACTIVE,onboarding_step=5,
            timezone="America/Recife")
        self.owner=User.objects.create_user(email="owner@post-deploy.test",tenant=self.tenant,role="owner")
        self.professional=Professional.objects.create(tenant=self.tenant,name="Ana",services_restricted=True)
        self.other=Professional.objects.create(tenant=self.tenant,name="Bia",services_restricted=True)
        self.service=Service.objects.create(tenant=self.tenant,name="Corte",price=40,duration_minutes=30)
        self.professional.services.add(self.service)
        self.customer=Customer.objects.create(tenant=self.tenant,name="Nome cadastrado",email="client@post-deploy.test",phone="5581999999999")
        self.day=timezone.localdate()+timedelta(days=2)
        ProfessionalAvailability.objects.create(tenant=self.tenant,professional=self.professional,
            weekday=self.day.isoweekday(),start_time=time(9),end_time=time(12))
        self.start=datetime.combine(self.day,time(9),tzinfo=ZoneInfo(self.tenant.timezone))
        self.client.force_login(self.owner)

    def appointment(self,**kwargs):
        return Appointment.objects.create(tenant=self.tenant,customer=self.customer,professional=self.professional,
            service=self.service,starts_at=self.start,ends_at=self.start+timedelta(minutes=30),**kwargs)

    def test_booking_preserves_customer_and_appointment_history(self):
        old=self.appointment(status=Appointment.Status.CANCELLED)
        response=self.client.post(reverse("public-booking",args=[self.tenant.slug]),{
            "service_id":self.service.pk,"professional_id":self.professional.pk,"starts_at":self.start.isoformat(),
            "name":"Nome desta reserva","email":self.customer.email,"phone":"5581888888888"},content_type="application/json")
        self.assertEqual(response.status_code,201,response.content)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.name,"Nome cadastrado")
        self.assertEqual(self.customer.phone,"5581999999999")
        new=Appointment.objects.get(pk=response.json()["id"])
        self.assertEqual(new.customer_name_snapshot,"Nome desta reserva")
        self.customer.name="Atualizado pelo gestor"
        self.customer.save()
        old.refresh_from_db()
        self.assertEqual(_value(old,"customer"),"Nome cadastrado")
        self.assertEqual(new.customer_display_name,"Nome desta reserva")
        self.assertContains(self.client.get(reverse("public-appointment-page",args=[response.json()["manage_token"]])),"Nome desta reserva")

    def test_rescheduling_only_offers_compatible_active_professionals(self):
        appointment=self.appointment()
        self.assertEqual([p.pk for p in _candidates(appointment)],[self.professional.pk])
        self.professional.active=False
        self.professional.save()
        self.assertEqual(_candidates(appointment),[])

    def test_agenda_filters_use_tenant_day_and_preserve_isolation(self):
        now=datetime(2026,10,2,2,tzinfo=ZoneInfo("UTC")) # Still October 1 in Recife.
        self.start=datetime(2026,10,1,23,tzinfo=ZoneInfo("America/Recife"))
        today=self.appointment(status=Appointment.Status.CONFIRMED)
        self.start+=timedelta(days=1)
        self.appointment(status=Appointment.Status.CONFIRMED)
        self.start-=timedelta(days=1)
        self.appointment(status=Appointment.Status.CANCELLED)
        another=Tenant.objects.create(name="Outra",slug="outside-post-deploy")
        outsider=Customer.objects.create(tenant=another,name="Não mostrar")
        Appointment.objects.create(tenant=another,customer=outsider,service=self.service,
            starts_at=self.start,ends_at=self.start+timedelta(minutes=30),status=Appointment.Status.CONFIRMED)
        with patch("core.portal.timezone.now",return_value=now):
            response=self.client.get(reverse("portal-resource-list",args=["agenda","agendamentos"]),{"period":"today","status":"confirmed"})
        self.assertEqual([row["obj"].pk for row in response.context["rows"]],[today.pk])
        self.assertContains(response,'value="today" selected')
        self.assertContains(response,static("js/live-agenda.js"))
        response=self.client.get(reverse("portal-resource-list",args=["agenda","agendamentos"]),{"period":"invalid","status":"invalid"})
        self.assertEqual(len(response.context["rows"]),3)

    def test_setup_separates_optional_copy_and_payment_blockers(self):
        response=self.client.get(reverse("portal-setup"))
        self.assertEqual(response.context["blockers"],[])
        self.assertFalse(response.context["steps"][3]["done"])
        TenantScheduleSettings.objects.create(tenant=self.tenant,allow_pay_on_site=False)
        response=self.client.get(reverse("portal-setup"))
        self.assertEqual(len(response.context["blockers"]),1)
        self.assertContains(response,"permita pagar na unidade")

    def test_setup_rejects_timetable_that_cannot_accommodate_offered_services(self):
        self.service.duration_minutes=240
        self.service.save()
        response=self.client.get(reverse("portal-setup"))
        self.assertFalse(response.context["steps"][2]["done"])
        self.service.duration_minutes=30
        self.service.save()
        self.professional.services.clear()
        response=self.client.get(reverse("portal-setup"))
        self.assertFalse(response.context["steps"][2]["done"])

    def test_arena_catalog_repair_preserves_price_subscription_and_master_disabled_links(self):
        arena=Module.objects.create(slug="sports_courts",name="Arena",active=True)
        plan=Plan.objects.create(name="Arena Sports",slug="old-arena-sports",monthly_price=Decimal("99.90"))
        subscription=Subscription.objects.create(tenant=self.tenant,plan=plan,started_at=timezone.now(),status="active")
        for _ in range(2):
            call_command("seed_sales_plans",stdout=StringIO())
        plan.refresh_from_db()
        subscription.refresh_from_db()
        self.assertEqual(plan.monthly_price,Decimal("99.90"))
        self.assertEqual(subscription.plan_id,plan.pk)
        self.assertEqual(plan.features["segments"],["arena"])
        self.assertEqual(PlanModule.objects.filter(plan=plan,module=arena).count(),1)
        PlanModule.objects.filter(plan=plan,module=arena).update(enabled=False)
        call_command("seed_sales_plans",stdout=StringIO())
        self.assertFalse(PlanModule.objects.get(plan=plan,module=arena).enabled)

    def test_signup_explains_actual_trial_and_cycle_prices(self):
        plan=Plan.objects.create(name="Plano de teste",slug="post-deploy-trial",monthly_price=40,annual_price=400,
            trial_days=7,trial_without_card=True)
        response=self.client.get(reverse("billing-signup"),{"plan":plan.pk})
        self.assertContains(response,"7 dias de teste sem cartão e sem cobrança agora")
        self.assertContains(response,"Para continuar após o teste")
        condition=next(item for item in response.context["plan_conditions"] if item["id"]==str(plan.pk))
        self.assertEqual(condition["prices"]["annual"],"400,00")
        self.assertContains(response,'signup-plan-conditions')

    def test_marketing_comparison_distinguishes_undeclared_from_unavailable(self):
        Plan.objects.create(name="Um",slug="comparison-one",monthly_price=10,
            features={"included_features":["Agenda pública"],"professionals":3})
        Plan.objects.create(name="Dois",slug="comparison-two",monthly_price=20)
        response=self.client.get(reverse("billing-plans"))
        rows={row["label"]:row["values"] for row in response.context["comparison"]}
        self.assertEqual(set(rows["Agenda pública"]),{"Declarado no plano","Não informado"})
        self.assertEqual(set(rows["Profissionais"]),{"3","Não informado"})

    def test_whatsapp_state_is_portuguese(self):
        response=self.client.get(reverse("tenant-whatsapp-settings"))
        self.assertContains(response,"Desconectado")
        self.assertNotContains(response,"disconnected")

    def test_arena_setup_requires_compatible_court_price_and_hours(self):
        from arena.models import Court,CourtHours,PriceRule
        self.tenant.category="arena"
        self.tenant.save()
        court=Court.objects.create(tenant=self.tenant,name="Quadra 1",slug="one")
        other=Court.objects.create(tenant=self.tenant,name="Quadra 2",slug="two")
        CourtHours.objects.create(tenant=self.tenant,court=court,weekday=1,start_time=time(9),end_time=time(10))
        PriceRule.objects.create(tenant=self.tenant,court=other,price_per_hour=100)
        response=self.client.get(reverse("portal-setup"))
        self.assertFalse(response.context["steps"][2]["done"])
        rule=PriceRule.objects.create(tenant=self.tenant,court=court,weekday=2,price_per_hour=100)
        response=self.client.get(reverse("portal-setup"))
        self.assertFalse(response.context["steps"][2]["done"])
        rule.weekday=1
        rule.save()
        response=self.client.get(reverse("portal-setup"))
        self.assertTrue(response.context["steps"][2]["done"])
        court.minimum_minutes=120
        court.save()
        response=self.client.get(reverse("portal-setup"))
        self.assertFalse(response.context["steps"][2]["done"])

    def test_arena_filters_apply_to_reservations_with_own_status_labels(self):
        from arena.models import Court,Reservation
        self.tenant.category="arena"
        self.tenant.save()
        court=Court.objects.create(tenant=self.tenant,name="Quadra",slug="filter-court")
        args=dict(tenant=self.tenant,court=court,customer_name="Cliente",customer_phone="5581999999999",
            starts_at=self.start,ends_at=self.start+timedelta(hours=1),duration_minutes=60,
            price_per_hour=100,total_amount=100)
        confirmed=Reservation.objects.create(public_id="filter-one",manage_token_hash="1"*64,status="confirmed",**args)
        Reservation.objects.create(public_id="filter-two",manage_token_hash="2"*64,status="cancelled",**args)
        response=self.client.get(reverse("portal-resource-list",args=["arena","reservas"]),{"status":"confirmed","period":"upcoming"})
        self.assertEqual([row["obj"].pk for row in response.context["rows"]],[confirmed.pk])
        self.assertContains(response,'value="confirmed" selected>Confirmada')

    def test_signup_switch_catalog_has_matching_segments_and_invalid_id_does_not_crash(self):
        barber=Plan.objects.create(name="Salão",slug="signup-barber",monthly_price=30,features={"segments":["barbearia"]})
        arena=Plan.objects.create(name="Arena",slug="signup-arena",monthly_price=50,features={"segments":["arena"]})
        response=self.client.get(reverse("billing-signup"),{"plan":barber.pk})
        conditions={row["id"]:row for row in response.context["plan_conditions"]}
        self.assertEqual({row["value"] for row in conditions[str(arena.pk)]["categories"]},{"","arena"})
        self.assertEqual({row["value"] for row in conditions[str(barber.pk)]["categories"]},{"","barbearia","salao"})
        for invalid in ("not-an-id","99999999999999999999999999"):
            self.assertEqual(self.client.get(reverse("billing-signup"),{"plan":invalid}).status_code,200)
