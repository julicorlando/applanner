import secrets
import uuid
from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class Notification(models.Model):
    class Channel(models.TextChoices):
        EMAIL="email","E-mail"
        WHATSAPP="whatsapp","WhatsApp"
        SMS="sms","SMS"
        PUSH="push","Push"
        INTERNAL="internal","Interna"

    class Status(models.TextChoices):
        QUEUED="queued","Na fila"
        SENT="sent","Enviada"
        FAILED="failed","Falhou"
        CANCELLED="cancelled","Cancelada"
        SKIPPED="skipped","Ignorada"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="notifications")
    customer=models.ForeignKey("scheduling.Customer",null=True,blank=True,on_delete=models.SET_NULL,related_name="notifications")
    channel=models.CharField(max_length=16,choices=Channel.choices)
    template_key=models.CharField(max_length=100,blank=True)
    destination=models.CharField(max_length=190,blank=True)
    payload=models.JSONField(default=dict,blank=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.QUEUED,db_index=True)
    provider_reference=models.CharField(max_length=190,blank=True)
    scheduled_at=models.DateTimeField(null=True,blank=True,db_index=True)
    sent_at=models.DateTimeField(null=True,blank=True)
    delivered_at=models.DateTimeField(null=True,blank=True)
    clicked_at=models.DateTimeField(null=True,blank=True)
    error_message=models.CharField(max_length=500,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["status","scheduled_at"])]


class UserNotification(models.Model):
    class Severity(models.TextChoices):
        INFO="info","Informação"
        SUCCESS="success","Sucesso"
        WARNING="warning","Aviso"
        DANGER="danger","Crítico"

    tenant=models.ForeignKey("tenants.Tenant",null=True,blank=True,on_delete=models.CASCADE,related_name="user_notifications")
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="notifications")
    type=models.CharField(max_length=60)
    title=models.CharField(max_length=190)
    message=models.CharField(max_length=500)
    action_url=models.CharField(max_length=255,blank=True)
    severity=models.CharField(max_length=12,choices=Severity.choices,default=Severity.INFO)
    read_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["user","read_at","created_at"])]


class CustomerCampaign(TimeStampedModel):
    class Type(models.TextChoices):
        RETURN="return","Retorno"
        IDLE="idle","Ocioso"
        INACTIVE="inactive","Inativo"
        BIRTHDAY="birthday","Aniversário"
        PROMOTION="promotion","Promoção"

    class Channel(models.TextChoices):
        EMAIL="email","E-mail"
        WHATSAPP="whatsapp","WhatsApp"

    class Status(models.TextChoices):
        DRAFT="draft","Rascunho"
        QUEUED="queued","Na fila"
        RUNNING="running","Executando"
        COMPLETED="completed","Concluída"
        CANCELLED="cancelled","Cancelada"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="campaigns")
    name=models.CharField(max_length=150)
    type=models.CharField(max_length=16,choices=Type.choices)
    channel=models.CharField(max_length=16,choices=Channel.choices)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.DRAFT,db_index=True)
    message=models.TextField()
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="customer_campaigns")


class CampaignRecipient(models.Model):
    class Status(models.TextChoices):
        QUEUED="queued","Na fila"
        SENT="sent","Enviado"
        DELIVERED="delivered","Entregue"
        CLICKED="clicked","Clicado"
        CONVERTED="converted","Convertido"
        FAILED="failed","Falhou"
        OPTED_OUT="opted_out","Descadastrado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="campaign_recipients")
    campaign=models.ForeignKey(CustomerCampaign,on_delete=models.CASCADE,related_name="recipients")
    customer=models.ForeignKey("scheduling.Customer",on_delete=models.CASCADE,related_name="campaign_recipients")
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.QUEUED,db_index=True)
    sent_at=models.DateTimeField(null=True,blank=True)
    converted_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["campaign","customer"],name="uq_campaign_customer")]
        indexes=[models.Index(fields=["tenant","status"])]


class RevenueAttribution(models.Model):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="revenue_attributions")
    campaign_recipient=models.ForeignKey(CampaignRecipient,on_delete=models.CASCADE,related_name="attributions")
    appointment=models.OneToOneField("scheduling.Appointment",on_delete=models.CASCADE,related_name="revenue_attribution")
    amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    attributed_at=models.DateTimeField()


class MarketingLead(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE="active","Ativo"
        UNSUBSCRIBED="unsubscribed","Descadastrado"
        BOUNCED="bounced","Bounce"

    class Source(models.TextChoices):
        MANUAL="manual","Manual"
        LIST="list","Lista"
        CSV="csv","CSV"

    name=models.CharField(max_length=160)
    email=models.EmailField(unique=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.ACTIVE,db_index=True)
    source=models.CharField(max_length=12,choices=Source.choices,default=Source.MANUAL)
    unsubscribe_token=models.CharField(max_length=64,unique=True)
    consent_at=models.DateTimeField(null=True,blank=True)
    unsubscribed_at=models.DateTimeField(null=True,blank=True)


class MarketingCampaign(TimeStampedModel):
    class Status(models.TextChoices):
        QUEUED="queued","Na fila"
        SENDING="sending","Enviando"
        COMPLETED="completed","Concluída"
        CANCELLED="cancelled","Cancelada"

    subject=models.CharField(max_length=190)
    body=models.TextField()
    image=models.ImageField(upload_to="marketing/",blank=True)
    image_url=models.URLField(max_length=700,blank=True)
    image_alt=models.CharField(max_length=190,blank=True)
    card_link_url=models.URLField(max_length=700,blank=True)
    active=models.BooleanField(default=True)
    deleted_at=models.DateTimeField(null=True,blank=True)
    source_campaign=models.ForeignKey("self",null=True,blank=True,on_delete=models.SET_NULL,related_name="resends")
    resend_number=models.PositiveIntegerField(default=0)
    resent_at=models.DateTimeField(null=True,blank=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.QUEUED,db_index=True)
    total_count=models.PositiveIntegerField(default=0)
    sent_count=models.PositiveIntegerField(default=0)
    failed_count=models.PositiveIntegerField(default=0)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="marketing_campaigns")
    queued_at=models.DateTimeField(null=True,blank=True)
    completed_at=models.DateTimeField(null=True,blank=True)


class MarketingDelivery(TimeStampedModel):
    class Status(models.TextChoices):
        QUEUED="queued","Na fila"
        SENT="sent","Enviado"
        FAILED="failed","Falhou"
        SKIPPED="skipped","Ignorado"

    campaign=models.ForeignKey(MarketingCampaign,on_delete=models.CASCADE,related_name="deliveries")
    lead=models.ForeignKey(MarketingLead,on_delete=models.CASCADE,related_name="deliveries")
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.QUEUED,db_index=True)
    error_message=models.CharField(max_length=500,blank=True)
    sent_at=models.DateTimeField(null=True,blank=True)
    opened_at=models.DateTimeField(null=True,blank=True)
    clicked_at=models.DateTimeField(null=True,blank=True)
    tracking_token=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["campaign","lead"],name="uq_marketing_delivery")]
        indexes=[models.Index(fields=["campaign","status"])]


class WhatsAppConversation(TimeStampedModel):
    class Status(models.TextChoices):
        BOT="bot","Bot"
        WAITING_HUMAN="waiting_human","Aguardando humano"
        HUMAN="human","Humano"
        CLOSED="closed","Fechada"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="whatsapp_conversations")
    customer=models.ForeignKey("scheduling.Customer",null=True,blank=True,on_delete=models.SET_NULL,related_name="whatsapp_conversations")
    wa_id=models.CharField(max_length=32)
    contact_name=models.CharField(max_length=150,blank=True)
    status=models.CharField(max_length=20,choices=Status.choices,default=Status.BOT,db_index=True)
    bot_state=models.CharField(max_length=60,default="welcome")
    assigned_to=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="whatsapp_conversations")
    context=models.JSONField(default=dict,blank=True)
    last_message_at=models.DateTimeField()
    
    class Meta:
        constraints=[models.UniqueConstraint(fields=["tenant","wa_id"],name="uq_wa_conversation")]
        indexes=[models.Index(fields=["tenant","status","last_message_at"],name="comm_wa_inbox_idx")]


class WhatsAppMessage(models.Model):
    class Direction(models.TextChoices):
        IN="in","Entrada"
        OUT="out","Saída"

    class SenderType(models.TextChoices):
        CUSTOMER="customer","Cliente"
        BOT="bot","Bot"
        USER="user","Usuário"
        SYSTEM="system","Sistema"

    class Status(models.TextChoices):
        RECEIVED="received","Recebida"
        QUEUED="queued","Na fila"
        SENT="sent","Enviada"
        DELIVERED="delivered","Entregue"
        READ="read","Lida"
        FAILED="failed","Falhou"

    conversation=models.ForeignKey(WhatsAppConversation,on_delete=models.CASCADE,related_name="messages")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="whatsapp_messages")
    provider_message_id=models.CharField(max_length=190,null=True,blank=True,unique=True)
    direction=models.CharField(max_length=4,choices=Direction.choices)
    sender_type=models.CharField(max_length=12,choices=SenderType.choices)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="whatsapp_messages")
    message_type=models.CharField(max_length=30,default="text")
    body=models.TextField(blank=True)
    status=models.CharField(max_length=16,choices=Status.choices)
    error_message=models.CharField(max_length=500,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    sent_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        indexes=[models.Index(fields=["conversation","id"],name="comm_wa_message_idx")]


class MarketingCampaignReferrer(models.Model):
    campaign=models.OneToOneField(MarketingCampaign,primary_key=True,on_delete=models.CASCADE,related_name="referrer")
    referrer_user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="referred_marketing_campaigns")
    created_at=models.DateTimeField(auto_now_add=True)
