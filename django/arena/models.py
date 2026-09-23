from decimal import Decimal
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
    dynamic_min_multiplier=models.DecimalField(max_digits=6,decimal_places=3,default=Decimal("0.800"))
    dynamic_max_multiplier=models.DecimalField(max_digits=6,decimal_places=3,default=Decimal("1.300"))
    dynamic_last_minute_hours=models.PositiveSmallIntegerField(default=4)
    dynamic_last_minute_discount_percent=models.DecimalField(max_digits=6,decimal_places=2,default=10)
    dynamic_high_occupancy_threshold=models.DecimalField(max_digits=6,decimal_places=2,default=70)
    dynamic_high_occupancy_surcharge_percent=models.DecimalField(max_digits=6,decimal_places=2,default=10)
    dynamic_low_occupancy_threshold=models.DecimalField(max_digits=6,decimal_places=2,default=30)
    dynamic_low_occupancy_discount_percent=models.DecimalField(max_digits=6,decimal_places=2,default=5)
    dynamic_low_demand_window_hours=models.PositiveSmallIntegerField(default=24)
    dynamic_weekend_surcharge_percent=models.DecimalField(max_digits=6,decimal_places=2,default=0)
    dynamic_rounding_step=models.DecimalField(max_digits=8,decimal_places=2,default=Decimal("0.01"))
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
        PARTIAL="partial","Parcial"
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
    legacy_tournament_match_id=models.BigIntegerField(null=True,blank=True,db_index=True)
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


class Membership(TimeStampedModel):
    class Frequency(models.TextChoices):
        WEEKLY="weekly","Semanal"
        BIWEEKLY="biweekly","Quinzenal"
        MONTHLY="monthly","Mensal"

    class Status(models.TextChoices):
        ACTIVE="active","Ativo"
        PAUSED="paused","Pausado"
        CANCELLED="cancelled","Cancelado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_memberships")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.PROTECT,related_name="sports_memberships")
    court=models.ForeignKey(Court,on_delete=models.PROTECT,related_name="memberships")
    modality=models.ForeignKey(Modality,null=True,blank=True,on_delete=models.SET_NULL,related_name="memberships")
    name=models.CharField(max_length=160)
    frequency=models.CharField(max_length=16,choices=Frequency.choices,default=Frequency.WEEKLY)
    weekday=models.PositiveSmallIntegerField(null=True,blank=True)
    day_of_month=models.PositiveSmallIntegerField(null=True,blank=True)
    start_time=models.TimeField()
    duration_minutes=models.PositiveSmallIntegerField(default=60)
    monthly_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    start_date=models.DateField()
    end_date=models.DateField(null=True,blank=True)
    next_generation_date=models.DateField(null=True,blank=True)
    generate_days_ahead=models.PositiveSmallIntegerField(default=60)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.ACTIVE,db_index=True)
    notes=models.CharField(max_length=1000,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="sports_memberships_created")

    class Meta:
        indexes=[models.Index(fields=["tenant","status","next_generation_date"],name="arena_membership_gen_idx")]


class MembershipConflict(models.Model):
    membership=models.ForeignKey(Membership,on_delete=models.CASCADE,related_name="conflicts")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_membership_conflicts")
    occurrence_date=models.DateField()
    starts_at=models.DateTimeField()
    reason=models.CharField(max_length=300)
    resolved_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["membership","starts_at"],name="uq_membership_conflict")]
        indexes=[models.Index(fields=["tenant","resolved_at","occurrence_date"],name="arena_membership_conflict_idx")]


class MembershipReservation(models.Model):
    membership=models.ForeignKey(Membership,on_delete=models.CASCADE,related_name="reservation_links")
    reservation=models.OneToOneField(Reservation,on_delete=models.CASCADE,related_name="membership_link")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_membership_reservations")
    occurrence_date=models.DateField()
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["membership","occurrence_date"],name="uq_membership_occurrence")]


class Game(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT="draft","Rascunho"
        OPEN="open","Aberto"
        CONFIRMED="confirmed","Confirmado"
        COMPLETED="completed","Concluído"
        CANCELLED="cancelled","Cancelado"

    public_token=models.CharField(max_length=32,unique=True)
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_games")
    reservation=models.ForeignKey(Reservation,null=True,blank=True,on_delete=models.SET_NULL,related_name="games")
    court=models.ForeignKey(Court,on_delete=models.PROTECT,related_name="games")
    modality=models.ForeignKey(Modality,null=True,blank=True,on_delete=models.SET_NULL,related_name="games")
    name=models.CharField(max_length=160)
    starts_at=models.DateTimeField()
    ends_at=models.DateTimeField()
    total_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    max_players=models.PositiveSmallIntegerField()
    minimum_players=models.PositiveSmallIntegerField(default=1)
    split_payment=models.BooleanField(default=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.OPEN,db_index=True)
    rules=models.CharField(max_length=1000,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="sports_games_created")

    class Meta:
        indexes=[models.Index(fields=["tenant","status","starts_at"],name="arena_game_status_idx")]
        constraints=[models.CheckConstraint(condition=models.Q(ends_at__gt=models.F("starts_at")),name="sports_game_end_after_start")]


class GamePlayer(TimeStampedModel):
    class ParticipationStatus(models.TextChoices):
        INVITED="invited","Convidado"
        CONFIRMED="confirmed","Confirmado"
        CANCELLED="cancelled","Cancelado"

    class PaymentStatus(models.TextChoices):
        PENDING="pending","Pendente"
        PAID="paid","Pago"
        CANCELLED="cancelled","Cancelado"
        REFUNDED="refunded","Estornado"

    game=models.ForeignKey(Game,on_delete=models.CASCADE,related_name="players")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_game_players")
    customer=models.ForeignKey("scheduling.Customer",null=True,blank=True,on_delete=models.SET_NULL,related_name="sports_game_entries")
    name=models.CharField(max_length=160)
    phone=models.CharField(max_length=30)
    email=models.EmailField(blank=True)
    share_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    amount_paid=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    participation_status=models.CharField(max_length=16,choices=ParticipationStatus.choices,default=ParticipationStatus.CONFIRMED)
    payment_status=models.CharField(max_length=16,choices=PaymentStatus.choices,default=PaymentStatus.PENDING)
    manage_token_hash=models.CharField(max_length=64,unique=True)
    provider=models.CharField(max_length=40,blank=True)
    provider_reference=models.CharField(max_length=190,blank=True)
    confirmed_at=models.DateTimeField(null=True,blank=True)
    paid_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        indexes=[
            models.Index(fields=["game","participation_status","payment_status"],name="arena_game_player_idx"),
            models.Index(fields=["tenant","phone"],name="arena_game_phone_idx"),
        ]


class WaitlistEntry(TimeStampedModel):
    class Status(models.TextChoices):
        WAITING="waiting","Aguardando"
        OFFERED="offered","Ofertado"
        CONVERTED="converted","Convertido"
        EXPIRED="expired","Expirado"
        CANCELLED="cancelled","Cancelado"

    public_token=models.CharField(max_length=32,unique=True)
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_waitlist")
    customer=models.ForeignKey("scheduling.Customer",null=True,blank=True,on_delete=models.SET_NULL,related_name="sports_waitlist_entries")
    court=models.ForeignKey(Court,null=True,blank=True,on_delete=models.SET_NULL,related_name="waitlist_entries")
    modality=models.ForeignKey(Modality,null=True,blank=True,on_delete=models.SET_NULL,related_name="waitlist_entries")
    customer_name=models.CharField(max_length=160)
    customer_phone=models.CharField(max_length=30)
    customer_email=models.EmailField(blank=True)
    notify_email=models.BooleanField(default=True)
    notify_whatsapp=models.BooleanField(default=False)
    preferred_date=models.DateField()
    preferred_start=models.TimeField(null=True,blank=True)
    preferred_end=models.TimeField(null=True,blank=True)
    flexibility_minutes=models.PositiveSmallIntegerField(default=0)
    duration_minutes=models.PositiveSmallIntegerField(default=60)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.WAITING,db_index=True)
    offer_expires_at=models.DateTimeField(null=True,blank=True)
    offered_at=models.DateTimeField(null=True,blank=True)
    offered_starts_at=models.DateTimeField(null=True,blank=True)
    offered_total=models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)
    notification_queued_at=models.DateTimeField(null=True,blank=True)
    last_notification_at=models.DateTimeField(null=True,blank=True)
    converted_reservation=models.ForeignKey(Reservation,null=True,blank=True,on_delete=models.SET_NULL,related_name="waitlist_conversions")
    notes=models.CharField(max_length=500,blank=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","status","preferred_date","court","modality"],name="arena_waitlist_match_idx")]


class SportsClass(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE="active","Ativa"
        PAUSED="paused","Pausada"
        CANCELLED="cancelled","Cancelada"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_classes")
    court=models.ForeignKey(Court,on_delete=models.PROTECT,related_name="classes")
    modality=models.ForeignKey(Modality,null=True,blank=True,on_delete=models.SET_NULL,related_name="classes")
    teacher_name=models.CharField(max_length=160)
    name=models.CharField(max_length=160)
    level=models.CharField(max_length=100,blank=True)
    weekday=models.PositiveSmallIntegerField()
    start_time=models.TimeField()
    duration_minutes=models.PositiveSmallIntegerField(default=60)
    capacity=models.PositiveSmallIntegerField(default=1)
    monthly_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.ACTIVE,db_index=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","status","weekday","start_time"],name="arena_class_schedule_idx")]
        constraints=[models.CheckConstraint(condition=models.Q(weekday__gte=1,weekday__lte=7),name="sports_class_weekday_iso")]


class ClassStudent(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE="active","Ativo"
        PAUSED="paused","Pausado"
        CANCELLED="cancelled","Cancelado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_class_students")
    sports_class=models.ForeignKey(SportsClass,on_delete=models.CASCADE,related_name="students")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.PROTECT,related_name="sports_classes")
    responsible_name=models.CharField(max_length=160,blank=True)
    responsible_phone=models.CharField(max_length=30,blank=True)
    monthly_amount_override=models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)
    billing_day=models.PositiveSmallIntegerField(null=True,blank=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.ACTIVE)
    joined_at=models.DateField()

    class Meta:
        constraints=[models.UniqueConstraint(fields=["sports_class","customer"],name="uq_class_student")]


class ClassAttendance(models.Model):
    class Status(models.TextChoices):
        PRESENT="present","Presente"
        ABSENT="absent","Ausente"
        EXCUSED="excused","Justificada"
        REPLACEMENT="replacement","Reposição"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_class_attendance")
    sports_class=models.ForeignKey(SportsClass,on_delete=models.CASCADE,related_name="attendance")
    student=models.ForeignKey(ClassStudent,on_delete=models.CASCADE,related_name="attendance")
    class_date=models.DateField()
    status=models.CharField(max_length=16,choices=Status.choices)
    notes=models.CharField(max_length=300,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["student","class_date"],name="uq_class_attendance")]
        indexes=[models.Index(fields=["sports_class","class_date"],name="arena_class_attendance_idx")]


class Tournament(TimeStampedModel):
    class Format(models.TextChoices):
        GROUPS="groups","Grupos"
        KNOCKOUT="knockout","Mata-mata"
        GROUPS_KNOCKOUT="groups_knockout","Grupos + mata-mata"

    class Status(models.TextChoices):
        DRAFT="draft","Rascunho"
        REGISTRATION="registration","Inscrições"
        RUNNING="running","Em andamento"
        COMPLETED="completed","Concluído"
        CANCELLED="cancelled","Cancelado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_tournaments")
    modality=models.ForeignKey(Modality,null=True,blank=True,on_delete=models.SET_NULL,related_name="tournaments")
    name=models.CharField(max_length=160)
    category=models.CharField(max_length=120,blank=True)
    format=models.CharField(max_length=24,choices=Format.choices,default=Format.GROUPS_KNOCKOUT)
    registration_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    starts_on=models.DateField()
    ends_on=models.DateField(null=True,blank=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.DRAFT,db_index=True)
    champion_team=models.ForeignKey("TournamentTeam",null=True,blank=True,on_delete=models.SET_NULL,related_name="championships")

    class Meta:
        indexes=[models.Index(fields=["tenant","status","starts_on"],name="arena_tournament_status_idx")]


class TournamentTeam(models.Model):
    tournament=models.ForeignKey(Tournament,on_delete=models.CASCADE,related_name="teams")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_tournament_teams")
    name=models.CharField(max_length=160)
    group_name=models.CharField(max_length=40,blank=True)
    captain_customer=models.ForeignKey("scheduling.Customer",null=True,blank=True,on_delete=models.SET_NULL,related_name="captained_teams")
    payment_status=models.CharField(max_length=16,default="pending")
    amount_paid=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["tournament","name"],name="uq_tournament_team_name")]


class TournamentMatch(TimeStampedModel):
    class Status(models.TextChoices):
        SCHEDULED="scheduled","Agendada"
        RUNNING="running","Em andamento"
        COMPLETED="completed","Concluída"
        CANCELLED="cancelled","Cancelada"

    tournament=models.ForeignKey(Tournament,on_delete=models.CASCADE,related_name="matches")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_tournament_matches")
    court=models.ForeignKey(Court,null=True,blank=True,on_delete=models.SET_NULL,related_name="tournament_matches")
    home_team=models.ForeignKey(TournamentTeam,null=True,blank=True,on_delete=models.SET_NULL,related_name="home_matches")
    away_team=models.ForeignKey(TournamentTeam,null=True,blank=True,on_delete=models.SET_NULL,related_name="away_matches")
    phase=models.CharField(max_length=80)
    group_name=models.CharField(max_length=40,blank=True)
    round_number=models.PositiveSmallIntegerField(null=True,blank=True)
    starts_at=models.DateTimeField(null=True,blank=True)
    reservation=models.ForeignKey(Reservation,null=True,blank=True,on_delete=models.SET_NULL,related_name="tournament_matches")
    home_score=models.SmallIntegerField(null=True,blank=True)
    away_score=models.SmallIntegerField(null=True,blank=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.SCHEDULED,db_index=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","starts_at","court","status"],name="arena_match_schedule_idx")]


class ClassMakeup(TimeStampedModel):
    class Status(models.TextChoices):
        CREDIT="credit","Crédito"
        SCHEDULED="scheduled","Agendada"
        USED="used","Utilizada"
        CANCELLED="cancelled","Cancelada"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_class_makeups")
    student=models.ForeignKey(ClassStudent,on_delete=models.CASCADE,related_name="makeups")
    original_class=models.ForeignKey(SportsClass,on_delete=models.CASCADE,related_name="makeups_origin")
    original_date=models.DateField()
    replacement_class=models.ForeignKey(SportsClass,null=True,blank=True,on_delete=models.SET_NULL,related_name="makeups_replacement")
    replacement_date=models.DateField(null=True,blank=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.CREDIT,db_index=True)
    notes=models.CharField(max_length=300,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="sports_makeups_created")

    class Meta:
        indexes=[models.Index(fields=["tenant","student","status","original_date"],name="arena_makeup_student_idx")]


class ClassBillingLog(models.Model):
    class Status(models.TextChoices):
        GENERATED="generated","Gerada"
        SKIPPED="skipped","Ignorada"
        CANCELLED="cancelled","Cancelada"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_class_billing_logs")
    student=models.ForeignKey(ClassStudent,on_delete=models.CASCADE,related_name="billing_logs")
    competence_month=models.CharField(max_length=7)
    amount=models.DecimalField(max_digits=12,decimal_places=2)
    financial_transaction=models.ForeignKey("finance.FinancialTransaction",null=True,blank=True,on_delete=models.SET_NULL,related_name="sports_class_billing_logs")
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.GENERATED)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["student","competence_month"],name="uq_class_billing_month")]
        indexes=[models.Index(fields=["tenant","competence_month","status"],name="arena_class_billing_idx")]


class DynamicPricingAudit(models.Model):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_dynamic_pricing_audits")
    reservation=models.OneToOneField(Reservation,on_delete=models.CASCADE,related_name="dynamic_pricing_audit")
    base_total=models.DecimalField(max_digits=12,decimal_places=2)
    final_total=models.DecimalField(max_digits=12,decimal_places=2)
    multiplier=models.DecimalField(max_digits=8,decimal_places=4)
    details=models.JSONField(default=dict,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","created_at"],name="arena_dynamic_audit_idx")]


class TournamentTeamPlayer(models.Model):
    team=models.ForeignKey(TournamentTeam,on_delete=models.CASCADE,related_name="players")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.PROTECT,related_name="tournament_teams")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_tournament_players")
    jersey_number=models.PositiveSmallIntegerField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["team","customer"],name="uq_tournament_team_player")]


class TournamentEvent(models.Model):
    tournament=models.ForeignKey(Tournament,on_delete=models.CASCADE,related_name="events")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_tournament_events")
    event_type=models.CharField(max_length=50)
    detail=models.CharField(max_length=500,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="sports_tournament_events")
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["tournament","created_at"],name="arena_tournament_event_idx")]


class CustomerMetric(models.Model):
    class Segment(models.TextChoices):
        NEW="new","Novo"
        RECURRING="recurring","Recorrente"
        VIP="vip","VIP"
        INACTIVE="inactive","Inativo"
        CHURN_RISK="churn_risk","Risco de churn"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_customer_metrics")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.CASCADE,related_name="sports_metrics")
    last_reservation_at=models.DateTimeField(null=True,blank=True)
    reservation_count=models.PositiveIntegerField(default=0)
    cancellation_count=models.PositiveIntegerField(default=0)
    no_show_count=models.PositiveIntegerField(default=0)
    total_spent=models.DecimalField(max_digits=14,decimal_places=2,default=0)
    average_ticket=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    favorite_court=models.ForeignKey(Court,null=True,blank=True,on_delete=models.SET_NULL,related_name="+")
    favorite_modality=models.ForeignKey(Modality,null=True,blank=True,on_delete=models.SET_NULL,related_name="+")
    is_membership=models.BooleanField(default=False)
    game_count=models.PositiveIntegerField(default=0)
    segment=models.CharField(max_length=16,choices=Segment.choices,default=Segment.NEW,db_index=True)
    updated_at=models.DateTimeField(auto_now=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["tenant","customer"],name="uq_arena_customer_metric")]
        indexes=[models.Index(fields=["tenant","segment","last_reservation_at"],name="arena_customer_segment_idx")]


class AutomationLog(models.Model):
    class Status(models.TextChoices):
        SKIPPED="skipped","Ignorado"
        QUEUED="queued","Na fila"
        SENT="sent","Enviado"
        FAILED="failed","Falhou"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_automation_logs")
    automation_key=models.CharField(max_length=80)
    entity_type=models.CharField(max_length=60,blank=True)
    entity_id=models.BigIntegerField(null=True,blank=True)
    channel=models.CharField(max_length=20,blank=True)
    status=models.CharField(max_length=16,choices=Status.choices)
    detail=models.CharField(max_length=500,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","automation_key","created_at"],name="arena_automation_idx")]


class ArenaCommand(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN="open","Aberta"
        CLOSED="closed","Fechada"
        CANCELLED="cancelled","Cancelada"

    class PaymentStatus(models.TextChoices):
        PENDING="pending","Pendente"
        PAID="paid","Pago"
        PARTIAL="partial","Parcial"
        CANCELLED="cancelled","Cancelado"

    public_id=models.CharField(max_length=32,unique=True)
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_commands")
    reservation=models.ForeignKey(Reservation,null=True,blank=True,on_delete=models.SET_NULL,related_name="commands")
    customer=models.ForeignKey("scheduling.Customer",null=True,blank=True,on_delete=models.SET_NULL,related_name="sports_commands")
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.OPEN,db_index=True)
    subtotal=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    discount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    surcharge=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    total=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    payment_method=models.CharField(max_length=40,blank=True)
    payment_status=models.CharField(max_length=16,choices=PaymentStatus.choices,default=PaymentStatus.PENDING)
    notes=models.CharField(max_length=500,blank=True)
    opened_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="sports_commands_opened")
    closed_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="sports_commands_closed")
    opened_at=models.DateTimeField()
    closed_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","status","opened_at"],name="arena_command_status_idx")]


class ArenaCommandItem(models.Model):
    command=models.ForeignKey(ArenaCommand,on_delete=models.CASCADE,related_name="items")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_command_items")
    product=models.ForeignKey("finance.Product",null=True,blank=True,on_delete=models.SET_NULL,related_name="sports_command_items")
    description=models.CharField(max_length=190)
    quantity=models.DecimalField(max_digits=12,decimal_places=3)
    unit_price=models.DecimalField(max_digits=12,decimal_places=2)
    cost_snapshot=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    total=models.DecimalField(max_digits=12,decimal_places=2)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["command"],name="arena_command_item_idx")]


class ArenaCommandStockMovement(models.Model):
    class Type(models.TextChoices):
        COMMAND_CLOSE="command_close","Fechamento de comanda"
        COMMAND_REVERSAL="command_reversal","Estorno de comanda"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sports_command_stock_movements")
    command=models.ForeignKey(ArenaCommand,on_delete=models.CASCADE,related_name="stock_movements")
    product=models.ForeignKey("finance.Product",on_delete=models.PROTECT,related_name="sports_command_stock_movements")
    quantity=models.DecimalField(max_digits=12,decimal_places=3)
    balance_after=models.DecimalField(max_digits=12,decimal_places=3)
    movement_type=models.CharField(max_length=24,choices=Type.choices)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints=[
            models.UniqueConstraint(
                fields=["command","product","movement_type"],
                name="uq_arena_command_stock",
            )
        ]
