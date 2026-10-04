from datetime import time
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils.translation import override

from accounts.models import User
from billing.models import Module, Plan, PlanModule
from core.branding import TenantBrandingForm
from core.portal import PORTAL_MODULES, _model_form, _value
from scheduling.availability import AvailabilityService
from scheduling.models import Professional, ProfessionalAvailability, Service, TenantScheduleSettings
from tenants.models import Tenant


class HomologationImprovementsTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Empresa",slug="melhorias",category="barbearia",
            public_enabled=True,status=Tenant.Status.ACTIVE,onboarding_step=5)
        self.owner=User.objects.create_user(email="owner@improvements.test",tenant=self.tenant,role="owner")
        self.professional=Professional.objects.create(tenant=self.tenant,name="Ana",public_slug="ana")
        self.other=Professional.objects.create(tenant=self.tenant,name="Bia")
        self.service=Service.objects.create(tenant=self.tenant,name="Corte",price=Decimal("40.00"),duration_minutes=30)
        self.previous=Service.objects.create(tenant=self.tenant,name="Barba",price=Decimal("20.00"),duration_minutes=15)
        self.client.force_login(self.owner)

    def service_form(self,professionals):
        return _model_form(Service,PORTAL_MODULES["agenda"]["resources"]["servicos"],
            {"name":"Corte","price":"40.00","duration_minutes":"30","active":"on",
             "service_selection":"True","offering_professionals":professionals},
            tenant=self.tenant,instance=self.service)

    def test_service_assignment_preserves_other_services_and_denies_unselected_professional(self):
        form=self.service_form([self.professional.pk])
        self.assertTrue(form.is_valid(),form.errors)
        form.save()
        availability=AvailabilityService()
        self.assertTrue(availability.professional_offers(self.tenant,self.professional.pk,self.service.pk))
        self.assertFalse(availability.professional_offers(self.tenant,self.other.pk,self.service.pk))
        self.assertTrue(availability.professional_offers(self.tenant,self.other.pk,self.previous.pk))
        self.professional.refresh_from_db()
        self.assertTrue(self.professional.services_restricted)

    def test_explicit_empty_assignment_does_not_mean_all_services(self):
        self.previous.delete()
        form=self.service_form([])
        self.assertTrue(form.is_valid(),form.errors)
        form.save()
        self.assertFalse(AvailabilityService().professional_offers(self.tenant,self.other.pk,self.service.pk))
        response=self.client.get(reverse("professional-public",args=[self.tenant.slug,"ana"]))
        self.assertNotContains(response,f'<option value="{self.service.pk}">')

    def test_assignment_rejects_professional_of_another_tenant(self):
        tenant=Tenant.objects.create(name="Outra",slug="outra-melhoria")
        outsider=Professional.objects.create(tenant=tenant,name="Outro")
        form=self.service_form([outsider.pk])
        self.assertFalse(form.is_valid())
        self.assertIn("offering_professionals",form.errors)

    def test_restricted_professional_without_services_does_not_see_unserviceable_waitlist(self):
        from engagement.models import WaitlistEntry
        from scheduling.models import Customer
        customer=Customer.objects.create(tenant=self.tenant,name="Cliente aguardando")
        WaitlistEntry.objects.create(tenant=self.tenant,customer=customer,service=self.service)
        user=User.objects.create_user(email="restricted@improvements.test",tenant=self.tenant,role="professional")
        self.professional.user=user
        self.professional.services_restricted=True
        self.professional.save()
        self.client.force_login(user)
        response=self.client.get(reverse("professional-area"))
        self.assertEqual(response.context["waiting_count"],0)

    def test_professional_can_select_services_or_keep_legacy_all_services(self):
        resource=PORTAL_MODULES["agenda"]["resources"]["profissionais"]
        data={"name":"Ana","commission_percent":"10","active":"on","service_selection":"True",
              "offered_services":[self.service.pk]}
        form=_model_form(Professional,resource,data,tenant=self.tenant,instance=self.professional)
        self.assertTrue(form.is_valid(),form.errors)
        form.save()
        self.assertFalse(AvailabilityService().professional_offers(self.tenant,self.professional.pk,self.previous.pk))
        data.update(all_services="on",offered_services=[])
        form=_model_form(Professional,resource,data,tenant=self.tenant,instance=self.professional)
        self.assertTrue(form.is_valid(),form.errors)
        form.save()
        self.assertTrue(AvailabilityService().professional_offers(self.tenant,self.professional.pk,self.previous.pk))

    def test_weekday_form_and_list_values_are_human_readable(self):
        availability=ProfessionalAvailability.objects.create(tenant=self.tenant,professional=self.professional,
            weekday=4,start_time=time(9),end_time=time(12))
        form=_model_form(ProfessionalAvailability,PORTAL_MODULES["agenda"]["resources"]["expedientes"],
            tenant=self.tenant,instance=availability)
        self.assertIn((4,"Quinta-feira"),form.fields["weekday"].choices)
        with override("pt-br"):
            self.assertEqual(_value(availability,"start_time"),"09:00")
            self.assertEqual(_value(availability,"weekday"),"Quinta-feira")
            self.assertEqual(_value(self.service,"price"),"R$ 40,00")
        form=_model_form(ProfessionalAvailability,PORTAL_MODULES["agenda"]["resources"]["expedientes"],
            {"professional":self.professional.pk,"weekday":"0","start_time":"12:00","end_time":"09:00"},tenant=self.tenant)
        self.assertFalse(form.is_valid())
        self.assertIn("weekday",form.errors)
        self.assertIn("end_time",form.errors)

    def test_vehicle_fields_only_for_automotive_segment(self):
        resource=PORTAL_MODULES["agenda"]["resources"]["agendamentos"]
        from scheduling.models import Appointment
        form=_model_form(Appointment,resource,tenant=self.tenant)
        self.assertNotIn("vehicle",form.fields)
        response=self.client.get(reverse("portal-resource-list",args=["agenda","agendamentos"]))
        self.assertNotIn("Veículo",response.context["headers"])
        self.tenant.category="Automotivo"
        form=_model_form(Appointment,resource,tenant=self.tenant)
        self.assertIn("vehicle",form.fields)

    def test_setup_requires_permission_and_does_not_count_other_tenants(self):
        self.professional.delete()
        self.other.delete()
        self.service.delete()
        self.previous.delete()
        outsider=Tenant.objects.create(name="Outra empresa",slug="checklist-outra")
        Professional.objects.create(tenant=outsider,name="Equipe alheia")
        response=self.client.get(reverse("portal-setup"))
        self.assertFalse(response.context["steps"][0]["done"])
        user=User.objects.create_user(email="professional@improvements.test",tenant=self.tenant,role="professional")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("portal-setup")).status_code,403)

    def test_setup_is_reusable_and_does_not_reset_onboarding(self):
        response=self.client.get(reverse("portal-setup"))
        self.assertContains(response,"Defina horários de atendimento")
        self.assertContains(response,"3 de 7 etapas")
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.onboarding_step,5)
        self.tenant.category="arena"
        self.tenant.save(update_fields=["category"])
        response=self.client.get(reverse("portal-setup"))
        self.assertContains(response,"Cadastre suas quadras")
        self.assertNotContains(response,"Cadastre sua equipe")

    def test_public_payment_options_require_an_available_online_method(self):
        response=self.client.get(reverse("tenant-public",args=[self.tenant.slug]))
        self.assertNotContains(response,"Como deseja pagar?")
        self.assertNotContains(response,"O Pix só consta")
        settings=TenantScheduleSettings.objects.get(tenant=self.tenant)
        settings.allow_pay_on_site=False
        settings.save()
        response=self.client.get(reverse("tenant-public",args=[self.tenant.slug]))
        self.assertContains(response,"ainda precisa configurar uma forma de pagamento")
        self.assertContains(response,'type="submit" disabled>Confirmar agendamento')

    def test_branding_and_categories_are_portuguese(self):
        form=TenantBrandingForm(instance=self.tenant)
        self.assertEqual(form.fields["public_headline"].label,"Título da página pública")
        self.tenant.category="salao"
        self.assertEqual(self.tenant.category_label,"Salão de beleza")

    def test_plan_comparison_uses_actual_catalog_without_changing_prices(self):
        plan=Plan.objects.create(name="Arena Sports",slug="arena-comparacao",monthly_price=Decimal("99.90"),
            features={"included_features":["Relatórios esportivos"]})
        module=Module.objects.create(name="Quadras e reservas",slug="quadras-comparacao")
        PlanModule.objects.create(plan=plan,module=module)
        Plan.objects.create(name="Arena",slug="arena-basico-comparacao",monthly_price=Decimal("49.90"))
        with override("pt-br"):
            response=self.client.get(reverse("billing-plans"))
        self.assertContains(response,"Compare o que está incluído")
        self.assertContains(response,"99,90")
        self.assertContains(response,"49,90")
        rows={item["label"]:item["values"] for item in response.context["comparison"]}
        self.assertEqual(set(rows["Quadras e reservas"]),{"Incluído","Não incluído"})
        self.assertNotIn("Relatórios esportivos",rows)
        self.assertContains(response,"Relatórios esportivos")
        plan.refresh_from_db()
        self.assertEqual(plan.monthly_price,Decimal("99.90"))
