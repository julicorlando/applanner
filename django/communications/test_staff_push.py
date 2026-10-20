from datetime import timedelta
from unittest.mock import patch, Mock

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from billing.models import Payment, Subscription, Plan
from core.crypto import encrypt_json, encrypt_text
from scheduling.models import Appointment, Customer, Professional, Service
from tenants.models import Tenant, Unit
from .mobile_models import PushSubscription, PushDelivery, DeliveryProviderSettings
from .mobile_delivery import appointment_event, queue_push, send_push
from .platform_events import payment_notice, reconcile_platform_events, suppress_platform_events
from .test_mobile_delivery import subscription_data


class StaffPushTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Empresa", slug="staff-push", category="Barbearia")
        self.unit = Unit.objects.create(tenant=self.tenant, name="Centro")
        self.owner = User.objects.create_user(email="owner@push.test", role="owner", tenant=self.tenant)
        self.pro_user = User.objects.create_user(email="pro@push.test", role="professional", tenant=self.tenant)
        self.other_user = User.objects.create_user(email="other@push.test", role="professional", tenant=self.tenant)
        self.professional = Professional.objects.create(tenant=self.tenant, unit=self.unit, name="Profissional", user=self.pro_user)
        self.service = Service.objects.create(tenant=self.tenant, unit=self.unit, name="Serviço", duration_minutes=30, price=50)
        self.customer = Customer.objects.create(tenant=self.tenant, name="Cliente privado", phone="81900000001")
        self.start = timezone.now() + timedelta(days=1)
        self.master = User.objects.create_superuser(email="master@push.test", password="Synthetic-only-123!")
        for index, user in enumerate([self.owner, self.pro_user, self.other_user, self.master], 1):
            PushSubscription.objects.create(tenant=user.tenant, user=user, endpoint_hash=str(index)*64,
                payload_encrypted=encrypt_json(subscription_data()), consent_at=timezone.now())
        self.appointment = Appointment.objects.create(tenant=self.tenant, unit=self.unit,
            professional=self.professional, customer=self.customer, service=self.service,
            starts_at=self.start, ends_at=self.start+timedelta(minutes=30), status="pending")

    def test_new_booking_goes_to_company_and_assigned_professional_only(self):
        deliveries = PushDelivery.objects.filter(subscription__user__in=[self.owner, self.pro_user, self.other_user])
        self.assertEqual(set(deliveries.values_list("subscription__user_id", flat=True)),
                         {self.owner.pk, self.pro_user.pk})
        self.assertEqual(set(deliveries.values_list("payload__title", flat=True)), {"Novo agendamento"})
        for row in deliveries:
            self.assertNotIn(self.customer.name, str(row.payload))
            self.assertNotIn(self.customer.phone, str(row.payload))

    def test_repeated_booking_event_has_no_duplicate_and_reassignment_notifies_new_professional(self):
        before = PushDelivery.objects.count()
        appointment_event(self.appointment, created=True)
        self.assertEqual(PushDelivery.objects.count(), before)
        other = Professional.objects.create(tenant=self.tenant, unit=self.unit, name="Outro", user=self.other_user)
        self.appointment.professional = other
        self.appointment.save(update_fields=["professional"])
        self.assertTrue(PushDelivery.objects.filter(subscription__user=self.other_user).exists())

    def test_other_company_and_inactive_users_are_excluded(self):
        outsider = Tenant.objects.create(name="Outra", slug="staff-push-other")
        self.owner.tenant = outsider
        self.owner.save(update_fields=["tenant"])
        self.pro_user.is_active = False
        self.pro_user.save(update_fields=["is_active"])
        PushDelivery.objects.all().delete()
        appointment_event(self.appointment)
        self.assertFalse(PushDelivery.objects.exists())

    def test_master_payment_event_is_private_and_deduplicated(self):
        payment = Payment.objects.create(tenant=self.tenant, amount=99, purpose="subscription", status="paid")
        with self.captureOnCommitCallbacks(execute=True):
            payment_notice(payment)
            payment_notice(payment)
        rows = PushDelivery.objects.filter(subscription__user=self.master)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.get().payload["title"], "Pagamento confirmado")
        self.assertNotIn("99", rows.get().payload["body"])

    def test_sandbox_and_customer_payments_do_not_trigger_master_financial_alert(self):
        with self.captureOnCommitCallbacks(execute=True):
            for values in [{"purpose": "booking", "environment": "production"},
                           {"purpose": "subscription", "environment": "sandbox"}]:
                payment = Payment.objects.create(tenant=self.tenant, amount=50, status="paid", **values)
                payment_notice(payment)
        self.assertFalse(PushDelivery.objects.filter(subscription__user=self.master).exists())

    def test_deadline_sweep_detects_end_of_trial_and_bulk_status_changes_once(self):
        plan = Plan.objects.create(name="Plano", slug="push-plan", monthly_price=50)
        subscription = Subscription.objects.create(tenant=self.tenant, plan=plan, status="trial",
            started_at=timezone.now()-timedelta(days=8), trial_ends_at=timezone.now()-timedelta(minutes=1))
        with self.captureOnCommitCallbacks(execute=True):
            reconcile_platform_events()
            reconcile_platform_events()
        rows = PushDelivery.objects.filter(subscription__user=self.master, payload__title="Teste grátis encerrado")
        self.assertEqual(rows.count(), 1)
        Subscription.objects.filter(pk=subscription.pk).update(status="cancelled")
        with self.captureOnCommitCallbacks(execute=True):
            reconcile_platform_events()
        self.assertTrue(PushDelivery.objects.filter(subscription__user=self.master,
                                                    payload__title="Assinatura cancelada").exists())

    def test_broker_failure_preserves_delivery_without_failing_transaction(self):
        sub = PushSubscription.objects.get(user=self.owner)
        with patch("communications.mobile_delivery.send_push.delay", side_effect=RuntimeError("broker unavailable")):
            with self.captureOnCommitCallbacks(execute=True):
                row = queue_push(sub, "broker-test", {"title": "Teste"})
        row.refresh_from_db()
        self.assertEqual(row.status, "queued")

    def test_delivery_revalidates_user_tenant_before_sending(self):
        self.owner.tenant = Tenant.objects.create(name="Destino", slug="push-moved")
        self.owner.save(update_fields=["tenant"])
        config = DeliveryProviderSettings.objects.create(pk=1, push_enabled=True, contact_email="push@example.test",
                    vapid_public_key="synthetic", vapid_private_encrypted=encrypt_text("synthetic"))
        self.assertTrue(config.push_enabled)
        delivery = PushDelivery.objects.filter(subscription__user=self.owner).first()
        with patch("pywebpush.webpush", return_value=Mock(status_code=201)) as provider:
            send_push(delivery.pk)
        provider.assert_not_called()
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, "expired")

    def test_bulk_import_event_suppression_avoids_individual_platform_push(self):
        with self.captureOnCommitCallbacks(execute=True):
            with suppress_platform_events():
                Customer.objects.create(tenant=self.tenant, name="Importado", phone="81900000002")
        self.assertFalse(PushDelivery.objects.filter(subscription__user=self.master).exists())

    def test_arena_new_reservation_notifies_company_without_professional_interface(self):
        from arena.models import Court, Reservation
        court = Court.objects.create(tenant=self.tenant, unit=self.unit, name="Quadra", slug="push-quadra")
        PushDelivery.objects.all().delete()
        Reservation.objects.create(tenant=self.tenant, court=court, public_id="push-arena-example",
            customer_name="Cliente privado", customer_phone="81900000001", starts_at=self.start,
            ends_at=self.start+timedelta(hours=1), duration_minutes=60, price_per_hour=50,
            total_amount=50, manage_token_hash="f"*64)
        rows = PushDelivery.objects.all()
        self.assertEqual(list(rows.values_list("subscription__user_id", flat=True)), [self.owner.pk])
        self.assertEqual(rows.get().payload["title"], "Nova reserva")
