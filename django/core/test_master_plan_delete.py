from datetime import timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from billing.models import Plan, Subscription, SubscriptionHistory
from tenants.models import Tenant

class MasterPlanDeleteTests(TestCase):
    def setUp(self):
        self.master=User.objects.create_superuser(email="master-delete@example.test",password="StrongPassword123!")
        self.client.force_login(self.master)
        self.plan=Plan.objects.create(name="Plano antigo",slug="plano-antigo",monthly_price=10)
        self.url=reverse("master-plan-delete",args=[self.plan.pk])
    def test_unused_plan_requires_exact_name_and_deletes(self):
        self.assertContains(self.client.get(self.url),"pode ser removido com segurança")
        response=self.client.post(self.url,{"confirm_name":"Outro"})
        self.assertEqual(response.status_code,200)
        self.assertTrue(Plan.objects.filter(pk=self.plan.pk).exists())

        response=self.client.post(self.url,{"confirm_name":"Plano antigo"})
        self.assertRedirects(response,reverse("master-resource-list",args=["planos"]))
        self.assertFalse(Plan.objects.filter(pk=self.plan.pk).exists())

    def test_history_of_previous_plan_preserved(self):
        tenant=Tenant.objects.create(name="Empresa",slug="history-plan")
        current=Plan.objects.create(name="Atual",slug="current-plan")
        subscription=Subscription.objects.create(tenant=tenant,plan=current,started_at=timezone.now())
        SubscriptionHistory.objects.create(tenant=tenant,subscription=subscription,from_plan=self.plan,to_plan=current)
        response=self.client.post(self.url,{"confirm_name":self.plan.name})
        self.assertEqual(response.status_code,302)
        self.assertTrue(Plan.objects.filter(pk=self.plan.pk).exists())

    def test_company_cannot_remove_plan(self):
        tenant=Tenant.objects.create(name="Empresa",slug="permission-plan")
        owner=User.objects.create_user(email="owner-delete@example.test",role="owner",tenant=tenant)
        self.client.force_login(owner)
        self.assertEqual(self.client.post(self.url,{"confirm_name":self.plan.name}).status_code,403)
        self.assertTrue(Plan.objects.filter(pk=self.plan.pk).exists())
    def test_plan_with_subscription_cannot_be_deleted(self):
        tenant=Tenant.objects.create(name="Empresa",slug="empresa-plano-antigo")
        Subscription.objects.create(tenant=tenant,plan=self.plan,started_at=timezone.now(),status="cancelled",trial_ends_at=timezone.now()+timedelta(days=1))
        self.assertContains(self.client.get(self.url),"assinaturas")
        response=self.client.post(self.url,{"confirm_name":"Plano antigo"})
        self.assertRedirects(response,reverse("master-resource-list",args=["planos"]))
        self.assertTrue(Plan.objects.filter(pk=self.plan.pk).exists())
