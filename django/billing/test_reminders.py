from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings

from accounts.models import User
from tenants.models import Tenant
from communications.models import Notification, UserNotification
from communications.tasks import send_notification
from billing.access import paid_access_until
from billing.models import Plan, Subscription, Payment, SubscriptionNoticeLog
from billing.reminders import billing_notice, queue_subscription_reminder
from billing.tasks import queue_subscription_reminders


@override_settings(PUBLIC_BASE_URL="https://applanner.example.com",SUBSCRIPTION_ACCESS_ENFORCED=True)
class BillingReminderTests(TestCase):
    def setUp(self):
        self.now=datetime(2026,10,4,12,0,tzinfo=ZoneInfo("UTC"))
        self.tenant=Tenant.objects.create(name="Empresa",slug="renewal-notice",onboarding_step=5,status="active")
        self.owner=User.objects.create_user(email="owner@example.com",tenant=self.tenant,role="owner")
        self.manager=User.objects.create_user(email="manager@example.com",tenant=self.tenant,role="manager")
        User.objects.create_user(email="staff@example.com",tenant=self.tenant,role="professional")
        self.plan=Plan.objects.create(name="Plano",slug="renewal",monthly_price=99.9)
        self.subscription=Subscription.objects.create(tenant=self.tenant,plan=self.plan,status="active",
            started_at=self.now-timedelta(days=100),next_billing_at=self.now+timedelta(days=3))
        Payment.objects.create(tenant=self.tenant,subscription=self.subscription,amount=99.9,
            status="paid",paid_at=self.now-timedelta(days=28),purpose="subscription")

    def test_each_cycle_has_three_reminders_without_duplicates(self):
        for days in [3,1,0]:
            moment=self.subscription.next_billing_at-timedelta(days=days,hours=1)
            self.assertEqual(queue_subscription_reminder(self.subscription.pk,moment),1)
            self.assertEqual(queue_subscription_reminder(self.subscription.pk,moment),0)
        self.assertEqual(SubscriptionNoticeLog.objects.count(),3)
        self.assertEqual(Notification.objects.count(),6)
        self.assertEqual(UserNotification.objects.count(),6)
        self.subscription.next_billing_at+=timedelta(days=31)
        self.subscription.save()
        self.assertEqual(queue_subscription_reminder(self.subscription.pk,self.subscription.next_billing_at-timedelta(days=3)),1)

    def test_banner_persists_until_renewal_and_is_only_for_management(self):
        self.client.force_login(self.owner)
        with patch("billing.reminders.timezone.now",return_value=self.now):
            self.assertContains(self.client.get("/billing/assinatura/"),"Sua assinatura vence em 3 dias")
            self.assertContains(self.client.get("/billing/assinatura/"),"Sua assinatura vence em 3 dias")
        self.client.logout()
        with patch("billing.reminders.timezone.now",return_value=self.now):
            self.assertNotContains(self.client.get("/planos/"),"Sua assinatura vence em 3 dias")

    def test_overdue_is_not_sent_hourly_and_cancelled_never_notifies(self):
        self.assertEqual(queue_subscription_reminder(self.subscription.pk,self.now+timedelta(days=4)),1)
        self.assertEqual(queue_subscription_reminder(self.subscription.pk,self.now+timedelta(days=10)),0)
        self.subscription.status="cancelled"
        self.subscription.save()
        self.assertIsNone(billing_notice(self.subscription,self.now))

    def test_paid_renewal_cancels_outdated_email_before_delivery(self):
        queue_subscription_reminder(self.subscription.pk,self.now)
        notification=Notification.objects.first()
        self.subscription.next_billing_at=self.now+timedelta(days=34)
        self.subscription.save()
        with patch("billing.reminders.timezone.now",return_value=self.now):
            send_notification.run(notification.pk)
        notification.refresh_from_db()
        self.assertEqual(notification.status,"skipped")
        self.assertEqual(len(mail.outbox),0)

    def test_current_email_uses_queue_and_payment_link(self):
        queue_subscription_reminder(self.subscription.pk,self.now)
        notification=Notification.objects.first()
        with patch("billing.reminders.timezone.now",return_value=self.now):
            send_notification.run(notification.pk)
        self.assertIn("https://applanner.example.com/billing/assinatura/",mail.outbox[0].body)
        notification.refresh_from_db()
        self.assertEqual(notification.status,"sent")

    def test_latest_subscription_only_and_company_isolation(self):
        old=self.subscription
        self.subscription=Subscription.objects.create(tenant=self.tenant,plan=self.plan,status="trial",
            started_at=self.now,trial_ends_at=self.now+timedelta(days=2))
        other=Tenant.objects.create(name="Outra",slug="other-reminder")
        User.objects.create_user(email="other@example.com",tenant=other,role="owner")
        with patch("billing.reminders.timezone.now",return_value=self.now):
            self.assertEqual(queue_subscription_reminders.run(),1)
        self.assertFalse(SubscriptionNoticeLog.objects.filter(subscription=old).exists())
        self.assertFalse(UserNotification.objects.filter(tenant=other).exists())

    def test_trial_reminders_are_two_days_and_expiry_and_stop_after_payment(self):
        self.subscription.payments.all().delete()
        self.subscription.status="trial"
        self.subscription.trial_ends_at=self.now+timedelta(days=2)
        self.subscription.next_billing_at=None
        self.subscription.save()
        self.assertEqual(queue_subscription_reminder(self.subscription.pk,self.now),1)
        self.assertEqual(queue_subscription_reminder(self.subscription.pk,self.now+timedelta(days=1)),0)
        self.assertEqual(billing_notice(self.subscription,self.now+timedelta(days=1))["title"],"Seu teste grátis termina em 1 dia")
        self.assertEqual(queue_subscription_reminder(self.subscription.pk,self.now+timedelta(days=2)-timedelta(hours=1)),1)
        self.assertEqual(billing_notice(self.subscription,self.now+timedelta(days=3))["title"],"Seu teste grátis terminou")
        Payment.objects.create(tenant=self.tenant,subscription=self.subscription,amount=99.9,status="paid",paid_at=self.now)
        self.assertIsNone(billing_notice(self.subscription,self.now))

    def test_tenant_timezone_controls_days_and_label(self):
        self.tenant.timezone="America/Manaus"
        self.tenant.save()
        self.subscription.next_billing_at=datetime(2026,10,8,1,tzinfo=ZoneInfo("UTC"))
        self.subscription.save()
        notice=billing_notice(self.subscription,datetime(2026,10,5,1,tzinfo=ZoneInfo("UTC")))
        self.assertEqual(notice["days"],3)
        self.assertIn("07/10/2026 às 21:00",notice["message"])

    def test_paid_deadline_falls_back_to_cycle_when_provider_date_missing(self):
        self.subscription.next_billing_at=None
        self.subscription.billing_cycle="annual"
        self.subscription.save()
        self.assertGreater(paid_access_until(self.subscription),self.now+timedelta(days=300))
        self.assertIsNone(billing_notice(self.subscription,self.now))

    def test_schedule_is_created_at_deploy(self):
        from django_celery_beat.models import PeriodicTask
        call_command("seed_periodic_tasks",verbosity=0)
        self.assertTrue(PeriodicTask.objects.get(task="billing.tasks.queue_subscription_reminders").enabled)
