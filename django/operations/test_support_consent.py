from django.test import TestCase,override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from tenants.models import Tenant
from .models import SupportAccessSession,SupportTicket


@override_settings(SECURE_SSL_REDIRECT=False)
class SupportConsentTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Suporte",slug="suporte-paridade")
        self.owner=User.objects.create_user(email="owner@example.test",password="StrongPassword123!",tenant=self.tenant)
        self.other=User.objects.create_user(email="other@example.test",password="StrongPassword123!",tenant=self.tenant)
        self.ticket=SupportTicket.objects.create(
            protocol="SC-TEST-1",tenant=self.tenant,user=self.owner,
            category="billing",subject="Assinatura",description="Ajuda",
        )
        self.url=reverse("support-ticket-detail",args=[self.ticket.pk])

    def test_only_requester_can_authorize_and_revocation_ends_access(self):
        self.client.force_login(self.other)
        response=self.client.post(self.url,{"action":"remote_access","allowed":"1"})
        self.assertEqual(response.status_code,403)
        self.ticket.refresh_from_db()
        self.assertFalse(self.ticket.remote_access_allowed)

        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(self.url,{"action":"remote_access","allowed":"1"}).status_code,302)
        self.ticket.refresh_from_db()
        self.assertTrue(self.ticket.remote_access_allowed)
        self.assertIsNotNone(self.ticket.remote_access_allowed_at)
        session=SupportAccessSession.objects.create(
            ticket=self.ticket,tenant=self.tenant,master_user=self.other,
            impersonated_user=self.owner,started_at=timezone.now(),
        )
        self.assertEqual(self.client.post(self.url,{"action":"remote_access","allowed":"0"}).status_code,302)
        self.ticket.refresh_from_db()
        session.refresh_from_db()
        self.assertFalse(self.ticket.remote_access_allowed)
        self.assertIsNotNone(self.ticket.remote_access_revoked_at)
        self.assertIsNotNone(session.ended_at)
