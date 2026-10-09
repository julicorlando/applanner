from datetime import timedelta
from unittest.mock import patch
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from billing.models import Plan, Subscription, Payment, PaymentGateway, WebhookEvent
from communications.models import Notification
from finance.models import PlatformFinancialTransaction
from operations.models import Backup, CronHeartbeat
from tenants.models import Tenant, Unit
from core.models import AuditLog
from core.master_console import overview, alert_rows


@override_settings(SUBSCRIPTION_ACCESS_ENFORCED=False)
class MasterConsoleTests(TestCase):
    def setUp(self):
        self.now=timezone.now()
        self.master=User.objects.create_superuser(email='master-console@example.test',password='SyntheticPassword123!')
        self.company=Tenant.objects.create(name='Empresa Console',slug='console',status='active',public_enabled=True,public_booking_enabled=True)
        self.owner=User.objects.create_user(email='owner-console@example.test',password='SyntheticPassword123!',tenant=self.company,role='owner')
        self.plan=Plan.objects.create(name='Plano Console',slug='console-plan',monthly_price=100)
        self.sub=Subscription.objects.create(tenant=self.company,plan=self.plan,status='active',started_at=self.now)
        self.payment=Payment.objects.create(tenant=self.company,subscription=self.sub,purpose='subscription',provider='mercadopago',environment='production',amount=100,status='pending',due_at=self.now-timedelta(days=1),provider_reference='console-ref',provider_payment_id='123',metadata={'method':'card_recurring'})
        self.client.force_login(self.master)

    def test_all_six_console_pages_render_and_owner_has_no_access(self):
        urls=[reverse('master-home'),reverse('master-alerts'),reverse('master-charges'),reverse('master-reports'),reverse('master-company-detail',args=[self.company.pk]),reverse('master-charge-detail',args=[self.payment.pk]),reverse('master-company-lifecycle',args=[self.company.pk,'archive'])]
        for url in urls:
            with self.subTest(url=url): self.assertEqual(self.client.get(url).status_code,200)
        self.client.force_login(self.owner)
        for url in urls:
            with self.subTest(url=url): self.assertEqual(self.client.get(url).status_code,403)
        self.assertEqual(self.client.post(reverse('master-charge-consult',args=[self.payment.pk])).status_code,403)
        self.assertEqual(self.client.post(reverse('master-company-lifecycle',args=[self.company.pk,'delete'])).status_code,403)

    def test_overview_ignores_old_subscriptions_deleted_and_archived_companies(self):
        trial=Tenant.objects.create(name='Trial',slug='console-trial',status='trial')
        Subscription.objects.create(tenant=trial,plan=self.plan,status='trial',started_at=self.now,trial_ends_at=self.now+timedelta(days=1))
        Subscription.objects.create(tenant=self.company,plan=self.plan,status='trial',started_at=self.now-timedelta(days=3),trial_ends_at=self.now+timedelta(days=1))
        Tenant.objects.create(name='Deleted',slug='console-deleted',status='active',deleted_at=self.now)
        Tenant.objects.create(name='Archived',slug='console-archived',status='active',archived_at=self.now)
        result=overview()
        self.assertEqual(result['active_companies'],1)
        self.assertEqual(result['ending_trials'],1)
        self.assertEqual(result['overdue_count'],1)

    def test_alerts_detect_backup_failure_notification_and_stale_health(self):
        Notification.objects.create(tenant=self.company,channel='email',status='failed')
        titles=[row['title'] for row in alert_rows()]
        self.assertIn('Notificações com falha',titles)
        self.assertIn('Backup recente indisponível',titles)
        self.assertIn('Sem sinal saudável do processamento automático',titles)
        Backup.objects.create(type='database',status='completed',started_at=self.now,completed_at=self.now,destination='test')
        CronHeartbeat.objects.create(cron_key='platform_health',status='ok',started_at=self.now,finished_at=self.now)
        titles=[row['title'] for row in alert_rows()]
        self.assertNotIn('Backup recente indisponível',titles)
        self.assertNotIn('Sem sinal saudável do processamento automático',titles)
        for row in alert_rows(): self.assertEqual(self.client.get(row['url']).status_code,200)

    def lifecycle(self,action,name=None):
        return self.client.post(reverse('master-company-lifecycle',args=[self.company.pk,action]),{'confirm_name':name or self.company.name,'confirm_impact':'yes'})

    def test_archive_requires_confirmation_and_restores_exact_public_settings(self):
        self.lifecycle('archive','Wrong name')
        self.company.refresh_from_db()
        self.assertIsNone(self.company.archived_at)
        self.assertEqual(self.client.get(reverse('master-company-lifecycle',args=[self.company.pk,'archive'])).status_code,200)
        self.assertIsNone(self.company.archived_at)
        self.lifecycle('archive')
        self.company.refresh_from_db()
        self.assertIsNotNone(self.company.archived_at)
        self.assertFalse(self.company.public_enabled)
        self.assertEqual(self.company.status,'suspended')
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status,'active')
        rows=self.client.get(reverse('master-resource-list',args=['empresas'])).context['rows']
        self.assertFalse(any(row['obj'].pk==self.company.pk for row in rows))
        rows=self.client.get(reverse('master-resource-list',args=['empresas']),{'archive':'archived'}).context['rows']
        self.assertTrue(any(row['obj'].pk==self.company.pk for row in rows))
        self.assertEqual(self.client.get(reverse('master-resource-edit',args=['empresas',self.company.pk])).status_code,302)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('portal-home')).status_code,403)
        self.client.force_login(self.master)
        self.lifecycle('restore')
        self.company.refresh_from_db()
        self.assertIsNone(self.company.archived_at)
        self.assertTrue(self.company.public_enabled)
        self.assertTrue(self.company.public_booking_enabled)
        self.assertEqual(self.company.status,'active')
        self.assertEqual(AuditLog.objects.filter(action='MASTER_COMPANY_ARCHIVED').count(),1)

    def test_delete_preserves_financial_history_and_revokes_access(self):
        Unit.objects.create(tenant=self.company,name='Unidade')
        response=self.client.get(reverse('master-company-lifecycle',args=[self.company.pk,'delete']))
        self.assertEqual(response.context['impact']['usuarios'],1)
        self.assertEqual(response.context['impact']['pagamentos'],1)
        self.lifecycle('delete')
        self.company.refresh_from_db()
        self.owner.refresh_from_db()
        self.sub.refresh_from_db()
        self.assertIsNotNone(self.company.deleted_at)
        self.assertFalse(self.owner.is_active)
        self.assertEqual(self.sub.status,'cancelled')
        self.assertTrue(Payment.objects.filter(pk=self.payment.pk).exists())
        self.assertTrue(AuditLog.objects.filter(tenant=self.company,action='MASTER_ACCOUNT_DELETION_APPROVED').exists())
        self.assertEqual(self.client.get(reverse('master-company-detail',args=[self.company.pk])).status_code,200)
        self.assertEqual(self.client.get(reverse('master-company-lifecycle',args=[self.company.pk,'restore'])).status_code,404)
        self.assertFalse(Notification.objects.filter(template_key='account_deletion_approved').exists())

    def test_master_link_prevents_accidental_platform_lockout(self):
        self.master.tenant=self.company
        self.master.save(update_fields=['tenant'])
        self.lifecycle('delete')
        self.company.refresh_from_db()
        self.assertIsNone(self.company.deleted_at)
        self.lifecycle('archive')
        self.company.refresh_from_db()
        self.assertIsNone(self.company.archived_at)

    def test_delete_does_not_finish_when_provider_cancellation_is_unconfirmed(self):
        self.sub.provider_subscription_id='card-id'
        self.sub.save(update_fields=['provider_subscription_id'])
        self.lifecycle('delete')
        self.company.refresh_from_db()
        self.owner.refresh_from_db()
        self.assertIsNone(self.company.deleted_at)
        self.assertTrue(self.owner.is_active)
        self.assertFalse(self.company.billing_support_requests.exists())

    def test_charge_filters_and_invalid_dates(self):
        response=self.client.get(reverse('master-charges'),{'method':'card','status':'overdue'})
        self.assertEqual(response.context['page'].paginator.count,1)
        response=self.client.get(reverse('master-charges'),{'method':'pix'})
        self.assertEqual(response.context['page'].paginator.count,0)
        response=self.client.get(reverse('master-charges'),{'start':'2026-12-01','end':'2026-01-01'})
        self.assertEqual(response.context['page'].paginator.count,0)
        self.assertContains(response,'A data final deve ser')

    def gateway(self):
        return PaymentGateway.objects.create(provider='mercadopago',environment='production',active=True,last_test_status='validated',access_token_encrypted='unused',webhook_secret_encrypted='unused')

    def remote(self,**kwargs):
        return {'id':123,'external_reference':'console-ref','currency_id':'BRL','transaction_amount':'100.00','status':'approved','live_mode':True,'date_approved':self.now.isoformat(),**kwargs}

    @patch('billing.payment_services.platform_provider')
    def test_card_consultation_is_authenticated_idempotent_and_audited(self,provider):
        self.gateway()
        provider.return_value.get_payment.return_value=self.remote()
        url=reverse('master-charge-consult',args=[self.payment.pk])
        self.assertEqual(self.client.get(url).status_code,405)
        self.client.post(url)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status,'paid')
        self.assertEqual(self.payment.paid_at,self.now)
        self.client.post(url)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.paid_at,self.now)
        self.assertEqual(AuditLog.objects.filter(action='MASTER_PAYMENT_CONSULTED').count(),2)

    @patch('billing.payment_services.platform_provider')
    def test_remote_mismatches_never_approve(self,provider):
        self.gateway()
        for changes in [{'external_reference':'foreign'},{'transaction_amount':'1'},{'currency_id':'USD'},{'live_mode':False},{'id':999}]:
            provider.return_value.get_payment.return_value=self.remote(**changes)
            self.client.post(reverse('master-charge-consult',args=[self.payment.pk]))
            self.payment.refresh_from_db()
            self.assertEqual(self.payment.status,'pending')
        self.assertEqual(AuditLog.objects.filter(action='MASTER_PAYMENT_CONSULTED',after__result='failed').count(),5)

    @patch('billing.payment_services.platform_provider')
    def test_card_authorization_does_not_count_as_payment_and_cancelled_subscription_stays_cancelled(self,provider):
        self.gateway()
        provider.return_value.get_payment.return_value=self.remote(status='authorized')
        self.client.post(reverse('master-charge-consult',args=[self.payment.pk]))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status,'pending')
        self.sub.status='cancelled'
        self.sub.save(update_fields=['status'])
        provider.return_value.get_payment.return_value=self.remote()
        self.client.post(reverse('master-charge-consult',args=[self.payment.pk]))
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status,'cancelled')

    def test_payment_details_hide_raw_provider_payload(self):
        WebhookEvent.objects.create(provider='mercadopago',event_id='safe',resource_type='payment',resource_id='123',payload={'secret':'NEVER_SHOW_THIS'},signature_valid=True,payload_hash='a'*64)
        response=self.client.get(reverse('master-charge-detail',args=[self.payment.pk]))
        self.assertContains(response,'Últimas notificações')
        self.assertNotContains(response,'NEVER_SHOW_THIS')

    def period(self,kind):
        return {'start':str(timezone.localdate()),'end':str(timezone.localdate()),'kind':kind,'export':'csv'}

    def test_all_csv_reports_export_and_invalid_period_cannot_export(self):
        self.payment.status='paid'
        self.payment.paid_at=self.now
        self.payment.save()
        PlatformFinancialTransaction.objects.create(type='expense',status='paid',amount=20,description='Servidor',paid_at=self.now)
        for kind in ['companies','growth','revenue','expenses','overdue']:
            response=self.client.get(reverse('master-reports'),self.period(kind))
            self.assertEqual(response['Content-Type'],'text/csv; charset=utf-8')
            self.assertTrue(response.content.startswith(b'\xef\xbb\xbf'))
        data=self.client.get(reverse('master-reports'),self.period('revenue')).content.decode()
        self.assertIn('100,00',data)
        response=self.client.get(reverse('master-reports'),{'start':'wrong','end':'wrong','kind':'revenue','export':'csv'})
        self.assertNotIn('Content-Disposition',response)

    def test_csv_neutralizes_formulas_and_financial_report_excludes_sandbox(self):
        self.company.name='=HYPERLINK("evil")'
        self.company.save()
        data=self.client.get(reverse('master-reports'),self.period('companies')).content.decode()
        self.assertIn("'=HYPERLINK",data)
        self.payment.environment='sandbox'
        self.payment.status='paid'
        self.payment.paid_at=self.now
        self.payment.save()
        data=self.client.get(reverse('master-reports'),self.period('revenue')).content.decode()
        self.assertNotIn('100,00',data)
        self.assertTrue(AuditLog.objects.filter(action='MASTER_REPORT_EXPORTED').exists())

    def test_lifecycle_and_provider_actions_require_csrf(self):
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.master)
        self.assertEqual(client.post(reverse('master-company-lifecycle',args=[self.company.pk,'delete']),{'confirm_name':self.company.name,'confirm_impact':'yes'}).status_code,403)
        self.assertEqual(client.post(reverse('master-charge-consult',args=[self.payment.pk])).status_code,403)
        self.company.refresh_from_db()
        self.assertIsNone(self.company.deleted_at)

    def test_archived_trial_cannot_bypass_access_gate(self):
        from billing.access import subscription_allows_access
        self.company.archived_at=self.now
        self.company.save(update_fields=['archived_at'])
        self.sub.trial_ends_at=self.now+timedelta(days=1)
        self.sub.save(update_fields=['trial_ends_at'])
        self.sub.refresh_from_db()
        self.assertFalse(subscription_allows_access(self.sub))

    @patch('billing.payment_services.platform_provider')
    def test_charge_changed_while_querying_is_not_approved(self,provider):
        self.gateway()
        def remote_response(_id):
            Payment.objects.filter(pk=self.payment.pk).update(amount=200)
            return self.remote()
        provider.return_value.get_payment.side_effect=remote_response
        self.client.post(reverse('master-charge-consult',args=[self.payment.pk]))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.amount,200)
        self.assertEqual(self.payment.status,'pending')


class MasterPixConsultationTests(TestCase):
    def test_master_pix_consultation_reuses_verified_orders_and_does_not_duplicate_cycle(self):
        from billing.test_platform_pix import PlatformPixTests
        from unittest.mock import Mock
        PlatformPixTests.setUp(self)
        charge=PlatformPixTests._charge(self)
        master=User.objects.create_superuser(email='master-pix-console@example.test',password='SyntheticPassword123!')
        self.client.force_login(master)
        provider=Mock()
        provider.get_order.return_value=PlatformPixTests._order(self,charge)
        with patch('billing.pix_reconciliation.platform_provider',return_value=provider):
            self.client.post(reverse('master-charge-consult',args=[charge.payment_id]))
            self.subscription.refresh_from_db()
            deadline=self.subscription.next_billing_at
            self.client.post(reverse('master-charge-consult',args=[charge.payment_id]))
        charge.payment.refresh_from_db()
        self.subscription.refresh_from_db()
        self.assertEqual(charge.payment.status,'paid')
        self.assertEqual(self.subscription.next_billing_at,deadline)
        self.assertEqual(AuditLog.objects.filter(action='MASTER_PAYMENT_CONSULTED',entity_id=charge.payment_id).count(),2)
