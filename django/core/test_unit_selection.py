from datetime import datetime,time,timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase,RequestFactory
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.branding import UnitBrandingForm
from core.unit_settings import UnitScheduleForm
from scheduling.availability import AvailabilityService
from scheduling.models import Professional,ProfessionalAvailability,Service,TenantScheduleSettings
from tenants.models import Tenant,Unit,UnitBusinessHours


class UnitSelectionTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name='Rede',slug='rede',public_enabled=True,status='active')
        self.first=Unit.objects.create(tenant=self.tenant,name='Centro',is_primary=True,latitude=-7.85,longitude=-35.25)
        self.second=Unit.objects.create(tenant=self.tenant,name='Bairro',latitude=-7.86,longitude=-35.26,
                                      public_settings={'public_headline':'Página do Bairro','primary_color':'#112233'})
        self.far=Unit.objects.create(tenant=self.tenant,name='Distante',latitude=-9,longitude=-35)
        self.unknown=Unit.objects.create(tenant=self.tenant,name='Sem coordenadas')
        self.a=Professional.objects.create(tenant=self.tenant,unit=self.first,name='Equipe Centro',public_slug='centro')
        self.b=Professional.objects.create(tenant=self.tenant,unit=self.second,name='Equipe Bairro',public_slug='bairro')
        self.service=Service.objects.create(tenant=self.tenant,name='Compartilhado',duration_minutes=30,price=20)
        self.local=Service.objects.create(tenant=self.tenant,unit=self.second,name='Exclusivo Bairro',duration_minutes=30,price=20)
        self.owner=User.objects.create_user(email='units@example.test',password='ValidPassword2026!',tenant=self.tenant,role='owner')

    def test_explore_contains_both_nearby_units_excludes_distant_and_unknown(self):
        response=self.client.get(reverse('public-directory'),{'lat':-7.85,'lon':-35.25})
        self.assertEqual(len(response.context['cards']),2)
        self.assertEqual(response.context['cards'][0]['unit'],self.first)
        self.assertContains(response,'0,0 km')
        self.assertNotContains(response,'Distante')
        self.assertNotContains(response,'Sem coordenadas')

    def test_invalid_coordinates_do_not_crash_or_claim_distance(self):
        for value in ('nan','inf','91','texto'):
            response=self.client.get(reverse('public-directory'),{'lat':value,'lon':0})
            self.assertEqual(response.status_code,200)
            self.assertFalse(response.context['located'])

    def test_selected_public_unit_has_only_its_professionals_services_and_branding(self):
        response=self.client.get(reverse('tenant-public',args=['rede']),{'unit':self.second.pk})
        self.assertContains(response,'Página do Bairro')
        self.assertContains(response,'Equipe Bairro')
        self.assertNotContains(response,'Equipe Centro')
        self.assertContains(response,'Exclusivo Bairro')
        other=self.client.get(reverse('tenant-public',args=['rede']),{'unit':self.first.pk})
        self.assertNotContains(other,'Exclusivo Bairro')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.public_headline,'')

    def test_title_and_description_do_not_contain_scripts(self):
        response=self.client.get(reverse('tenant-public',args=['rede']))
        html=response.content.decode()
        self.assertNotIn('<script>',html.split('</head>')[0])

    def test_service_from_other_unit_is_rejected(self):
        availability=AvailabilityService()
        self.assertFalse(availability.professional_offers(self.tenant,self.a.pk,self.local.pk))
        self.assertTrue(availability.professional_offers(self.tenant,self.b.pk,self.local.pk))

    def test_operation_selection_persists_and_edit_is_scoped(self):
        self.client.force_login(self.owner)
        url=reverse('portal-resource-list',args=['agenda','profissionais'])
        response=self.client.get(url,{'unit':self.second.pk})
        self.assertContains(response,'Equipe Bairro')
        self.assertNotContains(response,'Equipe Centro')
        self.assertNotContains(self.client.get(url),'Equipe Centro')
        self.assertEqual(self.client.get(reverse('portal-resource-edit',args=['agenda','profissionais',self.a.pk])).status_code,404)
        response=self.client.get(reverse('portal-resource-create',args=['agenda','profissionais']))
        self.assertEqual(list(response.context['form'].fields['unit'].queryset),[self.second])

    def test_foreign_unit_selection_is_rejected(self):
        other=Tenant.objects.create(name='Outra empresa',slug='outra')
        unit=Unit.objects.create(tenant=other,name='Privada')
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('tenant-branding'),{'unit':unit.pk}).status_code,404)
        self.assertEqual(self.client.get(reverse('portal-home'),{'unit':unit.pk}).status_code,404)

    def test_branding_saved_to_selected_unit_only(self):
        self.client.force_login(self.owner)
        response=self.client.post(reverse('tenant-branding')+f'?unit={self.second.pk}',{
            'unit':self.second.pk,'public_headline':'Nova capa Bairro','description':'Apresentação própria',
            'primary_color':'#224466','background_color':'#ffffff','text_color':'#111111',
            'amenities':'["Wi-Fi"]','payment_methods':'["Pix"]'})
        self.assertEqual(response.status_code,302)
        self.second.refresh_from_db();self.first.refresh_from_db();self.tenant.refresh_from_db()
        self.assertEqual(self.second.public_settings['public_headline'],'Nova capa Bairro')
        self.assertEqual(self.second.amenities,['Wi-Fi'])
        self.assertEqual(self.first.public_settings,{})
        self.assertEqual(self.tenant.public_headline,'')

    def test_agenda_config_keeps_other_unit_and_company_payment_settings(self):
        self.client.force_login(self.owner)
        company=TenantScheduleSettings.objects.create(tenant=self.tenant,minimum_notice_minutes=30,allow_partial_payment=True)
        response=self.client.post(reverse('unit-schedule-settings')+f'?unit={self.second.pk}',{
            'minimum_notice_minutes':120,'maximum_days_ahead':15,'slot_interval_minutes':30,
            'buffer_minutes':5,'cancel_notice_minutes':60,'customer_can_cancel':'on','reminder_2h_enabled':'on'})
        self.assertEqual(response.status_code,302)
        self.second.refresh_from_db()
        config=AvailabilityService()
        self.assertEqual(config.settings(self.tenant,self.second).minimum_notice_minutes,120)
        self.assertEqual(config.settings(self.tenant,self.first).minimum_notice_minutes,30)
        self.assertTrue(config.settings(self.tenant,self.second).allow_partial_payment)
        company.refresh_from_db();self.assertEqual(company.minimum_notice_minutes,30)

    def test_business_hours_restrict_professional_availability(self):
        tz=ZoneInfo(self.tenant.timezone)
        start=(timezone.now().astimezone(tz)+timedelta(days=2)).replace(hour=10,minute=0,second=0,microsecond=0)
        ProfessionalAvailability.objects.create(tenant=self.tenant,professional=self.a,weekday=start.isoweekday(),start_time=time(8),end_time=time(18))
        UnitBusinessHours.objects.create(tenant=self.tenant,unit=self.first,weekday=start.isoweekday(),opens_at=time(12),closes_at=time(18))
        availability=AvailabilityService()
        self.assertFalse(availability.is_available(self.tenant,self.a,start,start+timedelta(minutes=30)))
        start=start.replace(hour=13)
        self.assertTrue(availability.is_available(self.tenant,self.a,start,start+timedelta(minutes=30)))

    def test_creating_service_does_not_change_another_units_professional_links(self):
        self.client.force_login(self.owner)
        response=self.client.post(reverse('portal-resource-create',args=['agenda','servicos'])+f'?unit={self.second.pk}',{
            'unit':self.second.pk,'name':'Novo serviço Bairro','duration_minutes':30,'price':25,
            'active':'on','service_selection':'on','offering_professionals':[self.b.pk]})
        self.assertEqual(response.status_code,302,response.context['form'].errors if response.status_code==200 else None)
        self.a.refresh_from_db()
        self.assertFalse(self.a.services_restricted)
        self.assertFalse(self.a.services.exists())
        created=Service.objects.get(name='Novo serviço Bairro')
        self.assertEqual(created.unit_id,self.second.pk)
        self.assertTrue(self.b.services.filter(pk=created.pk).exists())
