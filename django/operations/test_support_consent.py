from django.test import Client,TestCase,override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from tenants.models import Tenant
from core.models import AuditLog
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

    def _prepare_actor(self):
        self.owner.role="owner"
        self.owner.save(update_fields=["role"])
        self.actor=User.objects.create_superuser(
            email="master@example.test",password="StrongPassword123!",
        )
        self.client.force_login(self.owner)
        self.client.post(self.url,{"action":"remote_access","allowed":"1"})
        self.client.force_login(self.actor)

    def test_assisted_access_switches_identity_and_restores_actor(self):
        self._prepare_actor()
        start=reverse("support-start-access",args=[self.ticket.pk])
        self.assertEqual(self.client.post(start).status_code,302)
        self.assertEqual(int(self.client.session["_auth_user_id"]),self.owner.pk)
        access=SupportAccessSession.objects.get(ticket=self.ticket)
        self.assertEqual(access.master_user,self.actor)
        self.assertEqual(access.impersonated_user,self.owner)
        self.assertContains(self.client.get(reverse("portal-home")),"Acesso assistido ativo")
        self.assertEqual(self.client.get("/account/2fa/setup/").status_code,403)
        self.assertEqual(self.client.post(reverse("support-end-access")).status_code,302)
        self.assertEqual(int(self.client.session["_auth_user_id"]),self.actor.pk)
        access.refresh_from_db()
        self.assertIsNotNone(access.ended_at)
        self.assertTrue(AuditLog.objects.filter(user=self.actor,action="SUPPORT_ACCESS_STARTED").exists())
        self.assertTrue(AuditLog.objects.filter(user=self.actor,action="SUPPORT_ACCESS_ENDED").exists())

    def test_revocation_expires_existing_assisted_session(self):
        self._prepare_actor()
        self.assertEqual(self.client.post(reverse("support-start-access",args=[self.ticket.pk])).status_code,302)
        owner_client=Client()
        owner_client.force_login(self.owner)
        owner_client.post(self.url,{"action":"remote_access","allowed":"0"})
        self.assertEqual(self.client.get(reverse("portal-home")).status_code,302)
        self.assertEqual(int(self.client.session["_auth_user_id"]),self.actor.pk)

    def test_unconsented_access_is_denied(self):
        self.owner.role="owner"
        self.owner.save(update_fields=["role"])
        actor=User.objects.create_superuser(email="master2@example.test",password="StrongPassword123!")
        self.client.force_login(actor)
        response=self.client.post(reverse("support-start-access",args=[self.ticket.pk]))
        self.assertEqual(response.status_code,403)
        self.assertFalse(SupportAccessSession.objects.exists())
