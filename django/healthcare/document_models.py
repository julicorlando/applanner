import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from core.models import TimeStampedModel

KINDS=[('prescription','Receituário'),('certificate','Atestado'),('declaration','Declaração')]


class ProfessionalSignature(TimeStampedModel):
    professional=models.OneToOneField('scheduling.Professional',on_delete=models.PROTECT)
    image_encrypted=models.BinaryField(default=bytes,blank=True)
    sha256=models.CharField(max_length=64,blank=True)
    updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)


class ClinicalDocumentTemplate(TimeStampedModel):
    tenant=models.ForeignKey('tenants.Tenant',on_delete=models.CASCADE)
    professional=models.ForeignKey('scheduling.Professional',on_delete=models.PROTECT,null=True,blank=True)
    name=models.CharField(max_length=100)
    kind=models.CharField(max_length=20,choices=KINDS)
    text_encrypted=models.TextField()
    active=models.BooleanField(default=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)


class IssuedDocumentQuerySet(models.QuerySet):
    def update(self,**kwargs):
        raise ValidationError('Use o fluxo de revisão; documentos emitidos são imutáveis.')
    def delete(self):
        raise ValidationError('Documentos clínicos são preservados no histórico.')
    def bulk_update(self,*args,**kwargs):
        raise ValidationError('Use o fluxo de revisão de documentos.')


class ClinicalIssuedDocument(TimeStampedModel):
    objects=IssuedDocumentQuerySet.as_manager()
    tenant=models.ForeignKey('tenants.Tenant',on_delete=models.PROTECT)
    customer=models.ForeignKey('scheduling.Customer',on_delete=models.PROTECT,related_name='clinical_documents')
    professional=models.ForeignKey('scheduling.Professional',on_delete=models.PROTECT)
    template=models.ForeignKey(ClinicalDocumentTemplate,on_delete=models.PROTECT,null=True,blank=True)
    kind=models.CharField(max_length=20,choices=KINDS)
    title=models.CharField(max_length=150)
    body_encrypted=models.TextField()
    status=models.CharField(max_length=12,choices=[('draft','Rascunho'),('finalized','Emitido')],default='draft')
    version=models.PositiveIntegerField(default=1)
    request_id=models.UUIDField(default=uuid.uuid4,unique=True)
    pdf_encrypted=models.BinaryField(default=bytes,blank=True)
    sha256=models.CharField(max_length=64,blank=True)
    signature_snapshot_encrypted=models.TextField(blank=True)
    entry=models.OneToOneField('healthcare.MedicalRecordEntry',on_delete=models.PROTECT,null=True,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    finalized_at=models.DateTimeField(null=True,blank=True)

    def save(self,*args,**kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk,status='finalized').exists():
            raise ValidationError('Documento emitido é imutável. Emita um novo documento para corrigir.')
        super().save(*args,**kwargs)

    def delete(self,*args,**kwargs):
        raise ValidationError('O documento deve permanecer no histórico do paciente.')
