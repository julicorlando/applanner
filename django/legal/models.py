from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class LegalDocument(TimeStampedModel):
    class Type(models.TextChoices):
        TERMS="terms","Termos gerais"
        TERMS_COMPANY="terms_company","Termos de uso · Empresas"
        TERMS_CUSTOMER="terms_customer","Termos de uso · Clientes"
        PRIVACY="privacy","Política de privacidade"
        CANCELLATION_COMPANY="cancellation_company","Política de cancelamento · Empresas"
        CANCELLATION_CUSTOMER="cancellation_customer","Política de cancelamento · Clientes"

    class Status(models.TextChoices):
        DRAFT="draft","Rascunho"
        PUBLISHED="published","Publicado"
        ARCHIVED="archived","Arquivado"

    type=models.CharField(max_length=32,choices=Type.choices)
    version=models.CharField(max_length=30)
    title=models.CharField(max_length=190)
    content=models.TextField()
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.DRAFT,db_index=True)
    requires_acceptance=models.BooleanField(default=True)
    published_at=models.DateTimeField(null=True,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="legal_documents")

    class Meta:
        constraints=[models.UniqueConstraint(fields=["type","version"],name="uq_legal_type_version")]
        indexes=[models.Index(fields=["type","status","published_at"],name="legal_current_idx")]


class LegalAcceptance(models.Model):
    document=models.ForeignKey(LegalDocument,on_delete=models.PROTECT,related_name="acceptances")
    tenant=models.ForeignKey("tenants.Tenant",null=True,blank=True,on_delete=models.SET_NULL,related_name="legal_acceptances")
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="legal_acceptances")
    ip_address=models.GenericIPAddressField(null=True,blank=True)
    user_agent=models.CharField(max_length=500,blank=True)
    accepted_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["user","document"],name="uq_legal_acceptance")]
        indexes=[models.Index(fields=["tenant","accepted_at"],name="legal_accept_tenant_idx")]


class CustomerConsent(models.Model):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="customer_consents")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.CASCADE,related_name="consents")
    type=models.CharField(max_length=60)
    granted=models.BooleanField()
    version=models.CharField(max_length=30)
    source=models.CharField(max_length=40)
    ip_address=models.GenericIPAddressField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","customer","type","created_at"],name="legal_consent_customer_idx")]


class DataSubjectRequest(TimeStampedModel):
    class Type(models.TextChoices):
        EXPORT="export","Exportação de dados"
        CORRECTION="correction","Correção de dados"
        DELETION="deletion","Exclusão de dados"
        CONSENT="consent","Consentimento / marketing"

    class Status(models.TextChoices):
        OPEN="open","Aberta"
        IN_REVIEW="in_review","Em análise"
        WAITING_IDENTITY="waiting_identity","Aguardando validação de identidade"
        COMPLETED="completed","Concluída"
        REJECTED="rejected","Rejeitada"
        CANCELLED="cancelled","Cancelada"

    tenant=models.ForeignKey(
        "tenants.Tenant",null=True,blank=True,on_delete=models.SET_NULL,
        related_name="data_subject_requests",
    )
    user=models.ForeignKey(
        settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,
        related_name="data_subject_requests",
    )
    request_type=models.CharField(max_length=20,choices=Type.choices)
    status=models.CharField(max_length=24,choices=Status.choices,default=Status.OPEN,db_index=True)
    requester_name=models.CharField(max_length=160)
    requester_email=models.EmailField()
    requester_phone=models.CharField(max_length=32,blank=True)
    details=models.TextField(blank=True)
    deadline_at=models.DateTimeField(null=True,blank=True,db_index=True)
    reviewed_by=models.ForeignKey(
        settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,
        related_name="data_subject_requests_reviewed",
    )
    reviewed_at=models.DateTimeField(null=True,blank=True)
    completed_at=models.DateTimeField(null=True,blank=True)
    resolution_notes=models.TextField(blank=True)
    source=models.CharField(max_length=24,default="privacy_center")
    ip_address=models.GenericIPAddressField(null=True,blank=True)

    class Meta:
        indexes=[
            models.Index(fields=["status","deadline_at"],name="legal_dsr_status_due_idx"),
            models.Index(fields=["requester_email","created_at"],name="legal_dsr_email_idx"),
        ]
