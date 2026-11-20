from django.db import models
from core.models import TimeStampedModel


class BirthdaySettings(TimeStampedModel):
    tenant=models.OneToOneField('tenants.Tenant',on_delete=models.CASCADE)
    enabled=models.BooleanField(default=False)
    channel=models.CharField(max_length=16,choices=[('whatsapp','WhatsApp da clínica'),('email','E-mail')],default='whatsapp')
    hour=models.PositiveSmallIntegerField(default=9)
    message=models.CharField(max_length=600,default='Olá, {nome}! A equipe {empresa} deseja um feliz aniversário, com muita saúde e alegria!')


class BirthdayDelivery(models.Model):
    tenant=models.ForeignKey('tenants.Tenant',on_delete=models.PROTECT)
    customer=models.ForeignKey('scheduling.Customer',on_delete=models.PROTECT,related_name='birthday_deliveries')
    year=models.PositiveSmallIntegerField()
    day=models.DateField()
    notification=models.OneToOneField('communications.Notification',on_delete=models.PROTECT)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['tenant','customer','year'],name='uq_birthday_customer_year')]
