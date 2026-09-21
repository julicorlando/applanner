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
        indexes=[models.Index(fields=["tenant","name"]),models.Index(fields=["tenant","phone"])]


class Professional(TimeStampedModel):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="professionals")
    user=models.OneToOneField(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL)
    name=models.CharField(max_length=150)
    public_slug=models.SlugField(max_length=120,blank=True)
    email=models.EmailField(blank=True)
    phone=models.CharField(max_length=32,blank=True)
    specialty=models.CharField(max_length=150,blank=True)
    photo=models.ImageField(upload_to="professionals/",blank=True)
    commission_percent=models.DecimalField(max_digits=5,decimal_places=2,null=True,blank=True)
    active=models.BooleanField(default=True)
    services=models.ManyToManyField("Service",through="ProfessionalService",related_name="professionals",blank=True)

    class Meta:
        constraints=[
            models.UniqueConstraint(fields=["tenant","public_slug"],name="uq_professional_public_slug"),
        ]


class ProfessionalService(models.Model):
    professional=models.ForeignKey(Professional,on_delete=models.CASCADE)
    service=models.ForeignKey("Service",on_delete=models.CASCADE)

    class Meta:
        constraints=[
            models.UniqueConstraint(fields=["professional","service"],name="uq_professional_service"),
        ]


class Service(TimeStampedModel):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="services")
    name=models.CharField(max_length=150)
    description=models.TextField(blank=True)
    duration_minutes=models.PositiveSmallIntegerField()
    price=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    active=models.BooleanField(default=True)


class Appointment(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING="pending","Pendente"
        CONFIRMED="confirmed","Confirmado"
        IN_PROGRESS="in_progress","Em atendimento"
        COMPLETED="completed","Concluído"
        CANCELLED="cancelled","Cancelado"
        NO_SHOW="no_show","Faltou"

    class Source(models.TextChoices):
        PUBLIC="public","Público"
        INTERNAL="internal","Interno"
        WHATSAPP="whatsapp","WhatsApp"
        API="api","API"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="appointments")
    customer=models.ForeignKey(Customer,on_delete=models.PROTECT,related_name="appointments")
    professional=models.ForeignKey(Professional,null=True,blank=True,on_delete=models.SET_NULL,related_name="appointments")
    service=models.ForeignKey(Service,on_delete=models.PROTECT,related_name="appointments")
    starts_at=models.DateTimeField(db_index=True)
    ends_at=models.DateTimeField()
    status=models.CharField(max_length=20,choices=Status.choices,default=Status.PENDING,db_index=True)
    source=models.CharField(max_length=20,choices=Source.choices,default=Source.INTERNAL)
    notes=models.TextField(blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL)

    class Meta:
        indexes=[models.Index(fields=["tenant","starts_at"]),models.Index(fields=["tenant","status","starts_at"])]
        constraints=[models.CheckConstraint(condition=models.Q(ends_at__gt=models.F("starts_at")),name="appointment_end_after_start")]
