from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4
from django.test import TestCase,override_settings,RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from tenants.models import Tenant,Unit
from billing.models import Plan,Subscription,Payment
from scheduling.models import Professional,Service,Appointment,Customer
from communications.models import Notification
from operations.models import SupportTicket,SupportMessage,RuntimeEvent,TenantActivity
from operations.telemetry import RuntimeMonitoringMiddleware,request_trace,trace_id,record_event
from operations.tasks import prune_runtime_history
from core.company_health import company_health
from core.models import AuditLog

@override_settings(SUBSCRIPTION_ACCESS_ENFORCED=False)
class CustomerOperationsTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name='Empresa Saúde',slug='customer-health',status='active',public_enabled=True)
        self.unit=Unit.objects.create(tenant=self.tenant,name='Centro',is_primary=True)
        self.other=Unit.objects.create(tenant=self.tenant,name='Bairro')
        self.owner=User.objects.create_user(email='health-owner@example.test',tenant=self.tenant,role='owner')
        self.master=User.objects.create_superuser(email='health-master@example.test',password='Synthetic123!')
        self.support=User.objects.create_user(email='health-support@example.test',role='master-support',is_staff=True)
        self.pro=Professional.objects.create(tenant=self.tenant,unit=self.unit,name='Ana')
        self.service=Service.objects.create(tenant=self.tenant,unit=self.unit,name='Corte',duration_minutes=30,price=40)
        self.customer=Customer.objects.create(tenant=self.tenant,name='Cliente')
        self.start=timezone.now()+timedelta(days=1)
        self.ticket=SupportTicket.objects.create(tenant=self.tenant,user=self.owner,protocol='QA-HEALTH-001',category='agenda',subject='Ajuda',description='Configurar horários')
        self.client.force_login(self.owner)

    def appointment(self,unit=None,status='confirmed'):
        return Appointment.objects.create(tenant=self.tenant,unit=unit or self.unit,professional=self.pro,service=self.service,customer=self.customer,starts_at=self.start,ends_at=self.start+timedelta(minutes=30),status=status)

    def notification(self,appointment=None,**extra):
        row=appointment or self.appointment()
        return Notification.objects.create(tenant=self.tenant,channel='email',template_key='appointment_confirmation',destination='synthetic@example.test',payload={'appointment_id':row.pk,'text':'Confirmação'},status='failed',**extra)

    def test_health_flags_paying_company_without_first_booking_and_recent_usage(self):
        plan=Plan.objects.create(name='Plano',slug='health-plan',monthly_price=100)
        sub=Subscription.objects.create(tenant=self.tenant,plan=plan,started_at=timezone.now(),status='active')
        Payment.objects.create(tenant=self.tenant,subscription=sub,amount=100,status='paid',purpose='subscription',environment='production',paid_at=timezone.now())
        data=company_health(self.tenant)
        self.assertTrue(data['paid']);self.assertIn('Contratou e ainda não registrou o primeiro agendamento.',data['reasons'])
        self.appointment();TenantActivity.objects.create(tenant=self.tenant,last_active_at=timezone.now()-timedelta(days=8))
        data=company_health(self.tenant)
        self.assertIsNotNone(data['first_booking']);self.assertEqual(data['recent_bookings'],1)
        Appointment.objects.filter(tenant=self.tenant).update(status='cancelled')
        self.assertIsNotNone(company_health(self.tenant)['first_booking'])
        self.assertIn('Sem atividade da conta nos últimos 7 dias.',data['reasons'])

    def test_health_and_monitoring_are_master_only_and_paginated(self):
        for name in ['master-company-health','master-runtime-monitor']:
            self.assertEqual(self.client.get(reverse(name)).status_code,403)
        self.client.force_login(self.master)
        self.assertContains(self.client.get(reverse('master-company-health')),'Empresa Saúde')
        self.assertEqual(self.client.get(reverse('master-runtime-monitor'),{'trace':'invalid'}).status_code,200)
        self.client.force_login(self.support)
        self.assertEqual(self.client.get(reverse('master-company-health')).status_code,200)
        self.assertEqual(self.client.get(reverse('master-runtime-monitor')).status_code,200)

    def test_internal_notes_are_hidden_from_customer_thread(self):
        self.client.force_login(self.support)
        response=self.client.post(reverse('master-support-ticket',args=[self.ticket.pk]),{'action':'note','message':'NOTA PRIVADA MASTER'})
        self.assertEqual(response.status_code,302)
        self.assertTrue(SupportMessage.objects.get(ticket=self.ticket).is_internal)
        self.client.force_login(self.owner)
        response=self.client.get(reverse('support-ticket-detail',args=[self.ticket.pk]))
        self.assertNotContains(response,'NOTA PRIVADA MASTER')
        self.assertEqual(self.client.post(reverse('master-support-ticket',args=[self.ticket.pk]),{'action':'note','message':'forjado'}).status_code,403)
        self.assertEqual(SupportMessage.objects.filter(ticket=self.ticket).count(),1)

    def test_support_management_requires_solution_and_valid_internal_assignee(self):
        self.client.force_login(self.support)
        url=reverse('master-support-ticket',args=[self.ticket.pk])
        data={'action':'manage','status':'resolved','assigned_to':self.support.pk,'solution':''}
        self.assertContains(self.client.post(url,data),'Descreva a solução')
        self.ticket.refresh_from_db();self.assertEqual(self.ticket.status,'open')
        data.update(solution='Horários corrigidos.',due_at=(timezone.now()+timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'))
        self.assertEqual(self.client.post(url,data).status_code,302)
        self.ticket.refresh_from_db();self.assertEqual(self.ticket.assigned_to,self.support);self.assertIsNotNone(self.ticket.resolved_at)
        self.assertEqual(self.ticket.solution,'Horários corrigidos.')
        self.assertTrue(AuditLog.objects.filter(action='SUPPORT_TICKET_MANAGED').exists())
        data['assigned_to']=self.owner.pk
        self.assertEqual(self.client.post(url,data).status_code,200)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('support-ticket-detail',args=[self.ticket.pk])),'Horários corrigidos.')

    def test_notification_center_is_unit_scoped_and_retry_is_idempotent(self):
        notification=self.notification()
        other=self.notification(self.appointment(unit=self.other))
        response=self.client.get(reverse('communications-deliveries'))
        self.assertEqual([row.pk for row in response.context['page']],[notification.pk])
        url=reverse('communications-delivery-retry',args=[notification.pk])
        self.assertEqual(self.client.post(url).status_code,302)
        self.client.post(url)
        notification.refresh_from_db();self.assertEqual(notification.status,'queued');self.assertEqual(notification.manual_retry_count,1)
        self.assertEqual(AuditLog.objects.filter(action='NOTIFICATION_RETRY_QUEUED').count(),1)
        self.assertEqual(self.client.post(reverse('communications-delivery-retry',args=[other.pk])).status_code,404)

    def test_delivered_or_ambiguous_notifications_are_not_requeued(self):
        row=self.notification(provider_reference='provider-confirmed')
        self.client.post(reverse('communications-delivery-retry',args=[row.pk]))
        row.refresh_from_db();self.assertEqual(row.status,'failed');self.assertEqual(row.manual_retry_count,0)
        row.provider_reference='';row.delivered_at=timezone.now();row.save()
        self.client.post(reverse('communications-delivery-retry',args=[row.pk]))
        row.refresh_from_db();self.assertEqual(row.manual_retry_count,0)

    def test_retry_limit_cooldown_and_cancelled_appointments(self):
        row=self.notification(manual_retry_count=3)
        self.client.post(reverse('communications-delivery-retry',args=[row.pk]));row.refresh_from_db();self.assertEqual(row.status,'failed')
        row.manual_retry_count=1;row.last_manual_retry_at=timezone.now();row.save()
        self.client.post(reverse('communications-delivery-retry',args=[row.pk]));row.refresh_from_db();self.assertEqual(row.status,'failed')
        row.last_manual_retry_at=None;row.save()
        Appointment.objects.filter(pk=row.payload['appointment_id']).update(status='cancelled')
        self.client.post(reverse('communications-delivery-retry',args=[row.pk]));row.refresh_from_db();self.assertEqual(row.status,'failed')

        response=self.client.get(reverse('communications-deliveries'))
        self.assertFalse(next(item for item in response.context['page'] if item.pk==row.pk).retry_allowed)
        row.template_key='appointment_2h';row.save()
        Appointment.objects.filter(pk=row.payload['appointment_id']).update(
            status='confirmed',
            starts_at=timezone.now()-timedelta(hours=1),
            ends_at=timezone.now()-timedelta(minutes=30))
        self.client.post(reverse('communications-delivery-retry',args=[row.pk]))
        row.refresh_from_db();self.assertEqual(row.status,'failed')

    def test_customer_notifications_cannot_cross_tenants(self):
        outside=Tenant.objects.create(name='Outra',slug='health-other')
        foreign_unit=Unit.objects.create(tenant=outside,name='Outra unidade')
        row=self.notification()
        Notification.objects.filter(pk=row.pk).update(tenant=outside)
        self.assertEqual(self.client.post(reverse('communications-delivery-retry',args=[row.pk])).status_code,404)
        self.assertEqual(self.client.get(reverse('communications-deliveries'),{'unit':foreign_unit.pk}).status_code,404)

    def test_monitoring_correlates_requests_without_sensitive_payloads(self):
        rid=uuid4();token=request_trace.set(rid)
        row=self.notification();request_trace.reset(token)
        self.assertEqual(row.trace_id,rid)
        factory=RequestFactory();request=factory.get('/app/?token=SECRET-SENSITIVE');request.user=self.owner
        SessionMiddleware(lambda r:None).process_request(request)
        def response(req):
            self.assertEqual(trace_id(),req.operation_request_id)
            return HttpResponse('body SECRET-SENSITIVE',status=500)
        middleware=RuntimeMonitoringMiddleware(response)
        middleware.process_exception(request,RuntimeError('SECRET-SENSITIVE'))
        response=middleware(request)
        event=RuntimeEvent.objects.get(request_id=response['X-Request-ID'])
        self.assertEqual(event.error_type,'RuntimeError');self.assertEqual(event.status_code,500)
        self.assertNotIn('SECRET-SENSITIVE',str(event.__dict__))
        self.assertIsNone(request_trace.get())

    def test_monitoring_failure_does_not_break_request_and_retention_prunes_only_old_events(self):
        factory=RequestFactory();request=factory.get('/healthz/');request.user=self.owner
        SessionMiddleware(lambda r:None).process_request(request)
        with patch('operations.models.RuntimeEvent.objects.create',side_effect=RuntimeError('database unavailable')):
            self.assertEqual(RuntimeMonitoringMiddleware(lambda r:HttpResponse('OK'))(request).status_code,200)
        old=RuntimeEvent.objects.create(request_id=uuid4(),component='http',operation='old')
        RuntimeEvent.objects.filter(pk=old.pk).update(created_at=timezone.now()-timedelta(days=15))
        new=RuntimeEvent.objects.create(request_id=uuid4(),component='http',operation='new')
        prune_runtime_history()
        self.assertFalse(RuntimeEvent.objects.filter(pk=old.pk).exists());self.assertTrue(RuntimeEvent.objects.filter(pk=new.pk).exists())

    @override_settings(MASTER_WHATSAPP_GATEWAY_TOKEN='synthetic-test-token')
    def test_whatsapp_receipt_updates_only_matching_company_and_destination(self):
        row=self.notification();row.channel='whatsapp';row.destination='5581999999999';row.provider_reference='msg-test';row.status='sent';row.save()
        payload={'event':'receipt','tenant_id':self.tenant.pk,'to':'5581999999999@s.whatsapp.net','id':'msg-test','status':'delivered'}
        response=self.client.post(reverse('tenant-whatsapp-receive'),payload,content_type='application/json',HTTP_AUTHORIZATION='Bearer synthetic-test-token')
        self.assertEqual(response.status_code,200,response.content)
        row.refresh_from_db();self.assertIsNotNone(row.delivered_at)
        timestamp=row.delivered_at
        self.client.post(reverse('tenant-whatsapp-receive'),payload,content_type='application/json',HTTP_AUTHORIZATION='Bearer synthetic-test-token')
        row.refresh_from_db();self.assertEqual(row.delivered_at,timestamp)

    def test_sender_records_delivery_attempt_under_original_trace(self):
        from communications.tasks import send_notification
        row=self.notification();row.status='queued';row.save()
        with patch('communications.tasks.EmailMultiAlternatives.send',return_value=1):
            send_notification.apply(args=[row.pk],throw=True)
        row.refresh_from_db();self.assertEqual(row.status,'sent')
        event=RuntimeEvent.objects.get(component='notification',request_id=row.trace_id)
        self.assertEqual(event.status_code,200);self.assertEqual(event.tenant_id,self.tenant.pk)
        with patch('communications.tasks.EmailMultiAlternatives.send') as send:
            send_notification.apply(args=[row.pk],throw=True)
            send.assert_not_called()
        self.assertEqual(RuntimeEvent.objects.filter(component='notification',request_id=row.trace_id).count(),1)

    def test_activity_is_collected_only_from_successful_company_operation(self):
        self.client.get(reverse('tenant-public',args=[self.tenant.slug]))
        self.assertFalse(TenantActivity.objects.filter(tenant=self.tenant).exists())
        response=self.client.get(reverse('portal-home'))
        self.assertIn('X-Request-ID',response.headers)
        self.assertTrue(TenantActivity.objects.filter(tenant=self.tenant).exists())
        rid=response.headers['X-Request-ID']
        self.assertTrue(RuntimeEvent.objects.filter(request_id=rid,tenant=self.tenant,operation='portal-home').exists())
