from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class LegalDocument(TimeStampedModel):
    class Type(models.TextChoices):
        TERMS="terms","Termos"
        PRIVACY="privacy","Privacidade"

    class Status(models.TextChoices):
        DRAFT="draft","Rascunho"
        PUBLISHED="published","Publicado"
        ARCHIVED="archived","Arquivado"

    type=models.CharField(max_length=12,choices=Type.choices)
    version=models.CharField(max_length=30)
    title=models.CharField(max_length=190)
    content=models.TextField()
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.DRAFT,db_index=True)
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
