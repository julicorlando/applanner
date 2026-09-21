from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class SportsSettings(models.Model):
    class DepositType(models.TextChoices):
        FIXED="fixed","Fixo"
        PERCENT="percent","Percentual"

    tenant=models.OneToOneField("tenants.Tenant",primary_key=True,on_delete=models.CASCADE,related_name="sports_settings")
    public_enabled=models.BooleanField(default=True)
    default_slot_minutes=models.PositiveSmallIntegerField(default=60)
    minimum_notice_minutes=models.PositiveIntegerField(default=60)
    maximum_days_ahead=models.PositiveSmallIntegerField(default=90)
    cancellation_notice_minutes=models.PositiveIntegerField(default=720)
    require_deposit=models.BooleanField(default=False)
    deposit_type=models.CharField(max_length=12,choices=DepositType.choices,default=DepositType.PERCENT)
    deposit_value=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    pix_key=models.CharField(max_length=190,blank=True)
    pix_holder=models.CharField(max_length=190,blank=True)
    booking_terms=models.TextField(blank=True)
    updated_at=models.DateTimeField(auto_now=True)


class ArenaSettings(models.Model):
    tenant=models.OneToOneField("tenants.Tenant",primary_key=True,on_delete=models.CASCADE,related_name="arena_settings")
    payment_deadline_minutes=models.PositiveSmallIntegerField(default=10)
    waitlist_offer_minutes=models.PositiveSmallIntegerField(default=10)
    allow_waitlist=models.BooleanField(default=True)
    allow_games=models.BooleanField(default=True)
    dynamic_pricing_enabled=models.BooleanField(default=False)
    dynamic_min_multiplier=models.DecimalField(max_digits=6,decimal_places=3,default=0.800)
    dynamic_max_multiplier=models.DecimalField(max_digits=6,decimal_places=3,default=1.300)
    dynamic_last_minute_hours=models.PositiveSmallIntegerField(default=4)
    dynamic_last_minute_discount_percent=models.DecimalField(max_digits=6,decimal_places=2,default=10)
    dynamic_high_occupancy_threshold=models.DecimalField(max_digits=6,decimal_places=2,default=70)
    dynamic_high_occupancy_surcharge_percent=models.DecimalField(max_digits=6,decimal_places=2,default=10)
    dynamic_low_occupancy_threshold=models.DecimalField(max_digits=6,decimal_places=2,default=30)
    dynamic_low_occupancy_discount_percent=models.DecimalField(max_digits=6,decimal_places=2,default=5)
    dynamic_low_demand_window_hours=models.PositiveSmallIntegerField(default=24)
    dynamic_weekend_surcharge_percent=models.DecimalField(max_digits=6,decimal_places=2,default=0)
    dynamic_rounding_step=models.DecimalField(max_digits=8,decimal_places=2,default=0.01)
    waitlist_email_enabled=models.BooleanField(default=True)
    waitlist_whatsapp_enabled=models.BooleanField(default=False)
    reservation_reminder_enabled=models.BooleanField(default=True)
    reservation_reminder_hours=models.PositiveSmallIntegerField(default=24)
    crm_return_enabled=models.BooleanField(default=False)
    crm_return_days=models.PositiveSmallIntegerField(default=30)
    idle_slot_campaign_enabled=models.BooleanField(default=False)
    idle_slot_hours_before=models.PositiveSmallIntegerField(default=24)
    amenities=models.JSONField(default=list,blank=True)
    public_rules=models.TextField(blank=True)
    cancellation_policy=models.TextField(blank=True)
    updated_at=models.DateTimeField(auto_now=True)


class Modality(TimeStampedModel):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_modalities")
    name=models.CharField(max_length=120)
    description=models.CharField(max_length=500,blank=True)
    active=models.BooleanField(default=True)
    sort_order=models.IntegerField(default=0)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["tenant","name"],name="uq_sports_modality")]

    def __str__(self):
        return self.name


class Court(TimeStampedModel):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_courts")
    unit=models.ForeignKey("tenants.Unit",null=True,blank=True,on_delete=models.SET_NULL,related_name="sports_courts")
    name=models.CharField(max_length=150)
    slug=models.SlugField(max_length=170)
    description=models.TextField(blank=True)
    photo=models.ImageField(upload_to="arena/courts/",blank=True)
    surface=models.CharField(max_length=100,blank=True)
    indoor=models.BooleanField(default=False)
    lighting=models.BooleanField(default=False)
    capacity=models.PositiveSmallIntegerField(null=True,blank=True)
    minimum_minutes=models.PositiveSmallIntegerField(default=60)
    maximum_minutes=models.PositiveSmallIntegerField(default=180)
    interval_minutes=models.PositiveSmallIntegerField(default=0)
    active=models.BooleanField(default=True)
    sort_order=models.IntegerField(default=0)
    modalities=models.ManyToManyField(Modality,through="CourtModality",related_name="courts",blank=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["tenant","slug"],name="uq_sports_court_slug")]
        indexes=[models.Index(fields=["tenant","unit","active"],name="arena_court_unit_idx")]

    def __str__(self):
        return self.name


class CourtModality(models.Model):
    court=models.ForeignKey(Court,on_delete=models.CASCADE)
    modality=models.ForeignKey(Modality,on_delete=models.CASCADE)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["court","modality"],name="uq_court_modality")]


class CourtHours(TimeStampedModel):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_court_hours")
    court=models.ForeignKey(Court,on_delete=models.CASCADE,related_name="hours")
    weekday=models.PositiveSmallIntegerField()
    start_time=models.TimeField()
    end_time=models.TimeField()
    active=models.BooleanField(default=True)

    class Meta:
        constraints=[
            models.UniqueConstraint(fields=["court","weekday","start_time","end_time"],name="uq_sports_hours"),
            models.CheckConstraint(condition=models.Q(weekday__gte=1,weekday__lte=7),name="sports_hours_weekday_iso"),
            models.CheckConstraint(condition=models.Q(end_time__gt=models.F("start_time")),name="sports_hours_end_after_start"),
        ]
        indexes=[models.Index(fields=["court","weekday","active"],name="arena_hours_lookup_idx")]


class PriceRule(TimeStampedModel):
    class RuleType(models.TextChoices):
        STANDARD="standard","Padrão"
        HOLIDAY="holiday","Feriado"
        SPECIAL="special","Especial"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_price_rules")
    court=models.ForeignKey(Court,on_delete=models.CASCADE,related_name="price_rules")
    modality=models.ForeignKey(Modality,null=True,blank=True,on_delete=models.CASCADE,related_name="price_rules")
    weekday=models.PositiveSmallIntegerField(null=True,blank=True)
    start_time=models.TimeField(null=True,blank=True)
    end_time=models.TimeField(null=True,blank=True)
    price_per_hour=models.DecimalField(max_digits=10,decimal_places=2)
    priority=models.SmallIntegerField(default=0)
    active=models.BooleanField(default=True)
    rule_type=models.CharField(max_length=12,choices=RuleType.choices,default=RuleType.STANDARD)
    specific_date=models.DateField(null=True,blank=True)
    valid_from=models.DateField(null=True,blank=True)
    valid_to=models.DateField(null=True,blank=True)
    minimum_duration_minutes=models.PositiveSmallIntegerField(null=True,blank=True)
    maximum_duration_minutes=models.PositiveSmallIntegerField(null=True,blank=True)
    label=models.CharField(max_length=160,blank=True)

    class Meta:
        indexes=[models.Index(fields=["court","active","weekday","priority"],name="arena_price_lookup_idx")]


class CourtBlock(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE="active","Ativo"
        CANCELLED="cancelled","Cancelado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_court_blocks")
    court=models.ForeignKey(Court,on_delete=models.CASCADE,related_name="blocks")
    starts_at=models.DateTimeField()
    ends_at=models.DateTimeField()
    reason=models.CharField(max_length=300,blank=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.ACTIVE)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="sports_blocks_created")

    class Meta:
        indexes=[models.Index(fields=["court","status","starts_at","ends_at"],name="arena_block_range_idx")]
        constraints=[models.CheckConstraint(condition=models.Q(ends_at__gt=models.F("starts_at")),name="sports_block_end_after_start")]


class Reservation(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING_PAYMENT="pending_payment","Aguardando pagamento"
        CONFIRMED="confirmed","Confirmada"
        COMPLETED="completed","Concluída"
        CANCELLED="cancelled","Cancelada"
        NO_SHOW="no_show","Não compareceu"

    class PaymentStatus(models.TextChoices):
        NOT_REQUIRED="not_required","Não exigido"
        PENDING="pending","Pendente"
        PAID="paid","Pago"
        REFUNDED="refunded","Estornado"
        CANCELLED="cancelled","Cancelado"

    class Source(models.TextChoices):
        PUBLIC="public","Público"
        INTERNAL="internal","Interno"
        RECURRING="recurring","Recorrente"

    public_id=models.CharField(max_length=32,unique=True)
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_reservations")
    court=models.ForeignKey(Court,on_delete=models.PROTECT,related_name="reservations")
    modality=models.ForeignKey(Modality,null=True,blank=True,on_delete=models.SET_NULL,related_name="reservations")
    customer=models.ForeignKey("scheduling.Customer",null=True,blank=True,on_delete=models.SET_NULL,related_name="sports_reservations")
    customer_name=models.CharField(max_length=160)
    customer_phone=models.CharField(max_length=30)
    customer_email=models.EmailField(blank=True)
    starts_at=models.DateTimeField()
    ends_at=models.DateTimeField()
    duration_minutes=models.PositiveSmallIntegerField()
    price_per_hour=models.DecimalField(max_digits=10,decimal_places=2)
    total_amount=models.DecimalField(max_digits=12,decimal_places=2)
    base_total_amount=models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)
    pricing_multiplier=models.DecimalField(max_digits=8,decimal_places=4,default=1)
    pricing_details=models.JSONField(default=dict,blank=True)
    deposit_amount=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    status=models.CharField(max_length=20,choices=Status.choices,default=Status.CONFIRMED,db_index=True)
    payment_method=models.CharField(max_length=20,default="onsite")
    payment_status=models.CharField(max_length=20,choices=PaymentStatus.choices,default=PaymentStatus.NOT_REQUIRED)
    manage_token_hash=models.CharField(max_length=64,unique=True)
    recurrence_group=models.CharField(max_length=32,blank=True)
    source=models.CharField(max_length=16,choices=Source.choices,default=Source.PUBLIC)
    notes=models.CharField(max_length=1000,blank=True)
    terms_accepted_at=models.DateTimeField(null=True,blank=True)
    confirmed_at=models.DateTimeField(null=True,blank=True)
    cancelled_at=models.DateTimeField(null=True,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="sports_reservations_created")

    class Meta:
        indexes=[
            models.Index(fields=["court","status","starts_at","ends_at"],name="arena_res_calendar_idx"),
            models.Index(fields=["tenant","status","starts_at"],name="arena_res_tenant_idx"),
        ]
        constraints=[models.CheckConstraint(condition=models.Q(ends_at__gt=models.F("starts_at")),name="sports_res_end_after_start")]


class ReservationFinance(TimeStampedModel):
    class State(models.TextChoices):
        NOT_REQUIRED="not_required","Não exigido"
        PENDING="pending","Pendente"
        PARTIAL="partial","Parcial"
        PAID="paid","Pago"
        EXPIRED="expired","Expirado"
        CANCELLED="cancelled","Cancelado"
        REFUNDED="refunded","Estornado"
        PARTIALLY_REFUNDED="partially_refunded","Parcialmente estornado"
        FAILED="failed","Falhou"

    reservation=models.OneToOneField(Reservation,primary_key=True,on_delete=models.CASCADE,related_name="finance")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_reservation_finance")
    payment_state=models.CharField(max_length=24,choices=State.choices,default=State.NOT_REQUIRED,db_index=True)
    gross_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    deposit_due=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    amount_paid=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    amount_refunded=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    fee_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    net_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    provider=models.CharField(max_length=40,blank=True)
    external_reference=models.CharField(max_length=190,blank=True)
    transaction_id=models.CharField(max_length=190,blank=True)
    expires_at=models.DateTimeField(null=True,blank=True)
    paid_at=models.DateTimeField(null=True,blank=True)
    reconciled_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        constraints=[
            models.UniqueConstraint(
                fields=["tenant","provider","external_reference"],
                condition=~models.Q(external_reference=""),
                name="uq_arena_finance_provider_ref",
            )
        ]
        indexes=[models.Index(fields=["tenant","payment_state","expires_at"],name="arena_finance_state_idx")]


class ReservationHistory(models.Model):
    reservation=models.ForeignKey(Reservation,on_delete=models.CASCADE,related_name="history")
    action=models.CharField(max_length=60)
    old_status=models.CharField(max_length=40,blank=True)
    new_status=models.CharField(max_length=40,blank=True)
    notes=models.CharField(max_length=500,blank=True)
    actor_user=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="+")
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["reservation","created_at"],name="arena_res_history_idx")]
