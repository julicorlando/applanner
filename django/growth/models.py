from django.conf import settings
from django.db import models


class AcquisitionEvent(models.Model):
    session_key=models.CharField(max_length=40)
    event_id=models.UUIDField(unique=True)
    event_name=models.CharField(max_length=50,db_index=True)
    tenant=models.ForeignKey("tenants.Tenant",null=True,blank=True,on_delete=models.SET_NULL,related_name="acquisition_events")
    user=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="acquisition_events")
    segment=models.CharField(max_length=40,blank=True)
    source=models.CharField(max_length=100,blank=True)
    medium=models.CharField(max_length=100,blank=True)
    campaign=models.CharField(max_length=120,blank=True)
    content=models.CharField(max_length=120,blank=True)
    term=models.CharField(max_length=120,blank=True)
    event_url=models.CharField(max_length=500,blank=True)
    referrer=models.CharField(max_length=500,blank=True)
    client_ip_hash=models.CharField(max_length=64,blank=True)
    user_agent_hash=models.CharField(max_length=64,blank=True)
    marketing_consent=models.BooleanField(default=False)
    value_amount=models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)
    currency=models.CharField(max_length=3,default="BRL")
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[
            models.Index(fields=["event_name","created_at"],name="growth_funnel_idx"),
            models.Index(fields=["campaign","created_at"],name="growth_campaign_idx"),
            models.Index(fields=["session_key","created_at"],name="growth_session_idx"),
        ]


class MetaConversionLog(models.Model):
    class Status(models.TextChoices):
        QUEUED="queued","Na fila"
        SENT="sent","Enviado"
        FAILED="failed","Falhou"
        SKIPPED="skipped","Ignorado"

    event_id=models.UUIDField(unique=True)
    event_name=models.CharField(max_length=50)
    status=models.CharField(max_length=12,choices=Status.choices,default=Status.QUEUED,db_index=True)
    http_status=models.SmallIntegerField(null=True,blank=True)
    response_excerpt=models.CharField(max_length=500,blank=True)
    attempts=models.PositiveSmallIntegerField(default=0)
    sent_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)


class PublicContentTranslation(models.Model):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="public_translations")
    locale=models.CharField(max_length=10)
    content_key=models.CharField(max_length=80)
    content_value=models.TextField(blank=True)
    updated_at=models.DateTimeField(auto_now=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["tenant","locale","content_key"],name="uq_public_translation")]
