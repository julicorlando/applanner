from django.db import models
from core.models import TimeStampedModel


class Tenant(TimeStampedModel):
    class Status(models.TextChoices):
        TRIAL="trial","Teste"
        ACTIVE="active","Ativo"
        SUSPENDED="suspended","Suspenso"
        CANCELLED="cancelled","Cancelado"

    name=models.CharField(max_length=150)
    slug=models.SlugField(max_length=120,unique=True)
    public_slug=models.SlugField(max_length=120,unique=True,null=True,blank=True)
    public_short_code=models.CharField(max_length=16,unique=True,null=True,blank=True)
    public_booking_enabled=models.BooleanField(default=True)
    category=models.CharField(max_length=60,blank=True)
    document=models.CharField(max_length=32,blank=True)
    email=models.EmailField(blank=True)
    phone=models.CharField(max_length=32,blank=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.TRIAL,db_index=True)
    locale=models.CharField(max_length=10,default="pt-br")
    default_locale=models.CharField(max_length=10,default="pt-br")
    timezone=models.CharField(max_length=64,default="America/Recife")
    public_layout=models.CharField(max_length=24,default="editorial")
    public_headline=models.CharField(max_length=120,blank=True)
    public_subheadline=models.CharField(max_length=300,blank=True)
    public_cta_label=models.CharField(max_length=60,blank=True)
    public_announcement=models.CharField(max_length=160,blank=True)
    public_accent_color=models.CharField(max_length=7,blank=True)
    public_section_order=models.JSONField(default=list,blank=True)
    public_seo_title=models.CharField(max_length=70,blank=True)
    public_seo_description=models.CharField(max_length=180,blank=True)
    public_instagram=models.CharField(max_length=120,blank=True)
    metadata=models.JSONField(default=dict,blank=True)

    def __str__(self):
        return self.name
