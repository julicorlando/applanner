"""Optional waiting room display and replay-safe offline writes. No clinical plaintext."""
import secrets
from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


def screen_token():
    return secrets.token_urlsafe(16)


class WaitingRoomDisplay(TimeStampedModel):
    tenant = models.OneToOneField('tenants.Tenant', on_delete=models.CASCADE, related_name='waiting_room_display')
    token = models.CharField(max_length=32, unique=True, default=screen_token)
    enabled = models.BooleanField(default=False)
    title = models.CharField(max_length=100, default='Sala de espera')
    voice_enabled = models.BooleanField(default=False)
    show_full_name = models.BooleanField(default=False)
    retention_minutes = models.PositiveSmallIntegerField(default=30)


class WaitingRoomMedia(TimeStampedModel):
    display = models.ForeignKey(WaitingRoomDisplay, on_delete=models.CASCADE, related_name='media')
    title = models.CharField(max_length=100)
    mime = models.CharField(max_length=30)
    file = models.FileField(upload_to='waiting-room-private/')
    active = models.BooleanField(default=True)


class WaitingRoomCall(TimeStampedModel):
    display = models.ForeignKey(WaitingRoomDisplay, on_delete=models.PROTECT, related_name='calls')
    appointment = models.ForeignKey('scheduling.Appointment', on_delete=models.PROTECT)
    called_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    label_encrypted = models.TextField()
    room = models.CharField(max_length=60)
    expires_at = models.DateTimeField(db_index=True)
    request_id = models.UUIDField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['display', 'request_id'], name='uq_waiting_call_request')]
        indexes = [models.Index(fields=['display', '-created_at'], name='waiting_display_recent_idx')]


class OfflineOperation(TimeStampedModel):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_id = models.UUIDField()
    kind = models.CharField(max_length=30)
    fingerprint = models.CharField(max_length=64)
    result = models.JSONField(default=dict)  # Only object IDs and replay metadata, never clinical text or contacts.

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'user', 'request_id'], name='uq_clinical_offline_request')]
