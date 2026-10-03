from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class ProfessionalServiceCommission(TimeStampedModel):
    class Type(models.TextChoices):
        PERCENT="percent","Percentual"
        FIXED="fixed","Fixa"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="service_commission_rules")
    professional=models.ForeignKey("scheduling.Professional",on_delete=models.CASCADE,related_name="service_commission_rules")
    service=models.ForeignKey("scheduling.Service",on_delete=models.CASCADE,related_name="commission_rules")
    commission_type=models.CharField(max_length=12,choices=Type.choices,default=Type.PERCENT)
    commission_value=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    active=models.BooleanField(default=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["tenant","professional","service"],name="uq_barber_service_commission")]
        indexes=[models.Index(fields=["tenant","professional","active"],name="barber_commission_prof_idx")]


class ProfessionalCompensationModel(models.Model):
    class Model(models.TextChoices):
        COMMISSION="commission","Comissão"
        CHAIR_RENT="chair_rent","Aluguel de cadeira"
        DAILY_RENT="daily_rent","Aluguel diário"
        HYBRID="hybrid","Híbrido"

    professional=models.OneToOneField("scheduling.Professional",primary_key=True,on_delete=models.CASCADE,related_name="compensation")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="compensation_models")
    model=models.CharField(max_length=16,choices=Model.choices,default=Model.COMMISSION)
    monthly_rent=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    daily_rent=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    rent_due_day=models.PositiveSmallIntegerField(default=5)
    service_commission_percent=models.DecimalField(max_digits=5,decimal_places=2,null=True,blank=True)
    notes=models.CharField(max_length=500,blank=True)
    updated_at=models.DateTimeField(auto_now=True)


class ProfessionalGoal(TimeStampedModel):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="professional_goals")
    professional=models.ForeignKey("scheduling.Professional",on_delete=models.CASCADE,related_name="goals")
    year=models.PositiveSmallIntegerField()
    month=models.PositiveSmallIntegerField()
    revenue_target=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    services_target=models.PositiveIntegerField(default=0)
    products_target=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    ticket_target=models.DecimalField(max_digits=12,decimal_places=2,default=0)

    class Meta:
        constraints=[
            models.UniqueConstraint(fields=["tenant","professional","year","month"],name="uq_barber_goal"),
            models.CheckConstraint(condition=models.Q(month__gte=1,month__lte=12),name="barber_goal_month_valid"),
        ]


class BarberCommand(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN="open","Aberta"
        CLOSED="closed","Fechada"
        CANCELLED="cancelled","Cancelada"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="barber_commands")
    appointment=models.ForeignKey("scheduling.Appointment",null=True,blank=True,on_delete=models.SET_NULL,related_name="barber_commands")
    customer=models.ForeignKey("scheduling.Customer",null=True,blank=True,on_delete=models.SET_NULL,related_name="barber_commands")
    professional=models.ForeignKey("scheduling.Professional",null=True,blank=True,on_delete=models.SET_NULL,related_name="barber_commands")
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.OPEN,db_index=True)
    subtotal=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    discount_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    surcharge_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    tip_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    tip_professional=models.ForeignKey("scheduling.Professional",null=True,blank=True,on_delete=models.SET_NULL,related_name="tips_received")
    total_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    notes=models.CharField(max_length=500,blank=True)
    opened_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="barber_commands_opened")
    opened_at=models.DateTimeField()
    closed_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="barber_commands_closed")
    closed_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        constraints=[
            models.UniqueConstraint(
                fields=["tenant","appointment"],
                condition=models.Q(appointment__isnull=False),
                name="uq_barber_command_appointment",
            )
        ]
        indexes=[models.Index(fields=["tenant","status","opened_at"],name="barber_command_status_idx")]


class BarberCommandItem(models.Model):
    class ItemType(models.TextChoices):
        SERVICE="service","Serviço"
        PRODUCT="product","Produto"
        MANUAL="manual","Manual"

    command=models.ForeignKey(BarberCommand,on_delete=models.CASCADE,related_name="items")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="barber_command_items")
    item_type=models.CharField(max_length=12,choices=ItemType.choices)
    service=models.ForeignKey("scheduling.Service",null=True,blank=True,on_delete=models.SET_NULL)
    product=models.ForeignKey("finance.Product",null=True,blank=True,on_delete=models.SET_NULL)
    professional=models.ForeignKey("scheduling.Professional",null=True,blank=True,on_delete=models.SET_NULL)
    description=models.CharField(max_length=190)
    quantity=models.DecimalField(max_digits=12,decimal_places=3,default=1)
    unit_price=models.DecimalField(max_digits=12,decimal_places=2)
    discount_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    total_amount=models.DecimalField(max_digits=12,decimal_places=2)
    cost_snapshot=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    commission_amount_snapshot=models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)
    is_primary_service=models.BooleanField(default=False)
    covered_by_package=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["command","item_type"],name="barber_command_item_idx")]


class BarberCommandPayment(models.Model):
    command=models.ForeignKey(BarberCommand,on_delete=models.CASCADE,related_name="payments")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="barber_command_payments")
    method=models.CharField(max_length=40)
    amount=models.DecimalField(max_digits=12,decimal_places=2)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="barber_payments_received")
    received_at=models.DateTimeField()

    class Meta:
        indexes=[models.Index(fields=["command","received_at"],name="barber_command_payment_idx")]


class BarberQueueEntry(TimeStampedModel):
    class Status(models.TextChoices):
        WAITING="waiting","Aguardando"
        CALLED="called","Chamado"
        IN_SERVICE="in_service","Em atendimento"
        COMPLETED="completed","Concluído"
        CANCELLED="cancelled","Cancelado"
        NO_SHOW="no_show","Não compareceu"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="barber_queue")
    customer=models.ForeignKey("scheduling.Customer",null=True,blank=True,on_delete=models.SET_NULL,related_name="barber_queue_entries")
    customer_name=models.CharField(max_length=150)
    customer_phone=models.CharField(max_length=32,blank=True)
    service=models.ForeignKey("scheduling.Service",on_delete=models.PROTECT,related_name="barber_queue_entries")
    preferred_professional=models.ForeignKey("scheduling.Professional",null=True,blank=True,on_delete=models.SET_NULL,related_name="preferred_queue_entries")
    assigned_professional=models.ForeignKey("scheduling.Professional",null=True,blank=True,on_delete=models.SET_NULL,related_name="assigned_queue_entries")
    appointment=models.ForeignKey("scheduling.Appointment",null=True,blank=True,on_delete=models.SET_NULL,related_name="queue_entries")
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.WAITING,db_index=True)
    priority=models.SmallIntegerField(default=0)
    notes=models.CharField(max_length=255,blank=True)
    joined_at=models.DateTimeField()
    called_at=models.DateTimeField(null=True,blank=True)
    started_at=models.DateTimeField(null=True,blank=True)
    completed_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","status","priority","joined_at"],name="barber_queue_status_idx")]
