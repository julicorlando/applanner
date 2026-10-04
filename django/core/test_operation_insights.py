from datetime import datetime,time,timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo
from django.test import TestCase,override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from tenants.models import Tenant,Unit
from billing.models import Plan,Subscription,Payment,Module,TenantModule,PaymentGateway
from scheduling.models import Customer,Service,Professional,ProfessionalAvailability,ProfessionalBreak,Appointment
from finance.platform_dashboard import platform_totals
from core.operation_insights import utilization,performance_rows
from core.master_retention import retention_metrics
from billing.platform_accounting import capture_accounting,reconcile_financial_payment
from core.models import AuditLog

@override_settings(SUBSCRIPTION_ACCESS_ENFORCED=False)
class ImprovementsTests(TestCase):
    def setUp(self):
        self.now=timezone.now();self.day=self.now.astimezone(ZoneInfo('America/Recife')).date()
        self.company=Tenant.objects.create(name='Empresa',slug='insights',timezone='America/Recife',public_enabled=True)
        self.unit=Unit.objects.create(tenant=self.company,name='A',is_primary=True)
        self.other=Unit.objects.create(tenant=self.company,name='B')
        self.owner=User.objects.create_user(email='owner@insights.test',tenant=self.company,role='owner')
        self.master=User.objects.create_superuser(email='master@insights.test',password='ExampleSynthetic123!')
        self.client.force_login(self.owner)
        self.customer=Customer.objects.create(tenant=self.company,name='Cliente')
        self.service=Service.objects.create(tenant=self.company,name='Corte',duration_minutes=30,price=50)
        self.pro=Professional.objects.create(tenant=self.company,unit=self.unit,name='Ana')
        self.plan=Plan.objects.create(name='Inicial',slug='insights-plan',monthly_price=100)
        self.sub=Subscription.objects.create(tenant=self.company,plan=self.plan,status='active',started_at=self.now,trial_started_at=self.now-timedelta(days=5),contracted_price=100)
        self.start=datetime.combine(self.day,time(9),ZoneInfo('America/Recife'))
        self.app=Appointment.objects.create(tenant=self.company,unit=self.unit,professional=self.pro,service=self.service,customer=self.customer,
            starts_at=self.start,ends_at=self.start+timedelta(minutes=30),status='confirmed')
        self.payment=Payment.objects.create(tenant=self.company,subscription=self.sub,amount=100,status='paid',paid_at=self.now,provider='mercadopago',
            environment='production',provider_reference='ref',provider_payment_id='123')

    def remote(self,**extra):
        return {'id':123,'currency_id':'BRL','transaction_amount':100,'external_reference':'ref','live_mode':True,'status':'approved',
            'fee_details':[{'amount':'3'}],'transaction_details':{'net_received_amount':'97'},**extra}

    def test_today_and_history_render_and_do_not_leak_other_company(self):
        response=self.client.get(reverse('operation-today'))
        self.assertContains(response,'Cliente');self.assertContains(response,'Ana')
        outsider=Tenant.objects.create(name='Outra',slug='out-insights')
        c=Customer.objects.create(tenant=outsider,name='Segredo')
        self.assertEqual(self.client.get(reverse('customer-history',args=[c.pk])).status_code,404)
        self.assertEqual(self.client.post(reverse('customer-history',args=[c.pk]),{'preferences':'x'}).status_code,404)
        self.assertEqual(self.client.get(reverse('operation-today'),{'unit':Unit.objects.create(tenant=outsider,name='C').pk}).status_code,404)
        self.assertEqual(self.client.get(reverse('customer-history',args=[self.customer.pk])).status_code,200)

    def test_preferences_save_and_are_audited(self):
        self.client.post(reverse('customer-history',args=[self.customer.pk]),{'preferences':'Prefere tesoura'})
        self.customer.refresh_from_db();self.assertEqual(self.customer.preferences,'Prefere tesoura')
        self.assertTrue(AuditLog.objects.filter(tenant=self.company,action='CUSTOMER_PREFERENCES_UPDATED').exists())
        self.client.post(reverse('customer-history',args=[self.customer.pk]),{'preferences':'x'*1001})
        self.customer.refresh_from_db();self.assertEqual(self.customer.preferences,'Prefere tesoura')

    def test_actions_obey_selected_unit_terminal_states_and_financial_idempotency(self):
        url=reverse('operation-today-action',args=[self.app.pk])
        self.assertEqual(self.client.get(url).status_code,405)
        self.client.post(url,{'action':'check_in'})
        self.app.refresh_from_db();self.assertEqual(self.app.status,'waiting')
        self.app.starts_at=self.now-timedelta(hours=1);self.app.ends_at=self.now-timedelta(minutes=30);self.app.save()
        self.client.post(url,{'action':'start'})
        self.app.refresh_from_db();self.assertEqual(self.app.status,'in_progress')
        with patch('communications.tasks.process_notification_queue.delay'):
            self.client.post(url,{'action':'complete','payment_method':'cash'})
            self.client.post(url,{'action':'complete','payment_method':'cash'})
        self.app.refresh_from_db();self.assertEqual(self.app.status,'completed')
        from scheduling.models import AppointmentSettlement
        self.assertEqual(AppointmentSettlement.objects.filter(appointment=self.app).count(),1)
        self.client.get(reverse('operation-today'),{'unit':self.other.pk})
        self.assertEqual(self.client.post(url,{'action':'start'}).status_code,404)

    def test_start_cannot_precede_booked_time_and_invalid_payment_cannot_settle(self):
        self.app.starts_at=self.now+timedelta(hours=1);self.app.ends_at=self.now+timedelta(hours=2);self.app.save()
        self.client.post(reverse('operation-today-action',args=[self.app.pk]),{'action':'start'})
        self.app.refresh_from_db();self.assertEqual(self.app.status,'confirmed')
        self.client.post(reverse('operation-today-action',args=[self.app.pk]),{'action':'complete','payment_method':'fake'})
        self.app.refresh_from_db();self.assertEqual(self.app.status,'confirmed')

    def test_reception_can_use_today_but_cannot_view_management_indicators(self):
        self.owner.role='reception';self.owner.save()
        self.assertEqual(self.client.get(reverse('operation-today')).status_code,200)
        self.client.post(reverse('operation-today-action',args=[self.app.pk]),{'action':'check_in'})
        self.app.refresh_from_db();self.assertEqual(self.app.status,'waiting')
        self.assertEqual(self.client.get(reverse('operation-performance')).status_code,403)

    def test_utilization_subtracts_break_and_does_not_double_count_overlap(self):
        ProfessionalAvailability.objects.create(tenant=self.company,professional=self.pro,weekday=self.day.isoweekday(),start_time=time(9),end_time=time(12))
        ProfessionalBreak.objects.create(tenant=self.company,professional=self.pro,weekday=self.day.isoweekday(),start_time=time(10),end_time=time(11))
        self.app.ends_at=self.start+timedelta(hours=2);self.app.save()
        duplicate=Appointment(tenant=self.company,professional=self.pro,starts_at=self.start+timedelta(minutes=15),ends_at=self.start+timedelta(hours=1),status='confirmed')
        metrics=utilization(self.company,self.pro,self.day,self.day,[self.app,duplicate])
        self.assertEqual(metrics['capacity'],2);self.assertEqual(metrics['occupied'],1);self.assertEqual(metrics['occupancy'],50)
        self.assertEqual(self.client.get(reverse('operation-performance')).status_code,200)

    def test_return_rate_and_ticket_use_completed_visits_only(self):
        self.app.status='completed';self.app.service_price_snapshot=60;self.app.save()
        Appointment.objects.create(tenant=self.company,unit=self.unit,professional=self.pro,service=self.service,customer=self.customer,
            starts_at=self.start-timedelta(days=1),ends_at=self.start-timedelta(days=1)+timedelta(minutes=30),status='completed')
        row=performance_rows(self.company,[self.pro],self.day,self.day)[0]
        self.assertEqual(row['ticket'],60);self.assertEqual(row['return_rate'],100)
        self.assertEqual(self.client.get(reverse('operation-performance'),{'start':'2020-01-01','end':'2026-01-01'}).status_code,200)

    def test_finance_snapshots_are_idempotent_and_refunds_deducted(self):
        self.assertTrue(capture_accounting(self.payment,self.remote()))
        self.payment.save()
        capture_accounting(self.payment,self.remote());self.payment.save()
        totals=platform_totals(timezone.localdate(),timezone.localdate())
        self.assertEqual(totals['gross'],100);self.assertEqual(totals['provider_fees'],3);self.assertEqual(totals['net'],97)
        capture_accounting(self.payment,self.remote(status='partially_refunded',transaction_amount_refunded=20));self.payment.status='partially_refunded';self.payment.save()
        totals=platform_totals(timezone.localdate(),timezone.localdate())
        self.assertEqual(totals['refunds'],20);self.assertEqual(totals['net'],77)

    def test_accounting_rejects_currency_environment_reference_amount_and_nonfinite_values(self):
        for change in [{'currency_id':'USD'},{'live_mode':False},{'external_reference':'foreign'},{'transaction_amount':101},
                       {'fee_details':[{'amount':'NaN'}]},{'transaction_amount_refunded':101}]:
            with self.subTest(change=change),self.assertRaises(ValueError):capture_accounting(self.payment,self.remote(**change))
        self.assertNotIn('accounting',self.payment.metadata)

    def test_missing_provider_fields_do_not_estimate_fees(self):
        remote=self.remote();remote.pop('fee_details');remote.pop('transaction_details')
        capture_accounting(self.payment,remote);self.payment.save()
        totals=platform_totals(timezone.localdate(),timezone.localdate())
        self.assertEqual(totals['unreconciled_count'],1)

    def test_financial_refresh_preserves_original_payment_date_and_confirmed_refund(self):
        PaymentGateway.objects.create(provider='mercadopago',environment='production',active=True,last_test_status='validated')
        with patch('billing.payment_services.platform_provider') as provider:
            provider.return_value.get_payment.return_value=self.remote(status='refunded')
            self.assertTrue(reconcile_financial_payment(self.payment.pk))
        self.payment.refresh_from_db();self.assertEqual(self.payment.status,'refunded');self.assertEqual(self.payment.paid_at,self.now)

    def test_conversion_ignores_sandbox_and_counts_trial_once(self):
        Subscription.objects.create(tenant=self.company,plan=self.plan,status='trial',started_at=self.now-timedelta(days=1),trial_started_at=self.now-timedelta(days=1))
        data=retention_metrics(self.day-timedelta(days=10),self.day)
        self.assertEqual(data['trials'],1);self.assertEqual(data['converted'],1)
        self.payment.environment='sandbox';self.payment.save()
        self.assertEqual(retention_metrics(self.day-timedelta(days=10),self.day)['converted'],0)
        self.client.force_login(self.master)
        self.assertEqual(self.client.get(reverse('master-retention')).status_code,200)
        self.client.post(reverse('master-retention-note',args=[self.company.pk]),{'reason':'price','notes':'Custo'})
        self.assertTrue(AuditLog.objects.filter(action='MASTER_RETENTION_UPDATED').exists())

    def test_platform_role_route_matrix_and_login_destination(self):
        from accounts.master_access import PLATFORM_ROLES
        for role,(_,destination) in PLATFORM_ROLES.items():
            operator=User.objects.create_user(email=f'{role}@insights.test',role=role,is_staff=True)
            self.client.force_login(operator)
            self.assertRedirects(self.client.get('/'),reverse(destination),fetch_redirect_response=False)
            self.assertEqual(self.client.get(reverse(destination)).status_code,200)
            for url in ['/admin/','/app/','/api/scheduling/appointments/',reverse('master-resource-list',args=['usuarios']),
                        reverse('master-company-lifecycle',args=[self.company.pk,'delete'])]:
                self.assertEqual(self.client.get(url).status_code,403,(role,url))
            self.assertEqual(self.client.post(reverse('master-resource-create',args=['usuarios']),{}).status_code,403)
        self.client.force_login(User.objects.get(role='master-finance'))
        self.assertEqual(self.client.get(reverse('master-resource-create',args=['despesas'])).status_code,200)
        self.assertEqual(self.client.post(reverse('master-retention-note',args=[self.company.pk]),{'reason':'price'}).status_code,403)

    def test_checklist_highlights_each_professional_and_location(self):
        response=self.client.get(reverse('portal-setup'))
        self.assertContains(response,'Ana: horário de atendimento não cadastrado')
        self.assertContains(response,'coordenadas para o Explorar')

    def test_linked_manual_fee_is_deducted_once_after_provider_confirmation(self):
        from finance.models import PlatformFinancialTransaction
        cost=PlatformFinancialTransaction.objects.create(type='expense',status='paid',amount=3,description='Taxa',paid_at=self.now,provider_fee_payment=self.payment)
        self.assertEqual(platform_totals(timezone.localdate(),timezone.localdate())['net'],97)
        capture_accounting(self.payment,self.remote());self.payment.save()
        totals=platform_totals(timezone.localdate(),timezone.localdate())
        self.assertEqual(totals['net'],97);self.assertEqual(totals['expenses'],0)
        self.client.force_login(self.master)
        self.assertEqual(self.client.get(reverse('master-resource-edit',args=['despesas',cost.pk])).status_code,200)
        response=self.client.post(reverse('master-resource-edit',args=['despesas',cost.pk]),{'description':'Taxa','amount':'3','status':'paid','provider_fee_payment':self.payment.pk})
        self.assertEqual(response.status_code,302)

    def test_arena_today_and_indicators_use_courts_and_unit(self):
        from arena.models import Court,CourtHours,Reservation
        self.company.category='Arena';self.company.save()
        module=Module.objects.create(name='Quadras',slug='sports_courts')
        TenantModule.objects.create(tenant=self.company,module=module,enabled=True)
        court=Court.objects.create(tenant=self.company,unit=self.unit,name='Quadra Azul',slug='azul')
        CourtHours.objects.create(tenant=self.company,court=court,weekday=self.day.isoweekday(),start_time=time(8),end_time=time(12))
        Reservation.objects.create(tenant=self.company,court=court,customer=self.customer,customer_name='Jogador',customer_phone='5581999999999',
            starts_at=self.start,ends_at=self.start+timedelta(hours=1),duration_minutes=60,price_per_hour=80,total_amount=80,public_id='insights-arena',manage_token_hash='test-hash',status='confirmed')
        self.assertContains(self.client.get(reverse('operation-today')),'Quadra Azul')
        self.assertContains(self.client.get(reverse('operation-performance')),'Quadra Azul')
        self.assertNotContains(self.client.get(reverse('operation-today'),{'unit':self.other.pk}),'Quadra Azul')

    def test_limited_master_cannot_hold_a_tenant_or_superuser_profile(self):
        from core.master import UserMasterForm
        operator=User.objects.create_user(email='invalid-master@insights.test',tenant=self.company,role='master-finance',is_staff=True)
        self.client.force_login(operator)
        self.assertEqual(self.client.get(reverse('master-finance-dashboard')).status_code,403)
        form=UserMasterForm({'email':self.master.email,'role':'master-finance','is_staff':'on','is_active':'on'},instance=self.master)
        self.assertFalse(form.is_valid());self.assertIn('role',form.errors)

    def test_stale_provider_response_cannot_undo_confirmed_refund(self):
        capture_accounting(self.payment,self.remote(status='partially_refunded',transaction_amount_refunded=20))
        self.payment.status='partially_refunded';self.payment.save()
        with self.assertRaises(ValueError):capture_accounting(self.payment,self.remote())
        self.assertEqual(self.payment.metadata['accounting']['refunded'],'20')

    def test_master_financial_consult_is_audited_without_exposing_provider_errors(self):
        self.client.force_login(self.master)
        with patch('billing.platform_accounting.reconcile_financial_payment',side_effect=RuntimeError('private-provider-token')):
            response=self.client.post(reverse('master-financial-consult',args=[self.payment.pk]),follow=True)
        self.assertNotContains(response,'private-provider-token')
        self.assertTrue(AuditLog.objects.filter(action='MASTER_FINANCIAL_RECONCILIATION').exists())
