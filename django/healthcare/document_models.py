import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from core.models import TimeStampedModel

KINDS=[('prescription','Receituário'),('certificate','Atestado'),('declaration','Declaração'),('budget','Orçamento')]


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
    # Unguessable public token printed as QR code; set once at emission.
    verification_code=models.CharField(max_length=40,unique=True,null=True,blank=True,editable=False)
    # A revised budget points to the issued one it replaces; the old row stays untouched.
    replaces=models.ForeignKey('self',on_delete=models.PROTECT,null=True,blank=True,related_name='revisions')

    @property
    def replaced_by(self):
        return self.revisions.filter(status='finalized').order_by('-finalized_at','-pk').first()

    @property
    def display_code(self):
        code=(self.verification_code or '')[:12].upper()
        return '-'.join(code[i:i+4] for i in range(0,len(code),4))

    def save(self,*args,**kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk,status='finalized').exists():
            raise ValidationError('Documento emitido é imutável. Emita um novo documento para corrigir.')
        super().save(*args,**kwargs)

    def delete(self,*args,**kwargs):
        raise ValidationError('O documento deve permanecer no histórico do paciente.')


class ClinicalDocumentValidation(models.Model):
    """Append-only record of someone confirming an issued document's authenticity."""
    document=models.ForeignKey(ClinicalIssuedDocument,on_delete=models.PROTECT,related_name='validations')
    validator_name=models.CharField(max_length=120)
    validator_role=models.CharField(max_length=120,blank=True)
    ip_hash=models.CharField(max_length=64,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering=['-created_at','-pk']

    def save(self,*args,**kwargs):
        if self.pk:
            raise ValidationError('Validações registradas são preservadas.')
        super().save(*args,**kwargs)

    def delete(self,*args,**kwargs):
        raise ValidationError('Validações registradas são preservadas.')


class PatientNote(models.Model):
    """Append-only observation added to a patient's record by the clinic team (reception included)."""
    tenant=models.ForeignKey('tenants.Tenant',on_delete=models.PROTECT)
    customer=models.ForeignKey('scheduling.Customer',on_delete=models.PROTECT,related_name='patient_notes')
    text_encrypted=models.TextField()
    author=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    author_name=models.CharField(max_length=160)
    created_at=models.DateTimeField(auto_now_add=True)
    # Imported history: the date written on the clinic's old sheet (created_at stays the import time).
    occurred_at=models.DateTimeField(null=True,blank=True)
    import_key=models.CharField(max_length=80,blank=True,default='',editable=False)

    class Meta:
        ordering=['-created_at','-pk']
        constraints=[models.UniqueConstraint(fields=['tenant','import_key'],condition=~models.Q(import_key=''),name='uq_patient_note_import_key')]

    @property
    def effective_at(self):
        return self.occurred_at or self.created_at

    def save(self,*args,**kwargs):
        if self.pk:
            raise ValidationError('Observações do prontuário não podem ser alteradas.')
        super().save(*args,**kwargs)

    def delete(self,*args,**kwargs):
        raise ValidationError('Observações do prontuário ficam no histórico.')
