from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class DeliveryProviderSettings(TimeStampedModel):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    push_enabled = models.BooleanField(default=False)
    vapid_public_key = models.CharField(max_length=200, blank=True)
    vapid_private_encrypted = models.TextField(blank=True)
    contact_email = models.EmailField(blank=True)
    sms_enabled = models.BooleanField(default=False)
    twilio_account_sid = models.CharField(max_length=34, blank=True)
    twilio_token_encrypted = models.TextField(blank=True)
    sms_from = models.CharField(max_length=20, blank=True)


class TenantDeliverySettings(TimeStampedModel):
    tenant = models.OneToOneField("tenants.Tenant", on_delete=models.CASCADE)
    sms_enabled = models.BooleanField(default=False)
    sms_monthly_limit = models.PositiveIntegerField(default=0)


class CustomerDeliveryConsent(TimeStampedModel):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    customer = models.OneToOneField("scheduling.Customer", on_delete=models.CASCADE)
    sms_consent_at = models.DateTimeField(null=True, blank=True)
    phone_digest = models.CharField(max_length=64, blank=True)


class PushSubscription(TimeStampedModel):
    tenant = models.ForeignKey(
        "tenants.Tenant", null=True, blank=True, on_delete=models.CASCADE
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE
    )
    customer = models.ForeignKey(
        "scheduling.Customer", null=True, blank=True, on_delete=models.CASCADE
    )
    endpoint_hash = models.CharField(max_length=64)
    payload_encrypted = models.TextField()
    active = models.BooleanField(default=True)
    consent_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(user__isnull=False, customer__isnull=True)
                    | models.Q(
                        user__isnull=True, customer__isnull=False, tenant__isnull=False
                    )
                ),
                name="push_one_identity",
            ),
            models.UniqueConstraint(
                fields=["tenant", "customer", "endpoint_hash"],
                condition=models.Q(customer__isnull=False),
                name="uq_customer_push_endpoint",
            ),
            models.UniqueConstraint(
                fields=["user", "endpoint_hash"],
                condition=models.Q(user__isnull=False),
                name="uq_user_push_endpoint",
            ),
        ]


class PushDelivery(TimeStampedModel):
    subscription = models.ForeignKey(PushSubscription, on_delete=models.CASCADE)
    key = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16,
        choices=[
            ("queued", "Na fila"),
            ("sent", "Aceita pelo provedor"),
            ("failed", "Falhou"),
            ("expired", "Expirada"),
        ],
        default="queued",
        db_index=True,
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "key"], name="uq_push_delivery"
            )
        ]


class SMSDispatch(TimeStampedModel):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    notification = models.OneToOneField(
        "communications.Notification", null=True, blank=True, on_delete=models.CASCADE
    )
    key = models.CharField(max_length=64)
    state = models.CharField(max_length=16, default="queued")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "key"], name="uq_sms_event")
        ]
