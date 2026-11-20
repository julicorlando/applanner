from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class ClinicalDriveConfiguration(TimeStampedModel):
    tenant=models.OneToOneField('tenants.Tenant',on_delete=models.CASCADE)
    client_id=models.CharField(max_length=300,blank=True)
    client_secret_encrypted=models.TextField(blank=True)
    refresh_token_encrypted=models.TextField(blank=True)
    account_email=models.EmailField(blank=True)
    folder_id=models.CharField(max_length=200,blank=True)
    generation=models.PositiveIntegerField(default=1)
    enabled=models.BooleanField(default=False)
    hour=models.PositiveSmallIntegerField(default=3)
    authorized_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True)
    authorized_at=models.DateTimeField(null=True,blank=True)
    last_queued_day=models.DateField(null=True,blank=True)
    last_error_code=models.CharField(max_length=80,blank=True)


class PatientDriveBackup(TimeStampedModel):
    configuration=models.ForeignKey(ClinicalDriveConfiguration,on_delete=models.PROTECT,related_name='backups')
    customer=models.ForeignKey('scheduling.Customer',on_delete=models.PROTECT)
    generation=models.PositiveIntegerField()
    file_id=models.CharField(max_length=200,blank=True)
    source_sha256=models.CharField(max_length=64,blank=True)
    pdf_sha256=models.CharField(max_length=64,blank=True)
    pdf_md5=models.CharField(max_length=32,blank=True)
    status=models.CharField(max_length=20,default='pending',choices=[('pending','Pendente'),('processing','Processando'),('success','Atualizado'),('unchanged','Sem alterações'),('failed','Falhou'),('skipped','Ignorado')])
    last_checked_at=models.DateTimeField(null=True,blank=True)
    last_uploaded_at=models.DateTimeField(null=True,blank=True)
    started_at=models.DateTimeField(null=True,blank=True)
    last_error_code=models.CharField(max_length=80,blank=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['configuration','customer','generation'],name='uq_clinical_drive_patient')]
