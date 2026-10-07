from datetime import timedelta
from django.test import TestCase,Client
from django.urls import reverse
from django.utils import timezone
from django.forms import modelform_factory
from accounts.models import User
from tenants.models import Tenant,Unit
from scheduling.models import Appointment,Customer,Service,Professional
from core.models import AuditLog

class SimpleModeTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name='Barbearia Fácil',slug='barbearia-facil',category='barbearia',status='active')
        self.other=Tenant.objects.create(name='Outra empresa',slug='outra-empresa',status='active')
        self.owner=User.objects.create_user(email='simples@example.test',password='StrongPassword123!',tenant=self.tenant,role='owner')
        self.master=User.objects.create_superuser(email='master-simple@example.test',password='StrongPassword123!')
        self.url=reverse('master-company-simple-mode',args=[self.tenant.pk])
    def test_only_master_can_enable_and_change_is_audited_idempotently(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(self.url,{'action':'enable'}).status_code,403)
        self.tenant.refresh_from_db();self.assertFalse(self.tenant.simple_mode)
        self.client.force_login(self.master)
        self.assertEqual(self.client.get(self.url).status_code,405)
        self.assertEqual(self.client.post(self.url,{'action':'toggle'}).status_code,400)
        self.assertEqual(self.client.post(self.url,{'action':'enable'}).status_code,302)
        self.client.post(self.url,{'action':'enable'})
        self.tenant.refresh_from_db();self.assertTrue(self.tenant.simple_mode)
        self.assertEqual(AuditLog.objects.filter(action='MASTER_COMPANY_SIMPLE_MODE',tenant=self.tenant).count(),1)
        self.other.refresh_from_db();self.assertFalse(self.other.simple_mode)
        self.client.post(self.url,{'action':'disable','destination':'detail'})
        self.tenant.refresh_from_db();self.assertFalse(self.tenant.simple_mode)
    def test_csrf_required(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.master)
        self.assertEqual(client.post(self.url,{'action':'enable'}).status_code,403)
    def test_default_dashboard_and_master_button(self):
        self.client.force_login(self.owner)
        response=self.client.get(reverse('portal-home'))
        self.assertTemplateUsed(response,'portal/home.html')
        self.assertNotContains(response,'class="simple-primary-nav"')
        self.client.force_login(self.master)
        self.assertContains(self.client.get(reverse('master-resource-list',args=['empresas'])),'Simple Mode')
        self.assertContains(self.client.get(reverse('master-company-detail',args=[self.tenant.pk])),'Ativar Simple Mode')
    def test_company_cannot_change_field_through_regular_model_form(self):
        form=modelform_factory(Tenant,fields='__all__')
        self.assertNotIn('simple_mode',form.base_fields)
    def enable(self):
        self.tenant.simple_mode=True;self.tenant.save(update_fields=['simple_mode'])
        self.client.force_login(self.owner)
    def test_simple_dashboard_and_all_tools_are_available(self):
        self.enable();response=self.client.get(reverse('portal-home'))
        self.assertTemplateUsed(response,'portal/simple_home.html')
        for text in ['Vamos organizar seu dia?','Novo agendamento','Clientes','Minha equipe','Outras ferramentas e configurações','Mais opções']:
            self.assertContains(response,text)
        self.assertNotContains(response,'portal-view-toggle')
        response=self.client.get(reverse('portal-resource-create',args=['agenda','clientes']))
        self.assertContains(response,'simple-mode.css');self.assertContains(response,'Preencha os dados abaixo')
    def test_mode_does_not_leak_to_other_company_or_public_pages(self):
        self.enable();self.tenant.public_enabled=True;self.tenant.save(update_fields=['public_enabled'])
        self.assertNotContains(self.client.get(reverse('tenant-public',args=[self.tenant.slug])),'simple-mode.css')
        another=User.objects.create_user(email='outro-simple@example.test',password='StrongPassword123!',tenant=self.other,role='owner')
        self.client.force_login(another)
        self.assertTemplateUsed(self.client.get(reverse('portal-home')),'portal/home.html')
        other_customer=Customer.objects.create(tenant=self.other,name='Cliente externo')
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('portal-resource-edit',args=['agenda','clientes',other_customer.pk])).status_code,404)
    def test_day_summary_respects_selected_unit(self):
        self.enable()
        unit=Unit.objects.create(tenant=self.tenant,name='Centro',is_primary=True)
        second=Unit.objects.create(tenant=self.tenant,name='Filial')
        customer=Customer.objects.create(tenant=self.tenant,name='Ana')
        for location in [unit,second]:
            professional=Professional.objects.create(tenant=self.tenant,unit=location,name=location.name)
            service=Service.objects.create(tenant=self.tenant,unit=location,name='Corte',price=30,duration_minutes=30)
            start=timezone.now()
            Appointment.objects.create(tenant=self.tenant,unit=location,customer=customer,professional=professional,service=service,starts_at=start,ends_at=start+timedelta(minutes=30),status='confirmed')
        response=self.client.get(reverse('portal-home'),{'unit':unit.pk})
        self.assertEqual(response.context['simple_total'],1)
        self.assertEqual(response.context['simple_rows'][0].unit_id,unit.pk)
    def test_archived_company_cannot_be_changed(self):
        self.tenant.archived_at=timezone.now();self.tenant.save(update_fields=['archived_at'])
        self.client.force_login(self.master);self.assertEqual(self.client.post(self.url,{'action':'enable'}).status_code,404)
    def test_master_can_preview_but_master_area_keeps_original_layout(self):
        self.enable();self.client.force_login(self.master)
        self.client.get(reverse('portal-select-tenant',args=[self.tenant.pk]))
        self.assertTemplateUsed(self.client.get(reverse('portal-home')),'portal/simple_home.html')
        self.assertNotContains(self.client.get(reverse('master-home')),'simple-mode.css')
