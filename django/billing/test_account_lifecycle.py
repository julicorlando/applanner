from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from accounts.models import User
from tenants.models import Tenant
from operations.models import BillingSupportRequest,SupportTicket
from .models import Plan, Subscription, SubscriptionHistory, PaymentGateway
from .webhooks import _subscription_status


class AccountLifecycleTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name='Salão',slug='salao-lifecycle')
        self.owner=User.objects.create_user(email='owner@teste.local',password='SenhaFortissima123!',tenant=self.tenant,role='owner')
        self.member=User.objects.create_user(email='member@teste.local',password='SenhaFortissima123!',tenant=self.tenant,role='user')
        self.plan=Plan.objects.create(name='Plano',slug='lifecycle',monthly_price=49)
        self.subscription=Subscription.objects.create(tenant=self.tenant,plan=self.plan,status='active',started_at=timezone.now())

    def test_cancel_requires_owner_and_password_and_logs_history(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.post('/billing/assinatura/cancelar/',{'password':'SenhaFortissima123!'}).status_code,403)
        self.client.force_login(self.owner)
        self.client.post('/billing/assinatura/cancelar/',{'password':'errada'})
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status,'active')
        self.client.post('/billing/assinatura/cancelar/',{'password':'SenhaFortissima123!'})
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status,'cancelled')
        self.assertIsNotNone(self.subscription.cancelled_at)
        self.assertEqual(SubscriptionHistory.objects.filter(subscription=self.subscription,reason='Cancelamento solicitado pelo titular').count(),1)

    @patch('billing.views.platform_provider')
    def test_remote_failure_does_not_claim_cancellation(self,provider):
        self.subscription.provider_subscription_id='preapproval-123'
        self.subscription.save()
        PaymentGateway.objects.create(provider='mercadopago',environment='sandbox',active=True,last_test_status='validated')
        provider.return_value.cancel_subscription.side_effect=RuntimeError('failed')
        self.client.force_login(self.owner)
        self.client.post('/billing/assinatura/cancelar/',{'password':'SenhaFortissima123!'})
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status,'active')
        self.assertFalse(SubscriptionHistory.objects.filter(subscription=self.subscription).exists())

    def test_deletion_request_requires_owner_and_is_idempotent(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.post('/billing/conta/solicitar-exclusao/',{'password':'SenhaFortissima123!'}).status_code,403)
        self.client.force_login(self.owner)
        self.client.post('/billing/conta/solicitar-exclusao/',{'password':'errada'})
        self.assertFalse(SupportTicket.objects.exists())
        for _ in range(2):
            self.client.post('/billing/conta/solicitar-exclusao/',{'password':'SenhaFortissima123!','reason':'Encerrar'})
        self.assertEqual(SupportTicket.objects.filter(tenant=self.tenant,category='account_deletion').count(),1)
        self.assertEqual(BillingSupportRequest.objects.filter(
            tenant=self.tenant,request_type=BillingSupportRequest.RequestType.ACCOUNT_DELETION,
            status=BillingSupportRequest.Status.PENDING,
        ).count(),1)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status,'active')

    def test_mercado_pago_uses_documented_canceled_status(self):
        from .mercadopago import MercadoPagoProvider
        calls=[]
        provider=MercadoPagoProvider('TEST-123456789012345',transport=lambda *args: calls.append(args) or {'status':'canceled'})
        provider.cancel_subscription('preapproval-123')
        self.assertEqual(calls[0][2],{'status':'canceled'})
        self.assertEqual(_subscription_status('canceled'),Subscription.Status.CANCELLED)
