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
from finance.models import FinancialCategory,FinancialTransaction


class PostDeployFixesTests(TestCase):
    def test_health_warns_on_legacy_team_over_limit_and_missing_unit_hours(self):
        from core.portal import operation_health
        from tenants.models import Unit,UnitBusinessHours
        self.limited_plan(limit=1)
        unit=Unit.objects.create(tenant=self.tenant,name="Centro")
        checks={item["key"]:item for item in operation_health(self.tenant)}
        self.assertFalse(checks["team"]["ok"])
        self.assertIn("2 ativos para 1 autorizados",checks["team"]["detail"])
        self.assertFalse(checks["unit_hours"]["ok"])
        UnitBusinessHours.objects.create(tenant=self.tenant,unit=unit,weekday=4,opens_at=time(9),closes_at=time(18))
        self.assertTrue({item["key"]:item for item in operation_health(self.tenant)}["unit_hours"]["ok"])

    def test_failed_reactivation_describes_saved_inactive_state(self):
        self.limited_plan()
        inactive=Professional.objects.create(tenant=self.tenant,name="Inativo",active=False)
        response=self.client.post(reverse("portal-resource-edit",args=["agenda","profissionais",inactive.pk]),
            {"name":"Inativo","active":"on","all_services":"on","service_selection":"on"})
        self.assertContains(response,"Limite de 2 profissionais ativos atingido")
        self.assertNotContains(response,"Você pode editar este profissional ativo")
        inactive.refresh_from_db()
        self.assertFalse(inactive.active)

    def test_billing_explains_catalog_price_without_changing_contract(self):
        subscription=self.limited_plan()
        subscription.plan.monthly_price=Decimal("99.90")
        subscription.plan.save()
        subscription.base_contracted_price=Decimal("29.90")
        subscription.contracted_price=Decimal("29.90")
        subscription.save()
        response=self.client.get(reverse("billing-subscription-status"))
        self.assertContains(response,"valor-base contratado de R$ 29,90")
        self.assertContains(response,"catálogo para o mesmo ciclo é R$ 99,90")
        subscription.refresh_from_db()
        self.assertEqual(subscription.contracted_price,Decimal("29.90"))

    def limited_plan(self, limit=2):
        plan=Plan.objects.create(name="Plano com limite",slug="quota-test",features={"professionals":limit})
        return Subscription.objects.create(tenant=self.tenant,plan=plan,started_at=timezone.now(),status="trial",
            trial_ends_at=timezone.now()+timedelta(days=7))

    def test_trial_blocks_new_active_professional_but_preserves_existing(self):
        self.limited_plan()
        url=reverse("portal-resource-create",args=["agenda","profissionais"])
        response=self.client.post(url,{"name":"Excedente","active":"on","all_services":"on","service_selection":"on"})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"Limite de 2 profissionais ativos atingido")
        self.assertFalse(Professional.objects.filter(tenant=self.tenant,name="Excedente").exists())
        # Preserve operation when a legacy/imported team already exceeds its plan.
        Professional.objects.create(tenant=self.tenant,name="Legado")
        self.professional.name="Ana atualizada"
        self.professional.full_clean()
        self.professional.save()
        response=self.client.get(reverse("billing-subscription-status"))
        self.assertContains(response,"ultrapassa o limite")

    def test_inactive_professional_does_not_use_capacity_and_reactivation_is_validated(self):
        from django.core.exceptions import ValidationError
        self.limited_plan()
        inactive=Professional(tenant=self.tenant,name="Inativo",active=False)
        inactive.full_clean()
        inactive.save()
        inactive.active=True
        with self.assertRaises(ValidationError):
            inactive.full_clean()
        self.other.active=False
        self.other.save()
        inactive.full_clean()
        inactive.save()

    def test_master_override_can_expand_or_remove_limit_for_only_one_tenant(self):
        from billing.entitlements import professional_capacity
        from django.core.exceptions import ValidationError
        self.limited_plan()
        self.tenant.metadata={"professional_limit_override":3}
        self.tenant.save()
        candidate=Professional(tenant=self.tenant,name="Liberado")
        candidate.full_clean()
        candidate.save()
        self.assertTrue(professional_capacity(self.tenant)["overridden"])
        response=self.client.get(reverse("billing-subscription-status"))
        self.assertContains(response,"liberação especial do Master")
        self.tenant.metadata={"professional_limit_override":0}
        self.tenant.save()
        self.assertTrue(professional_capacity(self.tenant)["unlimited"])
        another=Professional(tenant=self.tenant,name="Sem limite")
        another.full_clean()
        self.tenant.metadata={}
        self.tenant.save()
        with self.assertRaises(ValidationError):
            another.full_clean()

    def test_master_limit_form_preserves_metadata_and_allows_reverting_to_plan(self):
        from core.master import TenantMasterForm
        self.tenant.metadata={"keep":"value"}
        self.tenant.save()
        data={"name":self.tenant.name,"slug":self.tenant.slug,"status":"active","locale":"pt-br",
              "timezone":"America/Recife","professional_limit_override":"0"}
        form=TenantMasterForm(data,instance=self.tenant)
        self.assertTrue(form.is_valid(),form.errors)
        form.save()
        self.assertEqual(self.tenant.metadata,{"keep":"value","professional_limit_override":0})
        data["professional_limit_override"]=""
        form=TenantMasterForm(data,instance=self.tenant)
        self.assertTrue(form.is_valid(),form.errors)
        form.save()
        self.assertEqual(self.tenant.metadata,{"keep":"value"})

    def test_public_booking_and_rescheduling_controls_have_associated_labels(self):
        from html.parser import HTMLParser
        class Labels(HTMLParser):
            def __init__(self):
                super().__init__()
                self.targets=set()
            def handle_starttag(self,tag,attrs):
                if tag=="label":
                    self.targets.add(dict(attrs).get("for"))
        response=self.client.get(reverse("tenant-public",args=[self.tenant.slug]))
        labels=Labels()
        labels.feed(response.content.decode())
        self.assertTrue({"booking-service","booking-professional","booking-date","booking-name",
                         "booking-phone","booking-email","booking-notes"}.issubset(labels.targets))
        from django.template.loader import render_to_string
        html=render_to_string("scheduling/public_appointment.html",{"appointment":self.appointment(status="confirmed"),
            "tenant":self.tenant,"professionals":[self.professional],"capabilities":{"can_reschedule":True}},request=response.wsgi_request)
        labels=Labels()
        labels.feed(html)
        self.assertTrue({"manage-professional","manage-date"}.issubset(labels.targets))

    def test_arena_sports_retired_without_removing_contracts(self):
        plan=Plan.objects.create(name="Arena Sports",slug="retired-arena",monthly_price="99.90",featured=True)
        subscription=Subscription.objects.create(tenant=self.tenant,plan=plan,started_at=timezone.now(),status="active")
        call_command("seed_sales_plans",stdout=StringIO())
        plan.refresh_from_db()
        subscription.refresh_from_db()
        self.assertFalse(plan.public_visible)
        self.assertFalse(plan.featured)
        self.assertEqual(subscription.plan_id,plan.pk)
        self.assertEqual(plan.monthly_price,Decimal("99.90"))
        self.assertNotContains(self.client.get(reverse("billing-plans")),"Arena Sports")

    def test_simplified_dashboard_keeps_important_shortcuts(self):
        response=self.client.get(reverse("portal-home"))
        self.assertContains(response,'aria-label="Atalhos da operação"')
        for name in ("reception-access","tenant-ratings","tenant-public"):
            url=reverse(name,args=[self.tenant.slug]) if name=="tenant-public" else reverse(name)
            self.assertContains(response,url)
        self.assertContains(response,"js/form-validation-pt")
        self.assertContains(response,"css/usability")

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
        self.assertEqual(old.customer_name_snapshot,"Nome cadastrado")
        self.assertEqual(_value(old,"customer"),"Atualizado pelo gestor")
        self.assertEqual(new.customer_display_name,"Atualizado pelo gestor")
        receipt=self.client.get(reverse("public-appointment-page",args=[response.json()["manage_token"]]))
        self.assertContains(receipt,"Nome desta reserva")
        self.assertNotContains(receipt,"Atualizado pelo gestor")

    def test_anonymous_booking_requires_phone_and_reuses_normalized_identity(self):
        from django.core.cache import cache
        cache.clear()
        self.addCleanup(cache.clear)
        self.client.logout()
        url=reverse("public-booking",args=[self.tenant.slug])
        payload={"service_id":self.service.pk,"professional_id":self.professional.pk,
            "starts_at":self.start.isoformat(),"name":"Nome informado","email":""}
        self.assertEqual(self.client.post(url,payload,content_type="application/json").status_code,400)
        response=self.client.post(url,{**payload,"phone":"(81) 99999-9999"},content_type="application/json")
        self.assertEqual(response.status_code,201,response.content)
        self.assertTrue(response.json()["customer_reused"])
        appointment=Appointment.objects.get(pk=response.json()["id"])
        self.assertEqual(appointment.customer_id,self.customer.pk)
        self.assertEqual(appointment.customer_display_name,self.customer.name)
        self.assertEqual(Customer.objects.filter(tenant=self.tenant).count(),1)

    def test_anonymous_automotive_booking_links_vehicle_and_customer_history(self):
        from django.core.cache import cache
        cache.clear()
        self.addCleanup(cache.clear)
        self.tenant.category="auto"
        self.tenant.save()
        self.client.logout()
        payload={"service_id":self.service.pk,"professional_id":self.professional.pk,
            "starts_at":self.start.isoformat(),"name":"Nome informado","phone":"81999999999",
            "vehicle_plate":"ABC1D23","vehicle_model":"Sedan"}
        response=self.client.post(reverse("public-booking",args=[self.tenant.slug]),payload,content_type="application/json")
        self.assertEqual(response.status_code,201,response.content)
        appointment=Appointment.objects.get(pk=response.json()["id"])
        self.assertEqual(appointment.customer_id,self.customer.pk)
        self.assertEqual(appointment.vehicle.customer_id,self.customer.pk)
        self.assertEqual(appointment.vehicle.plate,"ABC1D23")

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
        self.assertNotIn("Agenda pública",rows)
        self.assertEqual(set(rows["Profissionais"]),{"3","Consultar"})
        self.assertContains(response,"Agenda pública")

    def test_whatsapp_state_is_portuguese(self):
        response=self.client.get(reverse("tenant-whatsapp-settings"))
        self.assertContains(response,"Desconectado")
        self.assertNotContains(response,"disconnected")

    def test_operation_diagnostics_is_read_only_and_explains_optional_whatsapp(self):
        response=self.client.get(reverse("portal-diagnostics"))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"Diagnóstico da operação")
        self.assertContains(response,"WhatsApp é opcional")
        self.assertContains(response,"Página pública")
        self.assertEqual(response.context["checks"][-1]["key"],"whatsapp")

    def test_operation_home_exposes_simplified_view_toggle(self):
        response=self.client.get(reverse("portal-home"))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"Compactar painel")
        self.assertContains(response,"portal-view-toggle")
        self.assertContains(response,static("js/portal-dashboard.js"))

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

    def test_owner_can_create_reception_access_without_finance(self):
        response=self.client.post(reverse("reception-access"),{
            "email":"recepcao@post-deploy.test","password1":"StrongPass123!","password2":"StrongPass123!","active":"on",
        })
        self.assertRedirects(response,reverse("portal-home"))
        reception=User.objects.get(email="recepcao@post-deploy.test")
        self.assertEqual(reception.role,"reception")
        self.assertTrue(reception.must_change_password)
        reception.must_change_password=False
        reception.save(update_fields=["must_change_password"])
        self.client.force_login(reception)
        self.assertEqual(self.client.get(reverse("reception-access")).status_code,403)
        self.assertEqual(self.client.get(reverse("finance-summary")).status_code,403)

    def test_finance_summary_separates_gross_expenses_and_net(self):
        category=FinancialCategory.objects.create(tenant=self.tenant,name="Operação")
        paid_at=timezone.now()
        FinancialTransaction.objects.create(tenant=self.tenant,category=category,type="income",description="Serviço",amount=Decimal("100.00"),status="paid",paid_at=paid_at)
        FinancialTransaction.objects.create(tenant=self.tenant,category=category,type="expense",description="Compra",amount=Decimal("30.00"),status="paid",paid_at=paid_at)
        FinancialTransaction.objects.create(tenant=self.tenant,category=category,type="expense",description="Pendente",amount=Decimal("999.00"),status="pending")
        response=self.client.get(reverse("finance-summary"))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context["gross"],Decimal("100.00"))
        self.assertEqual(response.context["expenses"],Decimal("30.00"))
        self.assertEqual(response.context["net"],Decimal("70.00"))
        self.assertContains(response,"Receita líquida")
        self.assertContains(response,"R$ 70,00")
