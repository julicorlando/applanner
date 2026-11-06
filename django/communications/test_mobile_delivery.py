import base64, time
from unittest.mock import patch, Mock
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from django.test import TestCase, override_settings
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from core.crypto import encrypt_json, encrypt_text, decrypt_text
from scheduling.customer_portal import identity_digest
from finance import test_advanced_operations
from communications.mobile_models import (
    DeliveryProviderSettings,
    TenantDeliverySettings,
    CustomerDeliveryConsent,
    PushSubscription,
    PushDelivery,
    SMSDispatch,
)
from communications.mobile_delivery import (
    validate_subscription,
    initialize_vapid,
    queue_sms,
    phone_digest,
    send_push,
)
from communications.tasks import send_notification


def subscription_data():
    pub = (
        ec.generate_private_key(ec.SECP256R1())
        .public_key()
        .public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )
    enc = lambda data: base64.urlsafe_b64encode(data).decode().rstrip("=")
    return {
        "endpoint": "https://fcm.googleapis.com/fcm/send/testing-endpoint",
        "keys": {"auth": enc(b"0123456789abcdef"), "p256dh": enc(pub)},
    }


@override_settings(SUBSCRIPTION_ACCESS_ENFORCED=False)
class MobileDeliveryTests(TestCase):
    def setUp(self):
        test_advanced_operations.AdvancedOperationsTests.setUp(self)
        cache.clear()
        self.tenant.public_slug = "advanced-ops"
        self.tenant.public_enabled = True
        self.tenant.status = "active"
        self.tenant.save()
        self.config = DeliveryProviderSettings.objects.create(
            pk=1,
            push_enabled=True,
            contact_email="notice@example.test",
            sms_enabled=True,
            twilio_account_sid="AC" + "a" * 32,
            twilio_token_encrypted=encrypt_text("synthetic-provider-test-token"),
            sms_from="+5581990000000",
        )
        initialize_vapid(self.config)
        self.config.save()
        self.local = TenantDeliverySettings.objects.create(
            tenant=self.tenant, sms_enabled=True, sms_monthly_limit=2
        )
        self.customer.phone = "81900000001"
        self.customer.email = "consent@example.test"
        self.customer.save()

    def test_subscription_validation_blocks_private_hosts_and_invalid_keys(self):
        info = subscription_data()
        self.assertEqual(validate_subscription(info), info)
        for endpoint in [
            "http://fcm.googleapis.com/x",
            "https://127.0.0.1/",
            "https://fcm.googleapis.com.evil.test/a",
            "https://user@fcm.googleapis.com/a",
            "https://fcm.googleapis.com:444/a",
        ]:
            with self.assertRaises(ValidationError):
                validate_subscription({**info, "endpoint": endpoint})
        with self.assertRaises(ValidationError):
            validate_subscription(
                {**info, "keys": {"auth": "invalid", "p256dh": "invalid"}}
            )

    def test_professional_only_registers_own_subscription_and_ciphertext_is_stored(
        self,
    ):
        self.client.force_login(self.pro_user)
        info = subscription_data()
        response = self.client.post(
            reverse("professional-push-subscription"),
            {"subscription": info},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        row = PushSubscription.objects.get()
        self.assertEqual(row.user_id, self.pro_user.pk)
        self.assertEqual(row.tenant_id, self.tenant.pk)
        self.assertNotIn(info["endpoint"], row.payload_encrypted)

    def test_customer_enrollment_requires_verified_identity_and_rejects_another_customer(
        self,
    ):
        url = reverse("customer-push-subscription", args=[self.tenant.slug])
        info = subscription_data()
        self.assertEqual(
            self.client.post(
                url, {"subscription": info}, content_type="application/json"
            ).status_code,
            403,
        )
        session = self.client.session
        session[f"customer-portal:{self.tenant.pk}"] = {
            "customer": self.customer.pk,
            "expires": time.time() + 1000,
            "identity": identity_digest(self.customer),
        }
        session.save()
        self.assertEqual(
            self.client.post(
                url, {"subscription": info}, content_type="application/json"
            ).status_code,
            200,
        )
        self.assertEqual(PushSubscription.objects.get().customer_id, self.customer.pk)
        self.customer.email = "changed@example.test"
        self.customer.save()
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_push_delivery_is_deduplicated_and_real_encryption_accepts_generated_keys(
        self,
    ):
        info = subscription_data()
        sub = PushSubscription.objects.create(
            tenant=self.tenant,
            user=self.pro_user,
            endpoint_hash="a" * 64,
            payload_encrypted=encrypt_json(info),
            consent_at=timezone.now(),
        )
        delivery = PushDelivery.objects.create(
            subscription=sub,
            key="b" * 64,
            payload={"title": "ApPlanner", "url": "/app/profissional/"},
        )
        with patch("pywebpush.webpush", return_value=Mock(status_code=201)) as provider:
            send_push(delivery.pk)
            send_push(delivery.pk)
        self.assertEqual(provider.call_count, 1)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, "sent")
        from py_vapid import Vapid

        self.assertIsNotNone(
            Vapid.from_string(
                decrypt_text(self.config.vapid_private_encrypted)
            ).public_key
        )
        from pywebpush import webpush

        transport = Mock()
        transport.post.return_value = Mock(status_code=201)
        webpush(
            subscription_info=info,
            data="test-only",
            vapid_private_key=decrypt_text(self.config.vapid_private_encrypted),
            vapid_claims={"sub": "mailto:test@example.test"},
            requests_session=transport,
        )
        self.assertEqual(transport.post.call_count, 1)

    def test_expired_subscription_is_disabled(self):
        from pywebpush import WebPushException

        sub = PushSubscription.objects.create(
            tenant=self.tenant,
            user=self.pro_user,
            endpoint_hash="c" * 64,
            payload_encrypted=encrypt_json(subscription_data()),
            consent_at=timezone.now(),
        )
        delivery = PushDelivery.objects.create(
            subscription=sub, key="d" * 64, payload={}
        )
        response = Mock(status_code=410)
        with patch(
            "pywebpush.webpush",
            side_effect=WebPushException("expired", response=response),
        ):
            send_push(delivery.pk)
        sub.refresh_from_db()
        delivery.refresh_from_db()
        self.assertFalse(sub.active)
        self.assertEqual(delivery.status, "expired")

    def consent(self):
        CustomerDeliveryConsent.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            sms_consent_at=timezone.now(),
            phone_digest=phone_digest(self.customer),
        )

    def test_sms_requires_consent_deduplicates_and_reserves_monthly_quota(self):
        self.assertIsNone(queue_sms(self.appt, "confirmed"))
        self.consent()
        self.assertIsNotNone(queue_sms(self.appt, "confirmed"))
        self.assertIsNone(queue_sms(self.appt, "confirmed"))
        self.assertIsNotNone(queue_sms(self.appt, "reminder_2h"))
        self.assertIsNone(queue_sms(self.appt, "cancelled"))
        self.assertEqual(SMSDispatch.objects.count(), 2)

    def test_changed_phone_revokes_sms_permission(self):
        self.consent()
        self.customer.phone = "81900000002"
        self.customer.save()
        self.assertIsNone(queue_sms(self.appt, "confirmed"))

    def test_sms_uncertain_response_is_not_automatically_recharged(self):
        self.consent()
        notice = queue_sms(self.appt, "confirmed")
        with patch(
            "communications.mobile_delivery.requests.post", side_effect=TimeoutError
        ) as provider:
            send_notification(notice.pk)
            send_notification(notice.pk)
        notice.refresh_from_db()
        self.assertEqual(notice.status, "failed")
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(SMSDispatch.objects.get().state, "unknown")

    def test_sms_known_success_records_provider_reference(self):
        self.consent()
        notice = queue_sms(self.appt, "confirmed")
        with patch(
            "communications.mobile_delivery.requests.post",
            return_value=Mock(status_code=201, json=lambda: {"sid": "SM" + "b" * 32}),
        ):
            send_notification(notice.pk)
        notice.refresh_from_db()
        self.assertEqual(notice.status, "sent")
        self.assertEqual(notice.provider_reference, "SM" + "b" * 32)

    def test_provider_settings_are_master_only(self):
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.get(reverse("master-delivery-providers")).status_code, 403
        )
