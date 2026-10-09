from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.models import Plan,Subscription
from communications.models import Notification
from operations.models import BillingSupportRequest,HomologationRun,SupportTicket
from tenants.models import Tenant


class MasterOperationalActionTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_superuser(email="master-actions@example.com",password="StrongPassword123!")
        self.client.force_login(self.user)

    @patch("operations.services.shutil.disk_usage")
    def test_homologation_action(self,disk_usage):
        disk_usage.return_value=type("Usage",(),{"free":20*1024*1024*1024})()
        response=self.client.post(reverse("master-operational-action",args=["homologation-run"]))
        self.assertEqual(response.status_code,302)
        self.assertEqual(HomologationRun.objects.count(),1)


    def test_master_can_approve_and_complete_account_deletion(self):
        tenant=Tenant.objects.create(
            name="Empresa para excluir",slug="empresa-para-excluir",
            status=Tenant.Status.ACTIVE,public_enabled=True,public_booking_enabled=True,
            email="contato@empresa.test",
        )
        owner=User.objects.create_user(
            email="titular@empresa.test",password="StrongPassword123!",
            tenant=tenant,role="owner",first_name="Titular",
        )
        member=User.objects.create_user(
            email="equipe@empresa.test",password="StrongPassword123!",
            tenant=tenant,role="user",
        )
        plan=Plan.objects.create(name="Plano exclusão",slug="plano-exclusao",monthly_price=49)
        subscription=Subscription.objects.create(
            tenant=tenant,plan=plan,status=Subscription.Status.ACTIVE,
            started_at=timezone.now(),
        )
        ticket=SupportTicket.objects.create(
            protocol="EX-TESTE",tenant=tenant,user=owner,category="account_deletion",
            subject="Solicitação de exclusão de conta e dados",description="Encerrar",
        )
        deletion=BillingSupportRequest.objects.create(
            tenant=tenant,user=owner,ticket=ticket,
            request_type=BillingSupportRequest.RequestType.ACCOUNT_DELETION,
        )

        response=self.client.post(reverse(
            "master-operational-object-action",
            args=["account-deletion-approve",deletion.pk],
        ))
        self.assertEqual(response.status_code,302)

        self.assertEqual(self.client.get(reverse("master-resource-list",args=["empresas"])).context["rows"],[])
        self.assertEqual(self.client.get(reverse("master-resource-edit",args=["empresas",tenant.pk])).status_code,404)
        dashboard=self.client.get(reverse("master-home"))
        self.assertEqual(next(card["count"] for card in dashboard.context["cards"] if card["slug"]=="empresas"),0)
        platform=self.client.get(reverse("home"))
        self.assertEqual(platform.context["tenants_total"],0)
        self.assertEqual(list(platform.context["recent_tenants"]),[])

        tenant.refresh_from_db()
        owner.refresh_from_db()
        member.refresh_from_db()
        subscription.refresh_from_db()
        deletion.refresh_from_db()
        ticket.refresh_from_db()

        self.assertEqual(tenant.status,Tenant.Status.CANCELLED)
        self.assertIsNotNone(tenant.deleted_at)
        self.assertFalse(tenant.public_enabled)
        self.assertFalse(tenant.public_booking_enabled)
        self.assertFalse(owner.is_active)
        self.assertFalse(member.is_active)
        self.assertIsNotNone(owner.deleted_at)
        self.assertIsNotNone(member.deleted_at)
        self.assertEqual(subscription.status,Subscription.Status.CANCELLED)
        self.assertEqual(deletion.status,BillingSupportRequest.Status.COMPLETED)
        self.assertEqual(deletion.reviewed_by,self.user)
        self.assertEqual(ticket.status,SupportTicket.Status.CLOSED)
        notification=Notification.objects.get(template_key="account_deletion_approved")
        self.assertEqual(notification.destination,"titular@empresa.test")
        self.assertEqual(notification.status,Notification.Status.QUEUED)
