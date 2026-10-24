"""Beauty operations reuse the canonical agenda and company WhatsApp."""

from django.db import models
from core.models import TimeStampedModel


class BeautySettings(TimeStampedModel):
    tenant = models.OneToOneField("tenants.Tenant", on_delete=models.CASCADE)
    booking_assistant = models.BooleanField(default=False)
    recovery_enabled = models.BooleanField(default=False)


class SalonResource(TimeStampedModel):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    unit = models.ForeignKey("tenants.Unit", on_delete=models.PROTECT)
    name = models.CharField(max_length=120)
    kind = models.CharField(
        max_length=20,
        choices=[("chair", "Cadeira"), ("wash", "Lavatório"), ("other", "Outro")],
    )
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class ServiceStage(models.Model):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    service = models.ForeignKey(
        "scheduling.Service", on_delete=models.CASCADE, related_name="stages"
    )
    position = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=120)
    minutes = models.PositiveSmallIntegerField()
    professional_required = models.BooleanField(default=True)
    resource = models.ForeignKey(
        SalonResource, null=True, blank=True, on_delete=models.PROTECT
    )

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["service", "position"], name="uq_beauty_stage_position"
            )
        ]


class StageReservation(models.Model):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    appointment = models.ForeignKey(
        "scheduling.Appointment",
        on_delete=models.CASCADE,
        related_name="stage_reservations",
    )
    name = models.CharField(max_length=120)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    professional = models.ForeignKey(
        "scheduling.Professional", null=True, blank=True, on_delete=models.PROTECT
    )
    resource = models.ForeignKey(
        SalonResource, null=True, blank=True, on_delete=models.PROTECT
    )


class RecoveryOffer(TimeStampedModel):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    cancelled_appointment = models.ForeignKey(
        "scheduling.Appointment",
        on_delete=models.PROTECT,
        related_name="recovery_offers",
    )
    appointment = models.OneToOneField(
        "scheduling.Appointment",
        on_delete=models.PROTECT,
        related_name="recovery_offer",
    )
    entry = models.ForeignKey("engagement.WaitlistEntry", on_delete=models.PROTECT)
    token_hash = models.CharField(max_length=64, unique=True)
    token_encrypted = models.TextField()
    expires_at = models.DateTimeField()
    status = models.CharField(
        max_length=16,
        default="held",
        choices=[
            ("held", "Reservado"),
            ("accepted", "Aceito"),
            ("expired", "Expirado"),
            ("cancelled", "Cancelado"),
        ],
    )
    sent_at = models.DateTimeField(null=True, blank=True)
