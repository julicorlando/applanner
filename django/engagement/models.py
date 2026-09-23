from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class ServicePackage(TimeStampedModel):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="service_packages")
    name=models.CharField(max_length=150)
    description=models.CharField(max_length=500,blank=True)
    price=models.DecimalField(max_digits=12,decimal_places=2)
    validity_days=models.PositiveSmallIntegerField(default=30)
    active=models.BooleanField(default=True)
    recurring=models.BooleanField(default=False)

    def __str__(self):
        return self.name


class PackageItem(models.Model):
    package=models.ForeignKey(ServicePackage,on_delete=models.CASCADE,related_name="items")
    service=models.ForeignKey("scheduling.Service",on_delete=models.PROTECT,related_name="package_items")
    credits=models.PositiveSmallIntegerField(default=1)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["package","service"],name="uq_package_service")]


class CustomerPackage(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE="active","Ativo"
        EXHAUSTED="exhausted","Esgotado"
        EXPIRED="expired","Expirado"
        CANCELLED="cancelled","Cancelado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="customer_packages")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.CASCADE,related_name="packages")
    package=models.ForeignKey(ServicePackage,on_delete=models.PROTECT,related_name="customer_packages")
    purchased_at=models.DateTimeField()
    expires_at=models.DateTimeField(null=True,blank=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.ACTIVE,db_index=True)
    purchase_amount=models.DecimalField(max_digits=12,decimal_places=2)
    external_reference=models.CharField(max_length=190,blank=True)
    membership=models.ForeignKey("engagement.CustomerMembership",null=True,blank=True,on_delete=models.SET_NULL,related_name="purchased_packages")
    financial_transaction=models.OneToOneField("finance.FinancialTransaction",null=True,blank=True,on_delete=models.SET_NULL,related_name="customer_package")

    class Meta:
        indexes=[models.Index(fields=["tenant","customer","status"],name="eng_pkg_customer_idx")]


class CustomerPackageUsage(models.Model):
    customer_package=models.ForeignKey(CustomerPackage,on_delete=models.CASCADE,related_name="usages")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="package_usages")
    service=models.ForeignKey("scheduling.Service",on_delete=models.PROTECT,related_name="+")
    appointment=models.ForeignKey("scheduling.Appointment",null=True,blank=True,on_delete=models.SET_NULL,related_name="package_usages")
    credits_used=models.PositiveSmallIntegerField(default=1)
    used_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="package_usages")
    used_at=models.DateTimeField(auto_now_add=True)


class CustomerMembership(TimeStampedModel):
    class Cycle(models.TextChoices):
        MONTHLY="monthly","Mensal"
        QUARTERLY="quarterly","Trimestral"

    class Status(models.TextChoices):
        ACTIVE="active","Ativa"
        PAUSED="paused","Pausada"
        CANCELLED="cancelled","Cancelada"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="customer_memberships")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.CASCADE,related_name="memberships")
    package=models.ForeignKey(ServicePackage,on_delete=models.PROTECT,related_name="memberships")
    cycle=models.CharField(max_length=16,choices=Cycle.choices,default=Cycle.MONTHLY)
    recurring_amount=models.DecimalField(max_digits=12,decimal_places=2)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.ACTIVE,db_index=True)
    started_at=models.DateField()
    next_due_at=models.DateField(db_index=True)
    last_billed_at=models.DateField(null=True,blank=True)
    provider_subscription_id=models.CharField(max_length=190,blank=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","status","next_due_at"],name="eng_membership_due_idx")]


class TenantLoyaltySettings(models.Model):
    tenant=models.OneToOneField("tenants.Tenant",primary_key=True,on_delete=models.CASCADE,related_name="loyalty_settings")
    enabled=models.BooleanField(default=False)
    points_per_currency=models.DecimalField(max_digits=8,decimal_places=2,default=1)
    reward_points=models.PositiveIntegerField(default=100)
    reward_value=models.DecimalField(max_digits=10,decimal_places=2,default=10)
    referral_points=models.PositiveIntegerField(default=50)
    updated_at=models.DateTimeField(auto_now=True)


class LoyaltyAccount(models.Model):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="loyalty_accounts")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.CASCADE,related_name="loyalty_accounts")
    points=models.IntegerField(default=0)
    updated_at=models.DateTimeField(auto_now=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["tenant","customer"],name="uq_loyalty_account")]


class LoyaltyTransaction(models.Model):
    class Type(models.TextChoices):
        EARN="earn","Ganho"
        REDEEM="redeem","Resgate"
        ADJUST="adjust","Ajuste"
        REVERSE="reverse","Estorno"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="loyalty_transactions")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.CASCADE,related_name="loyalty_transactions")
    type=models.CharField(max_length=12,choices=Type.choices)
    points=models.IntegerField()
    source_type=models.CharField(max_length=40,blank=True)
    source_id=models.BigIntegerField(null=True,blank=True)
    note=models.CharField(max_length=255,blank=True)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="loyalty_transactions")
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","customer","created_at"],name="eng_loyalty_tx_idx")]
        constraints=[
            models.UniqueConstraint(
                fields=["tenant","customer","type","source_type","source_id"],
                condition=models.Q(source_type__gt="",source_id__isnull=False),
                name="uq_loyalty_source",
            )
        ]


class LoyaltyReward(models.Model):
    class Status(models.TextChoices):
        AVAILABLE="available","Disponível"
        REDEEMED="redeemed","Resgatado"
        CANCELLED="cancelled","Cancelado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="loyalty_rewards")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.CASCADE,related_name="loyalty_rewards")
    points_spent=models.PositiveIntegerField()
    reward_value=models.DecimalField(max_digits=10,decimal_places=2)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.AVAILABLE,db_index=True)
    issued_at=models.DateTimeField()
    redeemed_at=models.DateTimeField(null=True,blank=True)
    redeemed_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="loyalty_rewards_redeemed")

    class Meta:
        indexes=[models.Index(fields=["tenant","customer","status"],name="eng_loyalty_reward_idx")]


class LoyaltyReferral(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING="pending","Pendente"
        COMPLETED="completed","Concluída"
        CANCELLED="cancelled","Cancelada"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="loyalty_referrals")
    referrer=models.ForeignKey("scheduling.Customer",on_delete=models.CASCADE,related_name="referrals_made")
    referred=models.ForeignKey("scheduling.Customer",on_delete=models.CASCADE,related_name="referral_origin")
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.PENDING)
    reward_points=models.PositiveIntegerField()
    completed_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["tenant","referred"],name="uq_referral_referred")]


class WaitlistEntry(TimeStampedModel):
    class Period(models.TextChoices):
        ANY="any","Qualquer"
        MORNING="morning","Manhã"
        AFTERNOON="afternoon","Tarde"
        EVENING="evening","Noite"

    class Status(models.TextChoices):
        WAITING="waiting","Aguardando"
        MATCHED="matched","Encontrado"
        BOOKED="booked","Agendado"
        CANCELLED="cancelled","Cancelado"
        EXPIRED="expired","Expirado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="waitlist")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.CASCADE,related_name="waitlist_entries")
    service=models.ForeignKey("scheduling.Service",on_delete=models.CASCADE,related_name="waitlist_entries")
    professional=models.ForeignKey("scheduling.Professional",null=True,blank=True,on_delete=models.SET_NULL,related_name="waitlist_entries")
    preferred_date=models.DateField(null=True,blank=True)
    period=models.CharField(max_length=16,choices=Period.choices,default=Period.ANY)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.WAITING,db_index=True)
    notes=models.CharField(max_length=255,blank=True)
    last_notified_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","status","service","professional","preferred_date"],name="eng_waitlist_match_idx")]


class TenantDomain(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING="pending","Pendente"
        VERIFIED="verified","Verificado"
        FAILED="failed","Falhou"
        DISABLED="disabled","Desabilitado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="domains")
    domain=models.CharField(max_length=190,unique=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.PENDING,db_index=True)
    verification_token=models.CharField(max_length=64)
    verified_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","status"],name="eng_domain_status_idx")]


class ReferralProfile(TimeStampedModel):
    user=models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="referral_profile")
    referral_code=models.CharField(max_length=32,unique=True)
    active=models.BooleanField(default=True)


class ReferralVisit(models.Model):
    referrer_user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="referral_visits")
    campaign=models.ForeignKey("communications.MarketingCampaign",null=True,blank=True,on_delete=models.SET_NULL,related_name="referral_visits")
    lead=models.ForeignKey("communications.MarketingLead",null=True,blank=True,on_delete=models.SET_NULL,related_name="referral_visits")
    visit_token_hash=models.CharField(max_length=64,unique=True)
    ip_hash=models.CharField(max_length=64,blank=True)
    user_agent=models.CharField(max_length=500,blank=True)
    clicked_at=models.DateTimeField()
    converted_tenant=models.ForeignKey("tenants.Tenant",null=True,blank=True,on_delete=models.SET_NULL,related_name="referral_conversions")
    converted_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        indexes=[models.Index(fields=["referrer_user","clicked_at"],name="eng_referral_owner_idx")]


class BehaviorProfile(models.Model):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="behavior_profiles")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.CASCADE,related_name="behavior_profiles")
    avg_interval_days=models.DecimalField(max_digits=8,decimal_places=2,null=True,blank=True)
    median_interval_days=models.DecimalField(max_digits=8,decimal_places=2,null=True,blank=True)
    std_deviation_days=models.DecimalField(max_digits=8,decimal_places=2,null=True,blank=True)
    last_visit_at=models.DateTimeField(null=True,blank=True)
    next_expected_date=models.DateField(null=True,blank=True,db_index=True)
    confidence_score=models.PositiveSmallIntegerField(default=0)
    visits_count=models.PositiveIntegerField(default=0)
    intervals=models.JSONField(default=list,blank=True)
    updated_at=models.DateTimeField(auto_now=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["tenant","customer"],name="uq_behavior_customer")]
        indexes=[models.Index(fields=["tenant","next_expected_date"],name="behavior_next_idx")]


class BehaviorServiceProfile(models.Model):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="behavior_service_profiles")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.CASCADE,related_name="behavior_service_profiles")
    service=models.ForeignKey("scheduling.Service",on_delete=models.CASCADE,related_name="behavior_profiles")
    avg_interval_days=models.DecimalField(max_digits=8,decimal_places=2,null=True,blank=True)
    median_interval_days=models.DecimalField(max_digits=8,decimal_places=2,null=True,blank=True)
    std_deviation_days=models.DecimalField(max_digits=8,decimal_places=2,null=True,blank=True)
    last_visit_at=models.DateTimeField(null=True,blank=True)
    next_expected_date=models.DateField(null=True,blank=True)
    confidence_score=models.PositiveSmallIntegerField(default=0)
    visits_count=models.PositiveIntegerField(default=0)
    intervals=models.JSONField(default=list,blank=True)
    updated_at=models.DateTimeField(auto_now=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["tenant","customer","service"],name="uq_behavior_service")]
        indexes=[models.Index(fields=["tenant","next_expected_date","confidence_score"],name="behavior_service_next_idx")]


class BehaviorEvent(models.Model):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="behavior_events")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.CASCADE,related_name="behavior_events")
    event_type=models.CharField(max_length=60)
    score=models.DecimalField(max_digits=8,decimal_places=2,null=True,blank=True)
    payload=models.JSONField(default=dict,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","event_type","created_at"],name="behavior_event_type_idx")]


class PlatformAutomationLog(models.Model):
    class Channel(models.TextChoices):
        EMAIL="email","E-mail"
        WHATSAPP="whatsapp","WhatsApp"
    class Status(models.TextChoices):
        QUEUED="queued","Na fila"
        SENT="sent","Enviado"
        FAILED="failed","Falhou"
        SKIPPED="skipped","Ignorado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="automation_logs")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.CASCADE,related_name="automation_logs")
    event_type=models.CharField(max_length=60)
    channel=models.CharField(max_length=16,choices=Channel.choices)
    scheduled_for=models.DateField()
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.QUEUED)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["tenant","customer","event_type","channel","scheduled_for"],name="uq_platform_automation")]
        indexes=[models.Index(fields=["tenant","scheduled_for","status"],name="platform_automation_idx")]
