from django.conf import settings
from django.db import models
from django.utils import timezone
from core.models import TimeStampedModel


class AutoSettings(models.Model):
    tenant=models.OneToOneField("tenants.Tenant",primary_key=True,on_delete=models.CASCADE,related_name="auto_settings")
    public_enabled=models.BooleanField(default=True)
    slot_interval_minutes=models.PositiveSmallIntegerField(default=30)
    default_buffer_minutes=models.PositiveSmallIntegerField(default=10)
    require_checkin_photos=models.BooleanField(default=False)
    require_delivery_acceptance=models.BooleanField(default=False)
    crm_default_return_days=models.PositiveSmallIntegerField(default=30)
    terms_text=models.TextField(blank=True)
    created_at=models.DateTimeField(default=timezone.now,editable=False)
    updated_at=models.DateTimeField(auto_now=True)


class Vehicle(TimeStampedModel):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="vehicles")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.CASCADE,related_name="vehicles")
    plate=models.CharField(max_length=16)
    brand=models.CharField(max_length=80,blank=True)
    model=models.CharField(max_length=100)
    year=models.PositiveSmallIntegerField(null=True,blank=True)
    color=models.CharField(max_length=50,blank=True)
    notes=models.CharField(max_length=500,blank=True)
    active=models.BooleanField(default=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["tenant","plate"],name="uq_auto_vehicle_plate")]
        indexes=[models.Index(fields=["tenant","customer","active"],name="auto_vehicle_customer_idx")]

    def __str__(self):
        return f"{self.plate} · {self.model}"


class VehicleProfile(models.Model):
    class Size(models.TextChoices):
        COMPACT="compact","Compacto"
        MEDIUM="medium","Médio"
        LARGE="large","Grande"
        PICKUP="pickup","Pickup"
        MOTORCYCLE="motorcycle","Moto"
        OTHER="other","Outro"

    vehicle=models.OneToOneField(Vehicle,primary_key=True,on_delete=models.CASCADE,related_name="profile")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="vehicle_profiles")
    vehicle_type=models.CharField(max_length=50,blank=True)
    fuel_type=models.CharField(max_length=40,blank=True)
    vin=models.CharField(max_length=40,blank=True)
    current_odometer=models.PositiveIntegerField(null=True,blank=True)
    size_class=models.CharField(max_length=16,choices=Size.choices,blank=True)
    preferred_notes=models.CharField(max_length=500,blank=True)
    last_service_at=models.DateTimeField(null=True,blank=True)
    next_recommended_at=models.DateField(null=True,blank=True,db_index=True)
    warranty_until=models.DateField(null=True,blank=True)
    updated_at=models.DateTimeField(auto_now=True)


class ServiceBay(TimeStampedModel):
    class Type(models.TextChoices):
        BOX="box","Box"
        PARKING="vaga","Vaga"
        LIFT="elevador","Elevador"
        WASH="lavagem","Lavagem"
        DETAILING="detailing","Detailing"
        DRYING="secagem","Secagem"
        OTHER="outro","Outro"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="auto_bays")
    name=models.CharField(max_length=120)
    bay_type=models.CharField(max_length=16,choices=Type.choices,default=Type.BOX)
    capacity=models.PositiveSmallIntegerField(default=1)
    buffer_minutes=models.PositiveSmallIntegerField(default=0)
    notes=models.CharField(max_length=500,blank=True)
    active=models.BooleanField(default=True)
    sort_order=models.PositiveSmallIntegerField(default=0)
    services=models.ManyToManyField("scheduling.Service",through="BayService",related_name="auto_bays",blank=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["tenant","name"],name="uq_auto_bay_name")]
        indexes=[models.Index(fields=["tenant","active","sort_order"],name="auto_bay_active_idx")]


class BayHours(models.Model):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="auto_bay_hours")
    bay=models.ForeignKey(ServiceBay,on_delete=models.CASCADE,related_name="hours")
    weekday=models.PositiveSmallIntegerField()
    start_time=models.TimeField()
    end_time=models.TimeField()
    active=models.BooleanField(default=True)

    class Meta:
        constraints=[
            models.UniqueConstraint(fields=["bay","weekday","start_time","end_time"],name="uq_auto_bay_hours"),
            models.CheckConstraint(condition=models.Q(weekday__gte=1,weekday__lte=7),name="auto_bay_weekday_iso"),
            models.CheckConstraint(condition=models.Q(end_time__gt=models.F("start_time")),name="auto_bay_hours_valid"),
        ]
        indexes=[models.Index(fields=["tenant","bay","weekday","active"],name="auto_bay_hours_idx")]


class BayService(models.Model):
    bay=models.ForeignKey(ServiceBay,on_delete=models.CASCADE)
    service=models.ForeignKey("scheduling.Service",on_delete=models.CASCADE)
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["bay","service"],name="uq_auto_bay_service")]


class Job(TimeStampedModel):
    class Status(models.TextChoices):
        SCHEDULED="scheduled","Agendado"
        RECEIVED="received","Recebido"
        QUEUE="queue","Fila"
        PREPARATION="preparation","Preparação"
        IN_SERVICE="in_service","Em serviço"
        DRYING="drying","Secagem"
        CURING="curing","Cura"
        READY="ready","Pronto"
        DELIVERED="delivered","Entregue"
        CANCELLED="cancelled","Cancelado"

    class Fuel(models.TextChoices):
        EMPTY="empty","Vazio"
        QUARTER="quarter","1/4"
        HALF="half","1/2"
        THREE_QUARTERS="three_quarters","3/4"
        FULL="full","Cheio"
        UNKNOWN="unknown","Desconhecido"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="auto_jobs")
    appointment=models.OneToOneField("scheduling.Appointment",on_delete=models.CASCADE,related_name="auto_job")
    vehicle=models.ForeignKey(Vehicle,on_delete=models.PROTECT,related_name="jobs")
    bay=models.ForeignKey(ServiceBay,null=True,blank=True,on_delete=models.SET_NULL,related_name="jobs")
    assigned_professional=models.ForeignKey("scheduling.Professional",null=True,blank=True,on_delete=models.SET_NULL,related_name="auto_jobs")
    status=models.CharField(max_length=24,choices=Status.choices,default=Status.SCHEDULED,db_index=True)
    odometer_in=models.PositiveIntegerField(null=True,blank=True)
    fuel_level=models.CharField(max_length=20,choices=Fuel.choices,default=Fuel.UNKNOWN)
    keys_received=models.BooleanField(default=False)
    expected_ready_at=models.DateTimeField(null=True,blank=True)
    received_at=models.DateTimeField(null=True,blank=True)
    started_at=models.DateTimeField(null=True,blank=True)
    ready_at=models.DateTimeField(null=True,blank=True)
    delivered_at=models.DateTimeField(null=True,blank=True)
    internal_notes=models.TextField(blank=True)
    public_notes=models.CharField(max_length=500,blank=True)

    class Meta:
        indexes=[
            models.Index(fields=["tenant","status","created_at"],name="auto_job_status_idx"),
            models.Index(fields=["tenant","bay","status"],name="auto_job_bay_idx"),
            models.Index(fields=["tenant","vehicle","created_at"],name="auto_job_vehicle_idx"),
        ]


class JobStatusHistory(models.Model):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="auto_job_history")
    job=models.ForeignKey(Job,on_delete=models.CASCADE,related_name="history")
    old_status=models.CharField(max_length=40,blank=True)
    new_status=models.CharField(max_length=40)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="auto_job_changes")
    notes=models.CharField(max_length=500,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["job","created_at"],name="auto_job_history_idx")]


class InspectionItem(models.Model):
    class Phase(models.TextChoices):
        CHECKIN="checkin","Entrada"
        CHECKOUT="checkout","Saída"

    class Condition(models.TextChoices):
        OK="ok","OK"
        ATTENTION="attention","Atenção"
        DAMAGED="damaged","Danificado"
        NOT_CHECKED="not_checked","Não verificado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="auto_inspections")
    job=models.ForeignKey(Job,on_delete=models.CASCADE,related_name="inspection_items")
    phase=models.CharField(max_length=12,choices=Phase.choices,default=Phase.CHECKIN)
    area=models.CharField(max_length=80)
    item_label=models.CharField(max_length=120)
    condition_status=models.CharField(max_length=16,choices=Condition.choices,default=Condition.NOT_CHECKED)
    notes=models.CharField(max_length=500,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="auto_inspections_created")
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["job","phase"],name="auto_inspection_idx")]


class JobPhoto(models.Model):
    class Phase(models.TextChoices):
        BEFORE="before","Antes"
        DAMAGE="damage","Dano"
        PROCESS="process","Processo"
        AFTER="after","Depois"
        DELIVERY="delivery","Entrega"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="auto_photos")
    job=models.ForeignKey(Job,on_delete=models.CASCADE,related_name="photos")
    phase=models.CharField(max_length=12,choices=Phase.choices)
    file=models.ImageField(upload_to="auto/jobs/")
    caption=models.CharField(max_length=190,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="auto_photos_created")
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["job","phase","created_at"],name="auto_photo_idx")]


class JobMaterialUsage(models.Model):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="auto_material_usage")
    job=models.ForeignKey(Job,on_delete=models.CASCADE,related_name="materials")
    product=models.ForeignKey("finance.Product",on_delete=models.PROTECT,related_name="auto_job_usage")
    quantity=models.DecimalField(max_digits=10,decimal_places=3)
    dilution=models.CharField(max_length=60,blank=True)
    batch_lot=models.CharField(max_length=100,blank=True)
    notes=models.CharField(max_length=500,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="auto_material_usage")
    created_at=models.DateTimeField(auto_now_add=True)


class JobTechnicalDetail(models.Model):
    job=models.OneToOneField(Job,primary_key=True,on_delete=models.CASCADE,related_name="technical")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="auto_job_technical")
    return_days=models.PositiveSmallIntegerField(null=True,blank=True)
    warranty_days=models.PositiveSmallIntegerField(null=True,blank=True)
    quality_notes=models.TextField(blank=True)
    updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="auto_technical_updates")
    updated_at=models.DateTimeField(auto_now=True)


class Estimate(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT="draft","Rascunho"
        SENT="sent","Enviado"
        APPROVED="approved","Aprovado"
        REJECTED="rejected","Rejeitado"
        EXPIRED="expired","Expirado"
        CANCELLED="cancelled","Cancelado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="auto_estimates")
    job=models.ForeignKey(Job,on_delete=models.CASCADE,related_name="estimates")
    public_token_hash=models.CharField(max_length=64,unique=True)
    public_token_encrypted=models.TextField()
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.DRAFT,db_index=True)
    subtotal=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    discount_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    total_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    expires_at=models.DateTimeField(null=True,blank=True)
    sent_at=models.DateTimeField(null=True,blank=True)
    responded_at=models.DateTimeField(null=True,blank=True)
    customer_note=models.CharField(max_length=500,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="auto_estimates_created")

    class Meta:
        indexes=[models.Index(fields=["tenant","job","status"],name="auto_estimate_job_idx")]


class EstimateItem(models.Model):
    estimate=models.ForeignKey(Estimate,on_delete=models.CASCADE,related_name="items")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="auto_estimate_items")
    service=models.ForeignKey("scheduling.Service",null=True,blank=True,on_delete=models.SET_NULL,related_name="+")
    product=models.ForeignKey("finance.Product",null=True,blank=True,on_delete=models.SET_NULL,related_name="+")
    description=models.CharField(max_length=190)
    quantity=models.DecimalField(max_digits=10,decimal_places=3,default=1)
    unit_price=models.DecimalField(max_digits=12,decimal_places=2)
    total_amount=models.DecimalField(max_digits=12,decimal_places=2)
    created_at=models.DateTimeField(auto_now_add=True)


class AutoCommand(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN="open","Aberta"
        CLOSED="closed","Fechada"
        CANCELLED="cancelled","Cancelada"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="auto_commands")
    job=models.OneToOneField(Job,on_delete=models.CASCADE,related_name="command")
    appointment=models.ForeignKey("scheduling.Appointment",on_delete=models.CASCADE,related_name="auto_commands")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.PROTECT,related_name="auto_commands")
    vehicle=models.ForeignKey(Vehicle,on_delete=models.PROTECT,related_name="commands")
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.OPEN,db_index=True)
    subtotal=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    discount_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    surcharge_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    total_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    opened_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="auto_commands_opened")
    opened_at=models.DateTimeField()
    closed_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="auto_commands_closed")
    closed_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","status","opened_at"],name="auto_command_status_idx")]


class AutoCommandItem(models.Model):
    class Type(models.TextChoices):
        SERVICE="service","Serviço"
        PRODUCT="product","Produto"
        MATERIAL="material","Material"
        MANUAL="manual","Manual"

    command=models.ForeignKey(AutoCommand,on_delete=models.CASCADE,related_name="items")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="auto_command_items")
    item_type=models.CharField(max_length=12,choices=Type.choices)
    service=models.ForeignKey("scheduling.Service",null=True,blank=True,on_delete=models.SET_NULL)
    product=models.ForeignKey("finance.Product",null=True,blank=True,on_delete=models.SET_NULL)
    professional=models.ForeignKey("scheduling.Professional",null=True,blank=True,on_delete=models.SET_NULL)
    description=models.CharField(max_length=190)
    quantity=models.DecimalField(max_digits=10,decimal_places=3,default=1)
    unit_price=models.DecimalField(max_digits=12,decimal_places=2)
    discount_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    total_amount=models.DecimalField(max_digits=12,decimal_places=2)
    cost_snapshot=models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)
    approved_estimate=models.ForeignKey(Estimate,null=True,blank=True,on_delete=models.SET_NULL,related_name="command_items")
    is_primary_service=models.BooleanField(default=False)
    created_at=models.DateTimeField(default=timezone.now,editable=False)


class AutoCommandPayment(models.Model):
    command=models.ForeignKey(AutoCommand,on_delete=models.CASCADE,related_name="payments")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="auto_command_payments")
    payment_method=models.CharField(max_length=20)
    amount=models.DecimalField(max_digits=12,decimal_places=2)
    provider=models.CharField(max_length=50,blank=True)
    provider_reference=models.CharField(max_length=190,blank=True)
    received_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="auto_payments_received")
    received_at=models.DateTimeField()


class ServiceMaterial(models.Model):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE)
    service=models.ForeignKey("scheduling.Service",on_delete=models.CASCADE,related_name="auto_materials")
    product=models.ForeignKey("finance.Product",on_delete=models.CASCADE,related_name="auto_service_materials")
    quantity=models.DecimalField(max_digits=10,decimal_places=3)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["service","product"],name="uq_auto_service_material")]


class ServiceStep(models.Model):
    class Type(models.TextChoices):
        PREPARATION="preparation","Preparação"
        SERVICE="service","Serviço"
        DRYING="drying","Secagem"
        CURING="curing","Cura"
        QUALITY="quality","Qualidade"
        DELIVERY="delivery","Entrega"
        OTHER="other","Outro"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE)
    service=models.ForeignKey("scheduling.Service",on_delete=models.CASCADE,related_name="auto_steps")
    name=models.CharField(max_length=120)
    step_type=models.CharField(max_length=16,choices=Type.choices,default=Type.SERVICE)
    expected_minutes=models.PositiveSmallIntegerField(null=True,blank=True)
    sort_order=models.PositiveSmallIntegerField(default=0)
    active=models.BooleanField(default=True)

    class Meta:
        indexes=[models.Index(fields=["service","active","sort_order"],name="auto_service_step_idx")]


class JobStep(models.Model):
    class Status(models.TextChoices):
        PENDING="pending","Pendente"
        IN_PROGRESS="in_progress","Em andamento"
        COMPLETED="completed","Concluída"
        SKIPPED="skipped","Ignorada"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE)
    job=models.ForeignKey(Job,on_delete=models.CASCADE,related_name="steps")
    service_step=models.ForeignKey(ServiceStep,null=True,blank=True,on_delete=models.SET_NULL,related_name="job_steps")
    name=models.CharField(max_length=120)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.PENDING,db_index=True)
    started_at=models.DateTimeField(null=True,blank=True)
    completed_at=models.DateTimeField(null=True,blank=True)
    professional=models.ForeignKey("scheduling.Professional",null=True,blank=True,on_delete=models.SET_NULL,related_name="auto_steps")
    notes=models.CharField(max_length=500,blank=True)
    sort_order=models.PositiveSmallIntegerField(default=0)

    class Meta:
        indexes=[models.Index(fields=["job","status","sort_order"],name="auto_job_step_idx")]


class VehicleMaintenance(models.Model):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="auto_maintenance")
    vehicle=models.ForeignKey(Vehicle,on_delete=models.CASCADE,related_name="maintenance")
    source_job=models.ForeignKey(Job,null=True,blank=True,on_delete=models.SET_NULL,related_name="maintenance_records")
    title=models.CharField(max_length=150)
    performed_at=models.DateField()
    next_due_at=models.DateField(null=True,blank=True,db_index=True)
    warranty_until=models.DateField(null=True,blank=True)
    notes=models.CharField(max_length=500,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)


class DeliveryTerm(models.Model):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="auto_delivery_terms")
    job=models.OneToOneField(Job,on_delete=models.CASCADE,related_name="delivery_term")
    public_token_hash=models.CharField(max_length=64,unique=True)
    public_token_encrypted=models.TextField()
    terms_snapshot=models.TextField()
    accepted_name=models.CharField(max_length=150,blank=True)
    accepted_ip=models.GenericIPAddressField(null=True,blank=True)
    accepted_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)


class CRMEvent(TimeStampedModel):
    class Type(models.TextChoices):
        RETURN_DUE="return_due","Retorno"
        WARRANTY_DUE="warranty_due","Garantia"
        INACTIVE="inactive","Inatividade"
        MANUAL="manual","Manual"

    class Status(models.TextChoices):
        PENDING="pending","Pendente"
        NOTIFIED="notified","Notificado"
        DONE="done","Concluído"
        CANCELLED="cancelled","Cancelado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="auto_crm_events")
    vehicle=models.ForeignKey(Vehicle,on_delete=models.CASCADE,related_name="crm_events")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.CASCADE,related_name="auto_crm_events")
    event_type=models.CharField(max_length=20,choices=Type.choices)
    due_at=models.DateField()
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.PENDING,db_index=True)
    channel=models.CharField(max_length=30,blank=True)
    notified_at=models.DateTimeField(null=True,blank=True)
    notes=models.CharField(max_length=500,blank=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["tenant","vehicle","event_type","due_at"],name="uq_auto_crm_event")]
        indexes=[models.Index(fields=["tenant","status","due_at"],name="auto_crm_due_idx")]


class VehiclePackageLink(models.Model):
    customer_package=models.OneToOneField(
        "engagement.CustomerPackage",primary_key=True,on_delete=models.CASCADE,
        related_name="vehicle_link",
    )
    tenant=models.ForeignKey(
        "tenants.Tenant",on_delete=models.CASCADE,related_name="auto_vehicle_package_links"
    )
    vehicle=models.ForeignKey(
        Vehicle,on_delete=models.CASCADE,related_name="package_links"
    )
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","vehicle"],name="auto_pkg_vehicle_idx")]


class MembershipVehicleLink(models.Model):
    membership=models.OneToOneField(
        "engagement.CustomerMembership",primary_key=True,on_delete=models.CASCADE,
        related_name="vehicle_link",
    )
    tenant=models.ForeignKey(
        "tenants.Tenant",on_delete=models.CASCADE,related_name="auto_membership_vehicle_links"
    )
    vehicle=models.ForeignKey(
        Vehicle,on_delete=models.CASCADE,related_name="membership_links"
    )
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","vehicle"],name="auto_member_vehicle_idx")]
