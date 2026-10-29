from django.conf import settings
from django.db import models
from django.utils import timezone
from core.models import TimeStampedModel


class Customer(TimeStampedModel):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="customers")
    name=models.CharField(max_length=150)
    phone=models.CharField(max_length=32,blank=True)
    email=models.EmailField(blank=True)
    birth_date=models.DateField(null=True,blank=True)
    preferences=models.CharField(max_length=1000,blank=True)
    consent_marketing=models.BooleanField(default=False)
    active=models.BooleanField(default=True)

    def clean(self):
        super().clean()
        from .customer_identity import contact_values,identity_matches
        self.name,self.phone,self.email=contact_values(self.name,self.phone,self.email)
        if self.tenant_id:
            from django.core.exceptions import ValidationError
            phones,emails=identity_matches(self.tenant,self.phone,self.email)
            if phones.exclude(pk=self.pk).exists() or emails.exclude(pk=self.pk).exists():
                raise ValidationError("Este telefone ou e-mail já pertence a um cliente da empresa. Use o cadastro existente para preservar o histórico.")

    class Meta:
        indexes=[
            models.Index(fields=["tenant","name"]),
            models.Index(fields=["tenant","phone"]),
        ]

    def __str__(self):
        return self.name


class Service(TimeStampedModel):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="services")
    unit=models.ForeignKey("tenants.Unit",null=True,blank=True,on_delete=models.PROTECT,related_name="services")
    name=models.CharField(max_length=150)
    description=models.TextField(blank=True)
    duration_minutes=models.PositiveSmallIntegerField()
    price=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    active=models.BooleanField(default=True)

    def clean(self):
        super().clean()
        if self.unit_id and self.tenant_id and self.unit.tenant_id!=self.tenant_id:
            from django.core.exceptions import ValidationError
            raise ValidationError({"unit":"A unidade deve pertencer à mesma empresa."})

    def __str__(self):
        return self.name


class Professional(TimeStampedModel):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="professionals")
    unit=models.ForeignKey("tenants.Unit",null=True,blank=True,on_delete=models.SET_NULL,related_name="professionals")
    user=models.OneToOneField(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL)
    name=models.CharField(max_length=150)
    public_slug=models.SlugField(max_length=120,null=True,blank=True)
    public_short_code=models.CharField(max_length=16,unique=True,null=True,blank=True,editable=False)
    email=models.EmailField(blank=True)
    phone=models.CharField(max_length=32,blank=True)
    specialty=models.CharField(max_length=150,blank=True)
    photo=models.ImageField(upload_to="professionals/",blank=True)
    commission_percent=models.DecimalField(max_digits=5,decimal_places=2,null=True,blank=True)
    active=models.BooleanField(default=True)
    services=models.ManyToManyField(Service,through="ProfessionalService",related_name="professionals",blank=True)
    services_restricted=models.BooleanField(default=False)

    def clean(self):
        super().clean()
        from billing.entitlements import validate_professional_capacity
        validate_professional_capacity(self)
        if self.unit_id and self.tenant_id and self.unit.tenant_id!=self.tenant_id:
            from django.core.exceptions import ValidationError
            raise ValidationError({"unit":"A unidade deve pertencer à mesma empresa."})

    def save(self, *args, **kwargs):
        # Enforce dental seat limits on direct ORM writes, not only ModelForms.
        if self.tenant_id and (self.tenant.category or "").strip().lower() in {"odontologia", "odontologica", "odontológico", "odontologico"}:
            from billing.entitlements import validate_professional_capacity
            validate_professional_capacity(self)
        from core.public_identity import assign_short_code
        assign_short_code(self, kwargs)
        super().save(*args, **kwargs)

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
    reminder_2h_enabled=models.BooleanField(default=True)
    allow_pay_on_site=models.BooleanField(default=True,verbose_name="Permitir pagamento na unidade")
    allow_partial_payment=models.BooleanField(default=False,verbose_name="Permitir sinal por Pix no agendamento")
    allow_full_payment=models.BooleanField(default=False,verbose_name="Permitir pagamento total por Pix no agendamento")
    online_booking_payments_enabled=models.BooleanField(default=False,
        verbose_name="Ativar cobrança online ao agendar")
    card_booking_payments_enabled=models.BooleanField(default=False,verbose_name="Permitir cartão antecipado tokenizado")
    deposit_percent=models.PositiveSmallIntegerField(default=30,verbose_name="Percentual do sinal")
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
        WALK_IN="walk_in","Avulso"

    class BookingPayment(models.TextChoices):
        ON_SITE="on_site","Na unidade"
        PARTIAL="partial","Sinal por Pix"
        FULL="full","Total por Pix"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="appointments")
    unit=models.ForeignKey(
        "tenants.Unit",null=True,blank=True,on_delete=models.SET_NULL,related_name="appointments"
    )
    customer=models.ForeignKey(Customer,on_delete=models.PROTECT,related_name="appointments")
    vehicle=models.ForeignKey("auto.Vehicle",null=True,blank=True,on_delete=models.SET_NULL,related_name="appointments")
    professional=models.ForeignKey(Professional,null=True,blank=True,on_delete=models.SET_NULL,related_name="appointments")
    service=models.ForeignKey(Service,on_delete=models.PROTECT,related_name="appointments")
    service_price_snapshot=models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True)
    customer_name_snapshot=models.CharField(max_length=160,blank=True,editable=False)
    starts_at=models.DateTimeField(db_index=True)
    ends_at=models.DateTimeField()
    status=models.CharField(max_length=20,choices=Status.choices,default=Status.PENDING,db_index=True)
    source=models.CharField(max_length=24,choices=Source.choices,default=Source.INTERNAL)
    booking_payment=models.CharField(max_length=12,choices=BookingPayment.choices,
        default=BookingPayment.ON_SITE,verbose_name="Pagamento do agendamento")
    booking_payment_amount=models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True,
        verbose_name="Valor solicitado no agendamento")
    notes=models.TextField(blank=True)
    customer_manage_token_hash=models.CharField(max_length=64,null=True,blank=True,unique=True)
    customer_manage_token_encrypted=models.TextField(blank=True)
    idempotency_key=models.CharField(max_length=100,blank=True)
    idempotency_fingerprint=models.CharField(max_length=64,blank=True)
    customer_confirmed_at=models.DateTimeField(null=True,blank=True)
    checked_in_at=models.DateTimeField(null=True,blank=True)
    service_started_at=models.DateTimeField(null=True,blank=True)
    service_completed_at=models.DateTimeField(null=True,blank=True)
    reminder_24h_sent_at=models.DateTimeField(null=True,blank=True)
    reminder_2h_sent_at=models.DateTimeField(null=True,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL)

    @property
    def customer_display_name(self):
        # The submitted name is retained for audit; operational screens use the
        # same canonical customer as return intelligence and the editing form.
        return self.customer.name if self.customer_id else self.customer_name_snapshot or "Cliente a definir"

    @property
    def customer_name_differs(self):
        return bool(self.customer_id and self.customer_name_snapshot.strip()
                    and self.customer_name_snapshot.strip() != self.customer.name.strip())

    def save(self,*args,**kwargs):
        if self._state.adding and not self.customer_name_snapshot and self.customer_id:
            self.customer_name_snapshot=self.customer.name
        from django.db import transaction
        staged = self.service_id and self.service.stages.exists()
        if staged:
            if not self.unit_id and self.professional_id:
                self.unit_id=self.professional.unit_id
                if kwargs.get('update_fields') is not None:
                    kwargs['update_fields']=set(kwargs['update_fields'])|{'unit'}
            with transaction.atomic():
                if self.unit_id:
                    from tenants.models import Unit
                    Unit.objects.select_for_update().get(pk=self.unit_id,tenant_id=self.tenant_id)
                if self.professional_id:
                    Professional.objects.select_for_update().get(pk=self.professional_id,tenant_id=self.tenant_id)
                previous=type(self).objects.filter(pk=self.pk).values('starts_at','ends_at','professional_id','service_id').first() if self.pk else None
                changed=previous is None or any(previous[k]!=getattr(self,k) for k in previous)
                if changed and self.status not in ['cancelled','no_show']:
                    from .availability import AvailabilityService
                    from django.core.exceptions import ValidationError
                    if not self.professional_id or not AvailabilityService().is_available(self.tenant,self.professional,
                        self.starts_at,self.ends_at,exclude_appointment_id=self.pk,public_rules=False,service=self.service):
                        raise ValidationError('Etapas, profissional ou recurso indisponível neste horário.')
                super().save(*args,**kwargs)
        else:
            super().save(*args,**kwargs)

    def __str__(self):
        if not self.customer_id or not self.starts_at:
            return "Novo agendamento"
        starts_at=timezone.localtime(self.starts_at) if timezone.is_aware(self.starts_at) else self.starts_at
        return f"{self.customer_display_name} — {starts_at:%d/%m/%Y %H:%M}"

    def clean(self):
        super().clean()
        if self.unit_id and self.unit.tenant_id!=self.tenant_id:
            from django.core.exceptions import ValidationError
            raise ValidationError({"unit":"A unidade deve pertencer à mesma empresa do agendamento."})
        if self.professional_id and self.professional.unit_id and self.unit_id and self.professional.unit_id!=self.unit_id:
            from django.core.exceptions import ValidationError
            raise ValidationError({"professional":"O profissional não pertence à unidade selecionada."})
        if self.vehicle_id and self.customer_id and (
            self.vehicle.customer_id!=self.customer_id or self.vehicle.tenant_id!=self.tenant_id
        ):
            from django.core.exceptions import ValidationError
            raise ValidationError({"vehicle":"O veículo deve pertencer ao cliente e à empresa do agendamento."})

    class Meta:
        indexes=[
            models.Index(fields=["tenant","starts_at"]),
            models.Index(fields=["tenant","status","starts_at"]),
            models.Index(fields=["tenant","unit","starts_at"],name="sched_appt_unit_start_idx"),
        ]
        constraints=[
            models.CheckConstraint(condition=models.Q(ends_at__gt=models.F("starts_at")),name="appointment_end_after_start"),
            models.UniqueConstraint(
                fields=["tenant","idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="uq_appointment_idempotency",
            ),
        ]


class AppointmentSettlement(models.Model):
    appointment=models.OneToOneField(Appointment,on_delete=models.PROTECT,related_name="settlement")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE)
    professional=models.ForeignKey(Professional,on_delete=models.PROTECT)
    attended=models.BooleanField()
    payment_method=models.CharField(max_length=40,blank=True)
    sale=models.OneToOneField("finance.Sale",null=True,blank=True,on_delete=models.PROTECT)
    settled_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)


class AppointmentRating(models.Model):
    appointment=models.OneToOneField(Appointment,on_delete=models.CASCADE,related_name="rating")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE)
    professional=models.ForeignKey(Professional,on_delete=models.PROTECT)
    score=models.PositiveSmallIntegerField()
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints=[models.CheckConstraint(condition=models.Q(score__gte=1,score__lte=5),name="appointment_rating_1_5")]
        indexes=[models.Index(fields=["tenant","professional","created_at"])]


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


class CustomerAccessChallenge(models.Model):
    import uuid as _uuid
    id = models.UUIDField(primary_key=True,default=_uuid.uuid4,editable=False)
    tenant = models.ForeignKey('tenants.Tenant',on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer,null=True,blank=True,on_delete=models.CASCADE)
    code_digest = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AppointmentWorkNote(models.Model):
    technical_encrypted = models.TextField(blank=True)

    @property
    def technical(self):
        from core.crypto import decrypt_json
        return decrypt_json(self.technical_encrypted) if self.technical_encrypted else {}

    @property
    def technical_display(self):
        labels={'cut_style':'Corte / máquina / degradê','beard':'Barba e acabamento',
            'color_formula':'Fórmula de coloração','products':'Produtos utilizados',
            'processing_minutes':'Pausa (minutos)','preferences':'Preferências e cuidados','result':'Resultado'}
        return [(labels[k],v) for k,v in self.technical.items() if k in labels and v not in (None,'')]

    tenant = models.ForeignKey('tenants.Tenant',on_delete=models.PROTECT)
    appointment = models.ForeignKey(Appointment,on_delete=models.PROTECT,related_name='work_notes')
    user = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    text = models.TextField(max_length=4000)
    photo = models.ImageField(upload_to='private/worknotes/',blank=True)
    photo_consent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class AppointmentBundle(models.Model):
    tenant = models.ForeignKey('tenants.Tenant',on_delete=models.PROTECT)
    unit = models.ForeignKey('tenants.Unit',on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=100)
    fingerprint = models.CharField(max_length=64)
    appointments = models.ManyToManyField(Appointment,related_name='bundles')
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant','idempotency_key'],name='uq_appointment_bundle_key')]


class CustomerImportBatch(TimeStampedModel):
    """Private staging for external customer CSV/XLSX files; source is cleared after apply."""
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="customer_imports")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    source_name = models.CharField(max_length=160)
    file_hash = models.CharField(max_length=64)
    payload_encrypted = models.TextField(blank=True)
    mapping = models.JSONField(default=dict)
    report = models.JSONField(default=dict)
    state = models.CharField(max_length=16, default="preview", choices=[("preview", "Prévia"), ("applied", "Importada")])
    expires_at = models.DateTimeField()
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "file_hash"], name="uq_customer_import_file")]
