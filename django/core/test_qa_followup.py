import hashlib
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.models import Plan
from core.master import PlanMasterForm
from scheduling.models import Appointment, Customer, Professional, Service, TenantScheduleSettings
from tenants.models import Tenant


class QAFollowupTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Salão QA",slug="salao-followup",phone="81900000000")
        self.owner=User.objects.create_user(email="owner-followup@example.test",tenant=self.tenant,role="owner")
        self.prof=Professional.objects.create(tenant=self.tenant,name="Profissional exclusivo")
        self.service=Service.objects.create(tenant=self.tenant,name="Serviço exclusivo",duration_minutes=30,price=55)
        self.customer=Customer.objects.create(tenant=self.tenant,name="Cliente",phone="5581900000000")
        self.cfg=TenantScheduleSettings.objects.create(tenant=self.tenant)
        start=timezone.now()+timedelta(hours=1)
        self.token="qa-followup-token"
        self.row=Appointment.objects.create(tenant=self.tenant,customer=self.customer,service=self.service,
            professional=self.prof,starts_at=start,ends_at=start+timedelta(minutes=30),status="confirmed",
            customer_manage_token_hash=hashlib.sha256(self.token.encode()).hexdigest())
        self.manage=reverse("public-appointment-page",args=[self.token])

    def test_anonymous_customer_sees_deadline_and_contact_without_mutation(self):
        response=self.client.get(self.manage)
        self.assertContains(response,"120 minutos de antecedência")
        self.assertContains(response,self.tenant.phone)
        self.assertNotContains(response,'value="cancel"')
        self.client.post(self.manage,{"action":"cancel"})
        self.row.refresh_from_db()
        self.assertEqual(self.row.status,"confirmed")

    def test_disabled_finished_and_expired_actions_explain_each_reason(self):
        self.row.starts_at=timezone.now()+timedelta(days=1)
        self.row.ends_at=self.row.starts_at+timedelta(minutes=30)
        self.row.save()
        self.cfg.customer_can_cancel=False
        self.cfg.save()
        self.assertContains(self.client.get(self.manage),"não permite cancelar online")
        self.cfg.customer_can_cancel=True
        self.cfg.save()
        response=self.client.get(self.manage)
        self.assertContains(response,'value="cancel"')
        self.assertNotContains(response,"Opções de alteração")
        self.row.status="cancelled"
        self.row.save()
        self.assertContains(self.client.get(self.manage),"o agendamento está cancelado")
        self.row.status="confirmed"
        self.row.starts_at=timezone.now()-timedelta(minutes=30)
        self.row.save()
        self.assertContains(self.client.get(self.manage),"horário do agendamento já começou")

    def test_pix_without_connection_or_email_explains_why_generation_is_disabled(self):
        self.row.booking_payment="full"
        self.row.save()
        self.assertContains(self.client.get(self.manage),"ainda não habilitou o recebimento online")
        with patch("billing.payment_services.has_connected_tenant_gateway",return_value=True):
            response=self.client.get(self.manage)
        self.assertContains(response,"é necessário um e-mail")
        self.assertNotContains(response,'value="pay"')

    def test_search_service_professional_and_live_refresh_keep_tenant_scope(self):
        other=Tenant.objects.create(name="Outra",slug="other-followup")
        Appointment.objects.create(tenant=other,customer=Customer.objects.create(tenant=other,name="Outro"),
            service=Service.objects.create(tenant=other,name=self.service.name,duration_minutes=30,price=55),
            starts_at=self.row.starts_at,ends_at=self.row.ends_at,status="confirmed")
        self.client.force_login(self.owner)
        url=reverse("portal-resource-list",args=["agenda","agendamentos"])
        for q in (self.service.name,self.prof.name,self.customer.phone):
            for headers in ({},{"HTTP_X_REQUESTED_WITH":"XMLHttpRequest"}):
                response=self.client.get(url,{"q":q,"period":"upcoming"},**headers)
                self.assertEqual([r["obj"].pk for r in response.context["rows"]],[self.row.pk])

    def test_schedule_labels_and_help_explain_actual_rules(self):
        self.client.force_login(self.owner)
        response=self.client.get(reverse("portal-resource-edit",args=["agenda","configuracao",self.tenant.pk]))
        self.assertContains(response,"Passo dos horários disponíveis (minutos)")
        self.assertContains(response,"Pausa entre atendimentos (minutos)")
        self.assertContains(response,"09:00, 09:15 e 09:30")
        self.assertContains(response,"antes e depois")

    def test_arena_seed_declares_unlimited_and_preserves_master_choices(self):
        call_command("seed_sales_plans",stdout=StringIO())
        plan=Plan.objects.get(slug="segment-arena")
        self.assertEqual(plan.features["courts"],0)
        self.assertEqual(plan.features["reservations"],0)
        response=self.client.get(reverse("billing-plans"))
        rows={r["label"]:r["values"] for r in response.context["comparison"]}
        self.assertIn("Sem limite",rows["Quadras"])
        plan.features.update(courts=2,reservations=100,custom="preserve")
        plan.save()
        call_command("seed_sales_plans",stdout=StringIO())
        plan.refresh_from_db()
        self.assertEqual(plan.features["courts"],2)
        self.assertEqual(plan.features["reservations"],100)
        self.assertEqual(plan.features["custom"],"preserve")
        data={"name":plan.name,"slug":plan.slug,"monthly_price":"49.90","trial_days":7,
            "sort_order":2,"segments":["arena"],"courts_limit":0,"reservations_limit":200,"units_limit":1}
        form=PlanMasterForm(data,instance=plan)
        self.assertTrue(form.is_valid(),form.errors)
        form.save()
        self.assertEqual(plan.features["courts"],0)
        self.assertEqual(plan.features["reservations"],200)
        self.assertEqual(plan.features["custom"],"preserve")
