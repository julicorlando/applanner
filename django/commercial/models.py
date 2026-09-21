import hashlib
from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class CommercialProfile(TimeStampedModel):
    user=models.OneToOneField(settings.AUTH_USER_MODEL,primary_key=True,on_delete=models.CASCADE,related_name="commercial_profile")
    commission_percent=models.DecimalField(max_digits=5,decimal_places=2,default=0)
    max_discount_percent=models.DecimalField(max_digits=5,decimal_places=2,default=0)
    active=models.BooleanField(default=True)


class Lead(TimeStampedModel):
    class Status(models.TextChoices):
        NEW="new","Novo"
        IN_SERVICE="in_service","Em atendimento"
        CONTACTED="contacted","Contatado"
        QUALIFIED="qualified","Qualificado"
        CONVERTED="converted","Convertido"
        LOST="lost","Perdido"

    name=models.CharField(max_length=160)
    phone=models.CharField(max_length=30)
    email=models.EmailField()
    business_type=models.CharField(max_length=100)
    estimated_value=models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True)
    source=models.CharField(max_length=80,default="public_interest_form")
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.NEW,db_index=True)
    assigned_to=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="commercial_leads")
    assigned_at=models.DateTimeField(null=True,blank=True)
    next_contact_at=models.DateTimeField(null=True,blank=True,db_index=True)
    contact_deadline_at=models.DateTimeField(null=True,blank=True,db_index=True)
    last_transferred_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="commercial_transfers")
    last_transferred_at=models.DateTimeField(null=True,blank=True)
    notes=models.TextField(blank=True)
    loss_reason=models.CharField(max_length=255,blank=True)
    ip_hash=models.CharField(max_length=64,blank=True)
    consent_granted=models.BooleanField(default=False)
    consent_version=models.CharField(max_length=30,blank=True)
    consent_purpose=models.CharField(max_length=255,blank=True)
    consent_at=models.DateTimeField(null=True,blank=True)
    consent_user_agent=models.CharField(max_length=500,blank=True)
    retention_until=models.DateTimeField(null=True,blank=True)
    anonymized_at=models.DateTimeField(null=True,blank=True)
    do_not_contact=models.BooleanField(default=False)

    class Meta:
        indexes=[models.Index(fields=["status","assigned_to","created_at"],name="commercial_lead_queue_idx")]


class LeadHistory(models.Model):
    class Action(models.TextChoices):
        CREATED="created","Criado"
        CLAIMED="claimed","Assumido"
        TRANSFERRED="transferred","Transferido"
        STATUS_CHANGED="status_changed","Status alterado"

    lead=models.ForeignKey(Lead,on_delete=models.CASCADE,related_name="history")
    from_user=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="+")
    to_user=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="+")
    action=models.CharField(max_length=20,choices=Action.choices)
    notes=models.CharField(max_length=500,blank=True)
    actor_user=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="commercial_lead_actions")
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["lead","created_at"],name="commercial_lead_hist_idx")]


class Proposal(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT="draft","Rascunho"
        SENT="sent","Enviada"
        VIEWED="viewed","Visualizada"
        CONVERTED="converted","Convertida"
        EXPIRED="expired","Expirada"
        CANCELLED="cancelled","Cancelada"

    class Approval(models.TextChoices):
        NOT_REQUIRED="not_required","Não necessária"
        PENDING="pending","Pendente"
        APPROVED="approved","Aprovada"
        REJECTED="rejected","Rejeitada"

    commercial_user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="commercial_proposals")
    plan=models.ForeignKey("billing.Plan",on_delete=models.PROTECT,related_name="commercial_proposals")
    base_plan=models.ForeignKey("billing.Plan",null=True,blank=True,on_delete=models.SET_NULL,related_name="+")
    title=models.CharField(max_length=160)
    customer_name=models.CharField(max_length=160,blank=True)
    customer_email=models.EmailField(blank=True)
    discount_percent=models.DecimalField(max_digits=5,decimal_places=2,default=0)
    final_price=models.DecimalField(max_digits=10,decimal_places=2)
    notes=models.TextField(blank=True)
    modules=models.JSONField(default=list,blank=True)
    features=models.JSONField(default=dict,blank=True)
    public_token=models.CharField(max_length=32,unique=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.DRAFT,db_index=True)
    approval_status=models.CharField(max_length=16,choices=Approval.choices,default=Approval.NOT_REQUIRED,db_index=True)
    approved_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="commercial_proposals_approved")
    approved_at=models.DateTimeField(null=True,blank=True)
    accepted_at=models.DateTimeField(null=True,blank=True)
    accepted_ip_hash=models.CharField(max_length=64,blank=True)
    tenant=models.ForeignKey("tenants.Tenant",null=True,blank=True,on_delete=models.SET_NULL,related_name="commercial_proposals")
    expires_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        indexes=[models.Index(fields=["commercial_user","status","created_at"],name="commercial_prop_owner_idx")]


class ProposalAcceptance(models.Model):
    proposal=models.OneToOneField(Proposal,on_delete=models.CASCADE,related_name="acceptance")
    document_hash=models.CharField(max_length=64)
    proposal_snapshot=models.JSONField()
    ip_hash=models.CharField(max_length=64,blank=True)
    user_agent=models.CharField(max_length=500,blank=True)
    accepted_at=models.DateTimeField()

    @staticmethod
    def hash_snapshot(snapshot):
        import json
        raw=json.dumps(snapshot,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
        return hashlib.sha256(raw).hexdigest()


class CommercialCommission(TimeStampedModel):
    class Status(models.TextChoices):
        PROJECTED="projected","Projetada"
        APPROVED="approved","Aprovada"
        REVERSED="reversed","Estornada"
        PAID="paid","Paga"

    commercial_user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="commercial_commissions")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="commercial_commissions")
    payment=models.ForeignKey("billing.Payment",null=True,blank=True,on_delete=models.SET_NULL,related_name="commercial_commissions")
    base_amount=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    commission_percent=models.DecimalField(max_digits=5,decimal_places=2,default=0)
    commission_amount=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.PROJECTED,db_index=True)
    approved_at=models.DateTimeField(null=True,blank=True)
    hold_until=models.DateTimeField(null=True,blank=True)
    reversed_at=models.DateTimeField(null=True,blank=True)
    paid_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["commercial_user","tenant"],name="uq_commercial_commission_tenant")]
        indexes=[models.Index(fields=["status","created_at"],name="commercial_commission_idx")]


class LeadPrivacyEvent(models.Model):
    class Action(models.TextChoices):
        CREATED="created","Criado"
        VIEWED="viewed","Visualizado"
        EXPORTED="exported","Exportado"
        CONSENT_UPDATED="consent_updated","Consentimento atualizado"
        DO_NOT_CONTACT="do_not_contact","Não contatar"
        ANONYMIZED="anonymized","Anonimizado"
        DELETED="deleted","Excluído"

    lead=models.ForeignKey(Lead,on_delete=models.CASCADE,related_name="privacy_events")
    action=models.CharField(max_length=24,choices=Action.choices)
    actor_user=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="commercial_privacy_events")
    ip_hash=models.CharField(max_length=64,blank=True)
    metadata=models.JSONField(default=dict,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["lead","created_at"],name="commercial_privacy_idx")]
