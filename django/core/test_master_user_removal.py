from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import PersonalAPIToken, SecurityEvent, User
from operations.models import SupportTicket
from tenants.models import Tenant


class MasterUserRemovalTests(TestCase):
    def setUp(self):
        self.master=User.objects.create_superuser(email="master@example.test",password="SenhaForte123!")
        self.tenant=Tenant.objects.create(name="Empresa",slug="empresa")
        self.target=User.objects.create_user(
            email="cliente@example.test",password="SenhaForte123!",tenant=self.tenant,
            role="owner",first_name="Maria",
        )
        self.url=reverse("master-user-remove",args=[self.target.pk])
        self.client.force_login(self.master)

    def test_confirmation_is_required_and_get_has_no_side_effects(self):
        self.assertContains(self.client.get(self.url),self.target.email)
        self.client.post(self.url,{"confirm_email":"email-errado@example.test"})
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)
        self.assertIsNone(self.target.deleted_at)

    def test_removal_revokes_access_and_preserves_protected_history(self):
        target_browser=Client()
        target_browser.force_login(self.target)
        ticket=SupportTicket.objects.create(
            protocol="CH-001",tenant=self.tenant,user=self.target,
            category="geral",subject="Histórico",description="Chamado existente",
        )
        PersonalAPIToken.objects.create(
            user=self.target,tenant=self.tenant,name="Integração",prefix="teste",
            secret_hash="a"*64,scopes=["agenda.read"],session_version=1,
            expires_at=timezone.now()+timedelta(days=30),
        )
        original_email=self.target.email
        response=self.client.post(self.url,{"confirm_email":original_email})
        self.assertRedirects(response,reverse("master-resource-list",args=["usuarios"]))
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertFalse(self.target.has_usable_password())
        self.assertIsNotNone(self.target.deleted_at)
        self.assertEqual(self.target.first_name,"")
        self.assertNotEqual(self.target.email,original_email)
        self.assertFalse(PersonalAPIToken.objects.filter(user=self.target).exists())
        self.assertEqual(target_browser.get(reverse("master-resource-list",args=["usuarios"])).status_code,302)
        self.assertEqual(SupportTicket.objects.get(pk=ticket.pk).user_id,self.target.pk)
        self.assertTrue(SecurityEvent.objects.filter(
            user=self.master,event_type="master_user_removed",
            metadata__removed_user_id=self.target.pk,
        ).exists())
        self.assertNotContains(self.client.get(reverse("master-resource-list",args=["usuarios"])),original_email)
        self.assertEqual(self.client.get(reverse("master-resource-edit",args=["usuarios",self.target.pk])).status_code,404)
        self.assertEqual(self.client.get(self.url).status_code,404)
        replacement=User.objects.create_user(email=original_email,password="SenhaNova123!")
        self.assertNotEqual(replacement.pk,self.target.pk)

    def test_only_master_can_remove_and_master_cannot_remove_self(self):
        self.assertEqual(self.client.get(reverse("master-user-remove",args=[self.master.pk])).status_code,403)
        other=User.objects.create_superuser(email="outro-master@example.test",password="SenhaForte123!")
        self.client.force_login(self.target)
        self.assertEqual(self.client.post(reverse("master-user-remove",args=[other.pk]),{
            "confirm_email":other.email,
        }).status_code,403)
        other.refresh_from_db()
        self.assertTrue(other.is_active)

    def test_master_can_remove_another_master_without_losing_own_access(self):
        other=User.objects.create_superuser(email="coadmin@example.test",password="SenhaForte123!")
        response=self.client.post(reverse("master-user-remove",args=[other.pk]),{
            "confirm_email":other.email,
        })
        self.assertEqual(response.status_code,302)
        other.refresh_from_db()
        self.assertFalse(other.is_superuser)
        self.assertFalse(other.is_active)
        self.assertEqual(self.client.get(reverse("master-resource-list",args=["usuarios"])).status_code,200)
