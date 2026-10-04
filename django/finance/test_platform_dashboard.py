from datetime import timedelta
from decimal import Decimal
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from tenants.models import Tenant
from billing.models import Payment, Plan, Subscription
from .models import PlatformFinancialTransaction as Entry
from .platform_dashboard import platform_totals


@override_settings(SUBSCRIPTION_ACCESS_ENFORCED=False)
class PlatformDashboardTests(TestCase):
    def setUp(self):
        self.now=timezone.now()
        self.today=timezone.localdate()
        self.master=User.objects.create_user(email='master@finance.test',role='master',is_superuser=True)
        self.tenant=Tenant.objects.create(name='Empresa',slug='finance-master')
        self.owner=User.objects.create_user(email='owner@finance.test',role='owner',tenant=self.tenant)
        plan=Plan.objects.create(name='Plano',slug='finance-master-plan',monthly_price=100)
        self.sub=Subscription.objects.create(tenant=self.tenant,plan=plan,status='active',started_at=self.now)
        for status,environment,purpose,amount in [('paid','production','subscription',100),
                ('pending','production','subscription',50),('paid','sandbox','subscription',900),
                ('refunded','production','subscription',700),('failed','production','subscription',600),
                ('paid','production','appointment',500)]:
            Payment.objects.create(tenant=self.tenant,subscription=self.sub,status=status,environment=environment,
                purpose=purpose,amount=amount,paid_at=self.now if status=='paid' else None,due_at=self.now)
        for kind,status,amount in [('expense','paid',20),('expense','pending',10),
                ('expense','cancelled',800),('income','paid',5)]:
            Entry.objects.create(type=kind,status=status,amount=amount,description=kind,
                due_at=self.today,paid_at=self.now if status=='paid' else None)

    def test_realized_and_forecast_use_only_relevant_money(self):
        totals=platform_totals(self.today,self.today)
        self.assertEqual(totals['gross'],Decimal('105'))
        self.assertEqual(totals['net'],Decimal('85'))
        self.assertEqual(totals['forecast'],Decimal('125'))
        self.assertEqual(totals['receivable'],Decimal('50'))
        self.assertEqual(totals['payable'],Decimal('10'))

    def test_paid_date_controls_period_and_negative_result_is_visible(self):
        Entry.objects.create(type='expense',status='paid',amount=200,description='Infra',paid_at=self.now)
        self.assertEqual(platform_totals(self.today,self.today)['net'],Decimal('-115'))
        self.assertEqual(platform_totals(self.today+timedelta(days=1),self.today+timedelta(days=1))['gross'],0)

    def test_dashboard_is_master_only_and_bad_period_has_feedback(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('master-finance-dashboard')).status_code,403)
        self.client.force_login(self.master)
        response=self.client.get(reverse('master-finance-dashboard'))
        self.assertContains(response,'Lucro líquido realizado')
        response=self.client.get(reverse('master-finance-dashboard'),{'start':'2026-10-31','end':'2026-10-01'})
        self.assertContains(response,'A data final deve ser')

    def test_expense_registration_sets_type_paid_date_and_author(self):
        self.client.force_login(self.master)
        response=self.client.post(reverse('master-resource-create',args=['despesas']),
            {'description':'Servidor','amount':'35.50','status':'paid','due_at':str(self.today),'notes':'Hospedagem'})
        self.assertEqual(response.status_code,302)
        row=Entry.objects.get(description='Servidor')
        self.assertEqual(row.type,'expense')
        self.assertEqual(row.created_by,self.master)
        self.assertIsNotNone(row.paid_at)
        response=self.client.get(reverse('master-resource-list',args=['despesas']))
        self.assertContains(response,'Servidor')
        self.assertNotContains(response,'<td>income</td>')

    def test_invalid_expense_does_not_enter_results(self):
        self.client.force_login(self.master)
        response=self.client.post(reverse('master-resource-create',args=['despesas']),
            {'description':'Inválida','amount':'-1','status':'paid'})
        self.assertContains(response,'Informe um valor maior que zero')
        self.assertFalse(Entry.objects.filter(description='Inválida').exists())
        income=Entry.objects.filter(type='income').first()
        self.assertEqual(self.client.get(reverse('master-resource-edit',args=['despesas',income.pk])).status_code,403)
