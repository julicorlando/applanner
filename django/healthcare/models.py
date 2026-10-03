from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class MedicalRecordEntry(models.Model):
    class Type(models.TextChoices):
        EVOLUTION="evolution","Evolução"
        ANAMNESIS="anamnesis","Anamnese"
        PROCEDURE="procedure","Procedimento"
        OBSERVATION="observation","Observação"
        FOLLOW_UP="follow_up","Acompanhamento"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="medical_records")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.PROTECT,related_name="medical_records")
    professional=models.ForeignKey("scheduling.Professional",on_delete=models.PROTECT,related_name="medical_records")
    appointment=models.ForeignKey("scheduling.Appointment",null=True,blank=True,on_delete=models.SET_NULL,related_name="medical_records")
    record_type=models.CharField(max_length=20,choices=Type.choices,default=Type.EVOLUTION)
    title=models.CharField(max_length=190)
    content_encrypted=models.TextField()
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="medical_records_created")
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[
            models.Index(fields=["tenant","customer","created_at"],name="health_record_customer_idx"),
            models.Index(fields=["tenant","professional","created_at"],name="health_record_prof_idx"),
        ]


class MedicalRecordAccessLog(models.Model):
    class Action(models.TextChoices):
        VIEW="view","Visualização"
        CREATE="create","Criação"
        EXPORT="export","Exportação"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="medical_record_access")
    entry=models.ForeignKey(MedicalRecordEntry,on_delete=models.CASCADE,related_name="access_log")
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="medical_record_access")
    action=models.CharField(max_length=12,choices=Action.choices)
    ip_hash=models.CharField(max_length=64,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
