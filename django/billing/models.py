from django.db import models
from core.models import TimeStampedModel


class Plan(TimeStampedModel):
    name=models.CharField(max_length=100)
    slug=models.SlugField(max_length=80,unique=True)
    monthly_price=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    active=models.BooleanField(default=True)
    features=models.JSONField(default=dict,blank=True)


class Subscription(TimeStampedModel):
    class Status(models.TextChoices):
        TRIAL="trial","Teste"
        ACTIVE="active","Ativa"
        PAST_DUE="past_due","Em atraso"
        CANCELLED="cancelled","Cancelada"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="subscriptions")
    plan=models.ForeignKey(Plan,on_delete=models.PROTECT)
    status=models.CharField(max_length=20,choices=Status.choices,default=Status.TRIAL,db_index=True)
    started_at=models.DateTimeField()
    next_billing_at=models.DateTimeField(null=True,blank=True,db_index=True)
    cancelled_at=models.DateTimeField(null=True,blank=True)


class Payment(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING="pending","Pendente"
        PAID="paid","Pago"
        FAILED="failed","Falhou"
        REFUNDED="refunded","Estornado"
        CANCELLED="cancelled","Cancelado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="payments")
    subscription=models.ForeignKey(Subscription,null=True,blank=True,on_delete=models.SET_NULL,related_name="payments")
    provider=models.CharField(max_length=60,blank=True)
    provider_reference=models.CharField(max_length=190,blank=True,db_index=True)
    amount=models.DecimalField(max_digits=10,decimal_places=2)
    status=models.CharField(max_length=20,choices=Status.choices,default=Status.PENDING,db_index=True)
    due_at=models.DateTimeField(null=True,blank=True)
    paid_at=models.DateTimeField(null=True,blank=True)
    metadata=models.JSONField(default=dict,blank=True)
