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
    document=models.CharField(max_length=32,blank=True)
    email=models.EmailField(blank=True)
    phone=models.CharField(max_length=32,blank=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.TRIAL,db_index=True)
    locale=models.CharField(max_length=10,default="pt-br")
    timezone=models.CharField(max_length=64,default="America/Recife")
    metadata=models.JSONField(default=dict,blank=True)

    def __str__(self):
        return self.name
