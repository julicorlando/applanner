from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class Customer(TimeStampedModel):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="customers")
    name=models.CharField(max_length=150)
    phone=models.CharField(max_length=32,blank=True)
    email=models.EmailField(blank=True)
    birth_date=models.DateField(null=True,blank=True)
    consent_marketing=models.BooleanField(default=False)
    active=models.BooleanField(default=True)

    class Meta:
        indexes=[
            models.Index(fields=["tenant","name"]),
            models.Index(fields=["tenant","phone"]),
        ]

    def __str__(self):
        return self.name


class Service(TimeStampedModel):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="services")
    name=models.CharField(max_length=150)
    description=models.TextField(blank=True)
    duration_minutes=models.PositiveSmallIntegerField()
    price=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    active=models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Professional(TimeStampedModel):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="professionals")
    unit=models.ForeignKey("tenants.Unit",null=True,blank=True,on_delete=models.SET_NULL,related_name="professionals")
    user=models.OneToOneField(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL)
    name=models.CharField(max_length=150)
    public_slug=models.SlugField(max_length=120,null=True,blank=True)
    email=models.EmailField(blank=True)
    phone=models.CharField(max_length=32,blank=True)
    specialty=models.CharField(max_length=150,blank=True)
    photo=models.ImageField(upload_to="professionals/",blank=True)
    commission_percent=models.DecimalField(max_digits=5,decimal_places=2,null=True,blank=True)
    active=models.BooleanField(default=True)
    services=models.ManyToManyField(Service,through="ProfessionalService",related_name="professionals",blank=True)

    class Meta:
        constraints=[
            models.UniqueConstraint(fields=["tenant","public_slug"],name="uq_professional_public_slug"),
        ]

    def __str__(self):
        return self.name


class ProfessionalService(models.Model):
    professional=models.ForeignKey(Professional,on_delete=models.CASCADE)
    service=models.ForeignKey(Service,on_delete=models.CASCADE)

    class Meta:
        constraints=[
            models.UniqueConstraint(fields=["professional","service"],name="uq_professional_service"),
        ]


class ProfessionalAvailability(TimeStampedModel):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="professional_availability")
    professional=models.ForeignKey(Professional,on_delete=models.CASCADE,related_name="availability")
    weekday=models.PositiveSmallIntegerField()
    start_time=models.TimeField()
    end_time=models.TimeField()
    active=models.BooleanField(default=True)

    class Meta:
        constraints=[
            models.UniqueConstraint(fields=["professional","weekday"],name="uq_professional_availability_day"),
            models.CheckConstraint(condition=models.Q(weekday__gte=1,weekday__lte=7),name="availability_weekday_iso"),
            models.CheckConstraint(condition=models.Q(end_time__gt=models.F("start_time")),name="availability_end_after_start"),
        ]


class ProfessionalBreak(TimeStampedModel):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="professional_breaks")
    professional=models.ForeignKey(Professional,on_delete=models.CASCADE,related_name="breaks")
    weekday=models.PositiveSmallIntegerField()
    start_time=models.TimeField()
    end_time=models.TimeField()
    label=models.CharField(max_length=100,blank=True)
    active=models.BooleanField(default=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","professional","weekday","active"])]
        constraints=[
            models.CheckConstraint(condition=models.Q(weekday__gte=1,weekday__lte=7),name="break_weekday_iso"),
            models.CheckConstraint(condition=models.Q(end_time__gt=models.F("start_time")),name="break_end_after_start"),
        ]


class ProfessionalTimeOff(TimeStampedModel):
    class Type(models.TextChoices):
        BREAK="break","Intervalo"
        DAY_OFF="day_off","Folga"
        VACATION="vacation","Férias"
        MEETING="meeting","Reunião"
        PERSONAL="personal","Pessoal"
        OTHER="other","Outro"

    class Status(models.TextChoices):
        ACTIVE="active","Ativo"
        CANCELLED="cancelled","Cancelado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="professional_time_off")
    professional=models.ForeignKey(Professional,on_delete=models.CASCADE,related_name="time_off")
    type=models.CharField(max_length=20,choices=Type.choices,default=Type.OTHER)
    starts_at=models.DateTimeField()
    ends_at=models.DateTimeField()
    reason=models.CharField(max_length=255,blank=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.ACTIVE)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="created_time_off")

    class Meta:
        indexes=[models.Index(fields=["tenant","professional","status","starts_at","ends_at"])]
        constraints=[
            models.CheckConstraint(condition=models.Q(ends_at__gt=models.F("starts_at")),name="timeoff_end_after_start"),
        ]


class TenantScheduleSettings(models.Model):
    tenant=models.OneToOneField("tenants.Tenant",primary_key=True,on_delete=models.CASCADE,related_name="schedule_settings")
    minimum_notice_minutes=models.PositiveIntegerField(default=30)
    maximum_days_ahead=models.PositiveSmallIntegerField(default=90)
    slot_interval_minutes=models.PositiveSmallIntegerField(default=15)
    buffer_minutes=models.PositiveSmallIntegerField(default=0)
    customer_can_cancel=models.BooleanField(default=True)
    customer_can_reschedule=models.BooleanField(default=True)
    cancel_notice_minutes=models.PositiveIntegerField(default=120)
    reminder_24h_enabled=models.BooleanField(default=True)
    reminder_2h_enabled=models.BooleanField(default=False)
    updated_at=models.DateTimeField(auto_now=True)


class Appointment(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING="pending","Pendente"
        CONFIRMED="confirmed","Confirmado"
        WAITING="waiting","Aguardando"
        IN_PROGRESS="in_progress","Em atendimento"
        COMPLETED="completed","Concluído"
        CANCELLED="cancelled","Cancelado"
        NO_SHOW="no_show","Faltou"

    class Source(models.TextChoices):
        PUBLIC="public","Público"
        PROFESSIONAL_LINK="professional_link","Link profissional"
        INTERNAL="internal","Interno"
        WHATSAPP="whatsapp","WhatsApp"
        CAMPAIGN="campaign","Campanha"
        API="api","API"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="appointments")
    customer=models.ForeignKey(Customer,on_delete=models.PROTECT,related_name="appointments")
    professional=models.ForeignKey(Professional,null=True,blank=True,on_delete=models.SET_NULL,related_name="appointments")
    service=models.ForeignKey(Service,on_delete=models.PROTECT,related_name="appointments")
    service_price_snapshot=models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True)
    starts_at=models.DateTimeField(db_index=True)
    ends_at=models.DateTimeField()
    status=models.CharField(max_length=20,choices=Status.choices,default=Status.PENDING,db_index=True)
    source=models.CharField(max_length=24,choices=Source.choices,default=Source.INTERNAL)
    notes=models.TextField(blank=True)
    customer_manage_token_hash=models.CharField(max_length=64,null=True,blank=True,unique=True)
    customer_manage_token_encrypted=models.TextField(blank=True)
    customer_confirmed_at=models.DateTimeField(null=True,blank=True)
    checked_in_at=models.DateTimeField(null=True,blank=True)
    service_started_at=models.DateTimeField(null=True,blank=True)
    service_completed_at=models.DateTimeField(null=True,blank=True)
    reminder_24h_sent_at=models.DateTimeField(null=True,blank=True)
    reminder_2h_sent_at=models.DateTimeField(null=True,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL)

    class Meta:
        indexes=[
            models.Index(fields=["tenant","starts_at"]),
            models.Index(fields=["tenant","status","starts_at"]),
        ]
        constraints=[
            models.CheckConstraint(condition=models.Q(ends_at__gt=models.F("starts_at")),name="appointment_end_after_start"),
        ]


class AppointmentRescheduleHistory(models.Model):
    class ActorType(models.TextChoices):
        CUSTOMER="customer","Cliente"
        USER="user","Usuário"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="reschedule_history")
    appointment=models.ForeignKey(Appointment,on_delete=models.CASCADE,related_name="reschedule_history")
    old_professional=models.ForeignKey(Professional,null=True,blank=True,on_delete=models.SET_NULL,related_name="+")
    new_professional=models.ForeignKey(Professional,null=True,blank=True,on_delete=models.SET_NULL,related_name="+")
    old_starts_at=models.DateTimeField()
    old_ends_at=models.DateTimeField()
    new_starts_at=models.DateTimeField()
    new_ends_at=models.DateTimeField()
    reason=models.CharField(max_length=255,blank=True)
    actor_type=models.CharField(max_length=16,choices=ActorType.choices)
    actor_user=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","appointment","created_at"])]


class AppointmentReminderLog(models.Model):
    class Channel(models.TextChoices):
        EMAIL="email","E-mail"
        WHATSAPP="whatsapp","WhatsApp"

    class Status(models.TextChoices):
        QUEUED="queued","Na fila"
        SENT="sent","Enviado"
        FAILED="failed","Falhou"
        SKIPPED="skipped","Ignorado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="appointment_reminders")
    appointment=models.ForeignKey(Appointment,on_delete=models.CASCADE,related_name="reminder_logs")
    reminder_key=models.CharField(max_length=30)
    channel=models.CharField(max_length=16,choices=Channel.choices)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.QUEUED)
    error_message=models.CharField(max_length=500,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    sent_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        constraints=[
            models.UniqueConstraint(fields=["appointment","reminder_key","channel"],name="uq_appointment_reminder"),
        ]
        indexes=[models.Index(fields=["tenant","status","created_at"])]
