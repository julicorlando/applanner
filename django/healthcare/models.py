import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


class ClinicalRecordQuerySet(models.QuerySet):
    def update(self, **kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Registros clínicos são imutáveis. Crie uma retificação.")

    def delete(self):
        from django.core.exceptions import ValidationError
        raise ValidationError("Registros clínicos devem ser preservados; exclusão exige processo de retenção próprio.")

    def bulk_update(self, objs, fields, batch_size=None):
        from django.core.exceptions import ValidationError
        raise ValidationError("Registros clínicos são imutáveis. Crie uma retificação.")


class MedicalRecordEntry(models.Model):
    objects=ClinicalRecordQuerySet.as_manager()
    class Type(models.TextChoices):
        EVOLUTION="evolution","Evolução"
        PHYSIO_EVALUATION="physio_evaluation","Avaliação fisioterápica"
        PHYSIO_EVOLUTION="physio_evolution","Evolução fisioterápica"
        ANAMNESIS="anamnesis","Anamnese"
        PROCEDURE="procedure","Procedimento"
        OBSERVATION="observation","Observação"
        FOLLOW_UP="follow_up","Acompanhamento"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.PROTECT,related_name="medical_records")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.PROTECT,related_name="medical_records")
    professional=models.ForeignKey("scheduling.Professional",on_delete=models.PROTECT,related_name="medical_records")
    appointment=models.ForeignKey("scheduling.Appointment",null=True,blank=True,on_delete=models.PROTECT,related_name="medical_records")
    physiotherapy_assessment=models.ForeignKey("PhysiotherapyAssessment",on_delete=models.PROTECT,null=True,blank=True,related_name="clinical_entries")
    record_type=models.CharField(max_length=20,choices=Type.choices,default=Type.EVOLUTION)
    title=models.CharField(max_length=190)
    content_encrypted=models.TextField()
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="medical_records_created")
    created_at=models.DateTimeField(default=timezone.now,editable=False)
    professional_snapshot=models.JSONField(default=dict,db_default={},blank=True)
    supersedes=models.ForeignKey("self",null=True,blank=True,on_delete=models.PROTECT,related_name="rectifications")
    correction_reason_encrypted=models.TextField(blank=True,db_default="")

    def delete(self,*args,**kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Registro clínico preservado; exclusão não permitida.")

    def save(self,*args,**kwargs):
        if not self._state.adding:
            from django.core.exceptions import ValidationError
            raise ValidationError("Registros clínicos são imutáveis. Crie uma retificação.")
        super().save(*args,**kwargs)

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


class ClinicalRegistration(models.Model):
    professional=models.OneToOneField("scheduling.Professional",on_delete=models.PROTECT,related_name="clinical_registration")
    council=models.CharField(max_length=10,choices=[("CRO","CRO"),("CREFITO","CREFITO")])
    number=models.CharField(max_length=40)
    jurisdiction=models.CharField(max_length=4)
    specialties=models.CharField(max_length=300,blank=True)
    professional_name=models.CharField(max_length=190,blank=True,db_default="")
    updated_at=models.DateTimeField(auto_now=True)

    def clean(self):
        import re
        from django.core.exceptions import ValidationError
        if not re.fullmatch(r"[0-9A-Za-z./-]{1,40}",self.number or ""):
            raise ValidationError({"number":"Registro profissional inválido."})
        self.jurisdiction=(self.jurisdiction or "").upper().strip()
        if self.council=="CRO" and self.jurisdiction not in "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split():
            raise ValidationError({"jurisdiction":"Informe a UF do CRO."})
        if self.council=="CREFITO" and not re.fullmatch(r"[1-9][0-9]?",self.jurisdiction):
            raise ValidationError({"jurisdiction":"Informe a região numérica do CREFITO."})

    def snapshot(self):
        return {"name":self.professional_name or (self.professional.user.get_full_name() if self.professional.user_id else "") or self.professional.name,"council":self.council,"number":self.number,
                "jurisdiction":self.jurisdiction,"specialties":self.specialties}


class ClinicalCareGrant(models.Model):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.PROTECT)
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.PROTECT)
    source_professional=models.ForeignKey("scheduling.Professional",on_delete=models.PROTECT,related_name="grants_given")
    grantee=models.ForeignKey("scheduling.Professional",on_delete=models.PROTECT,related_name="care_grants")
    granted_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="care_grants_given")
    justification_encrypted=models.TextField()
    created_at=models.DateTimeField(auto_now_add=True)
    revoked_at=models.DateTimeField(null=True,blank=True)
    revoked_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name="care_grants_revoked")


class ClinicalAttachment(models.Model):
    class Kind(models.TextChoices):
        EXAM="exam","Exame / radiografia"
        CONSENT="consent","Consentimento / documento assinado"
        IMAGE="image","Imagem clínica"
        DOCUMENT="document","Documento"
    entry=models.ForeignKey(MedicalRecordEntry,on_delete=models.PROTECT,related_name="attachments")
    kind=models.CharField(max_length=12,choices=Kind.choices,default=Kind.DOCUMENT)
    filename_encrypted=models.TextField()
    content_encrypted=models.BinaryField()
    mime_type=models.CharField(max_length=80)
    sha256=models.CharField(max_length=64)
    size=models.PositiveIntegerField()
    attestation=models.BooleanField(default=False)
    uploaded_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)

    def save(self,*args,**kwargs):
        if not self._state.adding:
            from django.core.exceptions import ValidationError
            raise ValidationError("Documento preservado; anexe uma nova versão.")
        return super().save(*args,**kwargs)


class ClinicalTreatmentPlan(models.Model):
    class Status(models.TextChoices):
        PROPOSED="proposed","Proposto"
        ACCEPTED="accepted","Aprovado pelo paciente"
        DECLINED="declined","Recusado"
        IN_PROGRESS="in_progress","Em tratamento"
        COMPLETED="completed","Concluído"
    entry=models.OneToOneField(MedicalRecordEntry,on_delete=models.PROTECT,related_name="treatment_budget")
    total=models.DecimalField(max_digits=12,decimal_places=2)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.PROPOSED)
    updated_at=models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Plano #{self.pk} — {self.entry.customer.name}"


class ClinicalFollowUp(models.Model):
    entry=models.ForeignKey(MedicalRecordEntry,on_delete=models.PROTECT,related_name="followups")
    due_at=models.DateField()
    note_encrypted=models.TextField()
    completed_at=models.DateTimeField(null=True,blank=True)
    completed_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)


class ClinicalSessionUsage(models.Model):
    entry=models.OneToOneField(MedicalRecordEntry,on_delete=models.PROTECT,related_name="session_usage")
    usage=models.OneToOneField("engagement.CustomerPackageUsage",on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)


class AssessmentQuerySet(models.QuerySet):
    def update(self, **kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Use o fluxo de revisão da avaliação clínica.")

    def delete(self):
        from django.core.exceptions import ValidationError
        raise ValidationError("Avaliações clínicas devem ser preservadas.")

    def bulk_update(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Use o fluxo de revisão da avaliação clínica.")


class PhysiotherapyAssessment(models.Model):
    submission_key=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    class Status(models.TextChoices):
        DRAFT="draft","Rascunho"
        FINALIZED="finalized","Finalizada"

    objects=AssessmentQuerySet.as_manager()
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.PROTECT)
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.PROTECT,related_name="physio_assessments")
    professional=models.ForeignKey("scheduling.Professional",on_delete=models.PROTECT)
    appointment=models.ForeignKey("scheduling.Appointment",on_delete=models.PROTECT,null=True,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.DRAFT)
    version=models.PositiveIntegerField(default=0)
    payload_encrypted=models.TextField()
    final_entry=models.OneToOneField(MedicalRecordEntry,on_delete=models.PROTECT,null=True,blank=True,related_name="physio_assessment")
    signed_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)

    def save(self,*args,**kwargs):
        from django.core.exceptions import ValidationError
        if self.pk and type(self)._base_manager.filter(pk=self.pk,status=self.Status.FINALIZED).exists():
            raise ValidationError("Avaliação finalizada é imutável. Registre evolução ou retificação.")
        super().save(*args,**kwargs)

    def delete(self,*args,**kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Avaliações clínicas devem ser preservadas.")

    class Meta:
        constraints=[models.CheckConstraint(condition=(models.Q(status="draft",final_entry__isnull=True,signed_at__isnull=True) | models.Q(status="finalized",final_entry__isnull=False,signed_at__isnull=False)),name="physio_assessment_final_state")]
        indexes=[models.Index(fields=["tenant","customer","created_at"],name="physio_assessment_patient_idx"),
                 models.Index(fields=["tenant","professional","status"],name="physio_assessment_status_idx")]


class PhysiotherapyAssessmentVersion(models.Model):
    objects=ClinicalRecordQuerySet.as_manager()
    assessment=models.ForeignKey(PhysiotherapyAssessment,on_delete=models.PROTECT,related_name="versions")
    number=models.PositiveIntegerField()
    status=models.CharField(max_length=16,choices=PhysiotherapyAssessment.Status.choices)
    payload_encrypted=models.TextField()
    sha256=models.CharField(max_length=64)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)

    def save(self,*args,**kwargs):
        from django.core.exceptions import ValidationError
        if not self._state.adding:raise ValidationError("Histórico de avaliação é imutável.")
        super().save(*args,**kwargs)

    def delete(self,*args,**kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Histórico de avaliação é imutável.")

    class Meta:
        constraints=[models.UniqueConstraint(fields=["assessment","number"],name="uq_physio_assessment_version")]
        ordering=["number"]


class PhysiotherapyAssessmentDocument(models.Model):
    objects=AssessmentQuerySet.as_manager()
    assessment=models.ForeignKey(PhysiotherapyAssessment,on_delete=models.PROTECT,related_name="documents")
    filename_encrypted=models.TextField()
    content_encrypted=models.BinaryField()
    mime_type=models.CharField(max_length=80)
    sha256=models.CharField(max_length=64)
    size=models.PositiveIntegerField()
    uploaded_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    removed_at=models.DateTimeField(null=True,blank=True)
    final_document=models.OneToOneField(ClinicalAttachment,on_delete=models.PROTECT,null=True,blank=True)

    def save(self,*args,**kwargs):
        from django.core.exceptions import ValidationError
        if PhysiotherapyAssessment.objects.filter(pk=self.assessment_id,status="finalized").exists():
            raise ValidationError("Documento de avaliação finalizada é imutável.")
        super().save(*args,**kwargs)

    def delete(self,*args,**kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Desvincule o documento no rascunho; o histórico é preservado.")


class DentalAssessment(models.Model):
    submission_key=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    class Status(models.TextChoices):
        DRAFT="draft","Rascunho"
        FINALIZED="finalized","Finalizada"

    objects=AssessmentQuerySet.as_manager()
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.PROTECT)
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.PROTECT,related_name="dental_assessments")
    professional=models.ForeignKey("scheduling.Professional",on_delete=models.PROTECT)
    appointment=models.ForeignKey("scheduling.Appointment",on_delete=models.PROTECT,null=True,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.DRAFT)
    version=models.PositiveIntegerField(default=0)
    payload_encrypted=models.TextField()
    final_entry=models.OneToOneField(MedicalRecordEntry,on_delete=models.PROTECT,null=True,blank=True,related_name="dental_assessment")
    treatment_plan=models.OneToOneField(ClinicalTreatmentPlan,on_delete=models.PROTECT,null=True,blank=True,related_name="dental_assessment")
    signed_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)

    def save(self,*args,**kwargs):
        from django.core.exceptions import ValidationError
        if self.pk and type(self)._base_manager.filter(pk=self.pk,status=self.Status.FINALIZED).exists():
            raise ValidationError("Avaliação finalizada é imutável. Registre evolução ou retificação.")
        super().save(*args,**kwargs)

    def delete(self,*args,**kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Avaliações clínicas devem ser preservadas.")

    class Meta:
        constraints=[models.CheckConstraint(condition=(models.Q(status="draft",final_entry__isnull=True,signed_at__isnull=True) | models.Q(status="finalized",final_entry__isnull=False,signed_at__isnull=False)),name="dental_assessment_final_state")]
        indexes=[models.Index(fields=["tenant","customer","created_at"],name="dental_assessment_patient_idx"),
                 models.Index(fields=["tenant","professional","status"],name="dental_assessment_status_idx")]


class DentalAssessmentVersion(models.Model):
    objects=ClinicalRecordQuerySet.as_manager()
    assessment=models.ForeignKey(DentalAssessment,on_delete=models.PROTECT,related_name="versions")
    number=models.PositiveIntegerField()
    status=models.CharField(max_length=16,choices=DentalAssessment.Status.choices)
    payload_encrypted=models.TextField()
    sha256=models.CharField(max_length=64)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)

    def save(self,*args,**kwargs):
        from django.core.exceptions import ValidationError
        if not self._state.adding:raise ValidationError("Histórico de avaliação é imutável.")
        super().save(*args,**kwargs)

    def delete(self,*args,**kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Histórico de avaliação é imutável.")

    class Meta:
        constraints=[models.UniqueConstraint(fields=["assessment","number"],name="uq_dental_assessment_version")]
        ordering=["number"]


class DentalAssessmentDocument(models.Model):
    objects=AssessmentQuerySet.as_manager()
    assessment=models.ForeignKey(DentalAssessment,on_delete=models.PROTECT,related_name="documents")
    kind=models.CharField(max_length=12,choices=[("radiograph","Radiografia"),("photo","Foto clínica"),("document","Documento")],default="document")
    filename_encrypted=models.TextField()
    content_encrypted=models.BinaryField()
    mime_type=models.CharField(max_length=80)
    sha256=models.CharField(max_length=64)
    size=models.PositiveIntegerField()
    uploaded_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    removed_at=models.DateTimeField(null=True,blank=True)
    final_document=models.OneToOneField(ClinicalAttachment,on_delete=models.PROTECT,null=True,blank=True)

    def save(self,*args,**kwargs):
        from django.core.exceptions import ValidationError
        if DentalAssessment.objects.filter(pk=self.assessment_id,status="finalized").exists():
            raise ValidationError("Documento de avaliação finalizada é imutável.")
        super().save(*args,**kwargs)

    def delete(self,*args,**kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Desvincule o documento no rascunho; o histórico é preservado.")

# Kept separate to make operational/offline records distinct from the clinical ledger.
from .operation_models import WaitingRoomDisplay, WaitingRoomMedia, WaitingRoomCall, OfflineOperation  # noqa: F401,E402
