from datetime import timedelta,time
from django.test import TestCase,override_settings,Client
from django.urls import reverse
from django.templatetags.static import static
from django.utils import timezone
from accounts.models import User
from tenants.models import Tenant,Unit,UnitBusinessHours
from scheduling.models import Professional,ProfessionalAvailability,Service
from billing.models import Plan,Subscription,Payment
from core.activation import activation_status
from core.booking_funnel import record
from core.models import BookingFunnelEvent
from core.master_console import activation_rows,unreleased_payments

@override_settings(SUBSCRIPTION_ACCESS_ENFORCED=False)
class ActivationFunnelTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name='Funil',slug='funnel-test',status='active',public_enabled=True,public_booking_enabled=True)
        self.unit=Unit.objects.create(tenant=self.tenant,name='Centro',address='Rua',address_number='10',city='Recife',state='PE',latitude=-8,longitude=-34)
        self.other=Unit.objects.create(tenant=self.tenant,name='Bairro')
        self.owner=User.objects.create_user(email='funnel-owner@example.test',tenant=self.tenant,role='owner')
        self.client.force_login(self.owner)
        self.professional=Professional.objects.create(tenant=self.tenant,unit=self.unit,name='Ana')
        self.service=Service.objects.create(tenant=self.tenant,unit=self.unit,name='Corte',price=40,duration_minutes=30)
        self.hours=ProfessionalAvailability.objects.create(tenant=self.tenant,professional=self.professional,weekday=1,start_time=time(9),end_time=time(10))
        UnitBusinessHours.objects.create(tenant=self.tenant,unit=self.unit,weekday=1,opens_at=time(8),closes_at=time(18))

    def test_activation_is_per_unit_and_requires_complete_address(self):
        status=activation_status(self.tenant,self.unit)
        self.assertEqual(status['completed'],6)
        self.assertEqual(status['pending'][0]['title'],'Endereço completo e localização')
        Unit.objects.filter(pk=self.unit.pk).update(postal_code='50000000')
        self.unit.refresh_from_db()
        self.assertTrue(activation_status(self.tenant,self.unit)['ready'])
        self.assertFalse(activation_status(self.tenant,self.other)['ready'])
        self.hours.end_time=time(9,15);self.hours.save()
        self.assertFalse(activation_status(self.tenant,self.unit)['steps'][5]['done'])

    def test_home_shows_activation_and_existing_guidance_stays_available(self):
        self.assertContains(self.client.get(reverse('portal-home')),'Ativação')
        self.assertEqual(self.client.get(reverse('portal-setup')).status_code,200)
        self.assertContains(self.client.get(reverse('booking-funnel')),'Funil de agendamento por unidade')

    def token(self):
        response=self.client.get(reverse('tenant-public',args=[self.tenant.slug]),{'unit':self.unit.pk})
        self.assertContains(response,static('js/booking-funnel.js'))
        return response.context['funnel_token']

    def test_visits_and_selections_deduplicate_and_confirmation_cannot_be_forged(self):
        token=self.token();self.token()
        url=reverse('public-booking-funnel',args=[self.tenant.slug])
        for stage in ['resource','slot','slot']:
            self.assertEqual(self.client.post(url,{'token':token,'stage':stage},content_type='application/json').status_code,200)
        self.assertEqual(BookingFunnelEvent.objects.count(),3)
        self.assertEqual(self.client.post(url,{'token':token,'stage':'confirmed'},content_type='application/json').status_code,400)
        self.assertEqual(self.client.post(url,[],content_type='application/json').status_code,400)
        self.assertEqual(self.client.post(url,{'token':'invalid','stage':'slot'},content_type='application/json').status_code,400)

    def test_tokens_do_not_cross_companies_or_deleted_units(self):
        token=self.token()
        tenant=Tenant.objects.create(name='Outra',slug='funnel-other',status='active',public_enabled=True,public_booking_enabled=True)
        self.assertEqual(self.client.post(reverse('public-booking-funnel',args=[tenant.slug]),{'token':token,'stage':'slot'},content_type='application/json').status_code,400)
        self.unit.active=False;self.unit.save()
        self.assertEqual(self.client.post(reverse('public-booking-funnel',args=[self.tenant.slug]),{'token':token,'stage':'slot'},content_type='application/json').status_code,400)

    def test_dashboard_counts_journeys_and_isolates_tenants(self):
        self.token()
        request=self.client.get(reverse('tenant-public',args=[self.tenant.slug])).wsgi_request
        record(request,self.tenant,self.unit,'confirmed');record(request,self.tenant,self.unit,'confirmed')
        request.session.save()
        response=self.client.get(reverse('booking-funnel'))
        row=next(r for r in response.context['rows'] if r['unit']==self.unit)
        self.assertEqual(row['stages'][3]['count'],1)
        self.assertEqual(row['stages'][3]['rate'],100)
        other_tenant=Tenant.objects.create(name='Segredo',slug='funnel-private')
        other_unit=Unit.objects.create(tenant=other_tenant,name='Segredo')
        self.assertEqual(self.client.get(reverse('booking-funnel'),{'unit':other_unit.pk}).status_code,404)
        self.assertNotContains(response,'Segredo')
        self.assertEqual(self.client.get(reverse('booking-funnel'),{'start':'invalid','end':'invalid'}).status_code,200)

    def test_tracking_requires_csrf_and_valid_public_page(self):
        token=self.token()
        client=Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse('public-booking-funnel',args=[self.tenant.slug]),{'token':token,'stage':'slot'},content_type='application/json').status_code,403)
        self.tenant.public_booking_enabled=False;self.tenant.save()
        self.assertEqual(self.client.post(reverse('public-booking-funnel',args=[self.tenant.slug]),{'token':token,'stage':'slot'},content_type='application/json').status_code,404)

    def test_master_alerts_show_pending_units_and_unreleased_paid_access(self):
        plan=Plan.objects.create(name='Plano',slug='funnel-plan',monthly_price=100)
        sub=Subscription.objects.create(tenant=self.tenant,plan=plan,status='active',contracted_price=100,started_at=timezone.now())
        payment=Payment.objects.create(tenant=self.tenant,subscription=sub,purpose='subscription',environment='production',status='paid',amount=100,paid_at=timezone.now())
        self.assertEqual(unreleased_payments(),[])
        self.tenant.status='suspended';self.tenant.save()
        self.assertEqual(unreleased_payments(),[payment])
        self.tenant.status='active';self.tenant.save()
        self.assertTrue(any(r['company']==self.tenant and r['unit']==self.other for r in activation_rows()))
        master=User.objects.create_superuser(email='funnel-master@example.test',password='Synthetic123!')
        self.client.force_login(master)
        self.assertContains(self.client.get(reverse('master-alerts')),'Configuração incompleta por unidade')

    def test_arena_checklist_uses_courts_and_prices(self):
        self.tenant.category='Arena';self.tenant.save()
        status=activation_status(self.tenant,self.unit)
        self.assertIn('Quadras ativas',[s['title'] for s in status['steps']])
        self.assertNotIn('Equipe ativa',[s['title'] for s in status['steps']])

    def test_public_booking_records_conversion_only_after_success_and_replay_is_not_duplicated(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from scheduling.models import TenantScheduleSettings
        day=timezone.localdate()+timedelta(days=2)
        ProfessionalAvailability.objects.get_or_create(tenant=self.tenant,professional=self.professional,weekday=day.isoweekday(),defaults={'start_time':time(9),'end_time':time(10)})
        TenantScheduleSettings.objects.create(tenant=self.tenant,allow_pay_on_site=True)
        self.token()
        url=reverse('public-booking',args=[self.tenant.slug])
        payload={'unit_id':self.unit.pk,'service_id':self.service.pk,'professional_id':self.professional.pk,'starts_at':datetime.combine(day,time(9),ZoneInfo('America/Recife')).isoformat(),'name':'Cliente Teste','phone':'81999999999','payment_choice':'on_site'}
        failed=self.client.post(url,{**payload,'phone':''},content_type='application/json')
        self.assertEqual(failed.status_code,400)
        self.assertFalse(BookingFunnelEvent.objects.filter(stage='confirmed').exists())
        response=self.client.post(url,payload,content_type='application/json',HTTP_IDEMPOTENCY_KEY='funnel-booking-test')
        self.assertEqual(response.status_code,201,response.content)
        self.assertEqual(BookingFunnelEvent.objects.filter(stage='confirmed',unit=self.unit).count(),1)
        replay=self.client.post(url,payload,content_type='application/json',HTTP_IDEMPOTENCY_KEY='funnel-booking-test')
        self.assertEqual(replay.status_code,200,replay.content)
        self.assertEqual(BookingFunnelEvent.objects.filter(stage='confirmed').count(),1)
