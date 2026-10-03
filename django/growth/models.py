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


class ReferralCampaign(models.Model):
    class RewardType(models.TextChoices):
        FIXED="fixed","Valor fixo"
        PERCENT="percent","Percentual"

    name=models.CharField(max_length=160)
    active=models.BooleanField(default=False,db_index=True)
    company_reward_type=models.CharField(max_length=12,choices=RewardType.choices,default=RewardType.FIXED)
    company_reward_value=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    professional_reward_amount=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    payment_threshold=models.PositiveSmallIntegerField(default=2)
    starts_at=models.DateTimeField(null=True,blank=True)
    ends_at=models.DateTimeField(null=True,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="referral_campaigns_created")
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class PlatformReferral(models.Model):
    class Status(models.TextChoices):
        PENDING="pending","Aguardando pagamentos"
        QUALIFIED="qualified","Qualificada"
        AWAITING_PIX="awaiting_pix","Aguardando chave Pix"
        READY="ready","Pronta para pagamento"
        PAID="paid","Paga"
        CANCELLED="cancelled","Cancelada"

    campaign=models.ForeignKey(ReferralCampaign,on_delete=models.PROTECT,related_name="referrals")
    referrer_user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="platform_referrals")
    referrer_tenant=models.ForeignKey("tenants.Tenant",null=True,blank=True,on_delete=models.SET_NULL,related_name="referrals_made")
    referrer_professional=models.ForeignKey("scheduling.Professional",null=True,blank=True,on_delete=models.SET_NULL,related_name="platform_referrals")
    referred_tenant=models.OneToOneField("tenants.Tenant",on_delete=models.CASCADE,related_name="platform_referral")
    code_snapshot=models.CharField(max_length=32)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.PENDING,db_index=True)
    payment_count=models.PositiveSmallIntegerField(default=0)
    company_discount_amount=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    professional_reward_amount=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    pix_key_encrypted=models.TextField(blank=True)
    pix_requested_at=models.DateTimeField(null=True,blank=True)
    qualified_at=models.DateTimeField(null=True,blank=True)
    paid_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)

    class Meta:
        indexes=[models.Index(fields=["status","created_at"],name="growth_ref_status_idx")]

    @property
    def pix_key_display(self):
        if not self.pix_key_encrypted:
            return ""
        from core.crypto import decrypt_text
        try:
            return decrypt_text(self.pix_key_encrypted)
        except Exception:
            return "Não foi possível descriptografar"

    def __str__(self):
        return f"{self.referrer_user} → {self.referred_tenant}"


class ReferralPaymentCredit(models.Model):
    referral=models.ForeignKey(PlatformReferral,on_delete=models.CASCADE,related_name="payment_credits")
    payment=models.OneToOneField("billing.Payment",on_delete=models.CASCADE,related_name="referral_credit")
    created_at=models.DateTimeField(auto_now_add=True)

