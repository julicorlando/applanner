from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class SupportTicket(TimeStampedModel):
    class Priority(models.TextChoices):
        LOW="low","Baixa"
        NORMAL="normal","Normal"
        HIGH="high","Alta"
        URGENT="urgent","Urgente"
    class Status(models.TextChoices):
        OPEN="open","Aberto"
        IN_PROGRESS="in_progress","Em andamento"
        WAITING_USER="waiting_user","Aguardando usuário"
        RESOLVED="resolved","Resolvido"
        CLOSED="closed","Fechado"

    protocol=models.CharField(max_length=30,unique=True)
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="support_tickets")
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="support_tickets")
    category=models.CharField(max_length=40)
    subject=models.CharField(max_length=190)
    description=models.TextField()
    priority=models.CharField(max_length=12,choices=Priority.choices,default=Priority.NORMAL)
    status=models.CharField(max_length=20,choices=Status.choices,default=Status.OPEN,db_index=True)
    assigned_to=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="support_assignments")

    class Meta:
        indexes=[models.Index(fields=["tenant","status"],name="ops_ticket_tenant_idx")]


class SupportMessage(models.Model):
    ticket=models.ForeignKey(SupportTicket,on_delete=models.CASCADE,related_name="messages")
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="support_messages")
    message=models.TextField()
    attachment=models.FileField(upload_to="support/",blank=True)
    created_at=models.DateTimeField(auto_now_add=True)


class SupportAccessSession(models.Model):
    ticket=models.ForeignKey(SupportTicket,on_delete=models.CASCADE,related_name="access_sessions")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="support_access_sessions")
    master_user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="support_access_sessions")
    started_at=models.DateTimeField()
    ended_at=models.DateTimeField(null=True,blank=True)
    ip_address=models.GenericIPAddressField(null=True,blank=True)
    actions=models.JSONField(default=list,blank=True)


class Backup(models.Model):
    class Type(models.TextChoices):
        DATABASE="database","Banco"
        FILES="files","Arquivos"
        FULL="full","Completo"
    class Status(models.TextChoices):
        RUNNING="running","Executando"
        COMPLETED="completed","Concluído"
        FAILED="failed","Falhou"
        EXPIRED="expired","Expirado"

    type=models.CharField(max_length=16,choices=Type.choices)
    scope=models.CharField(max_length=24,default="database")
    status=models.CharField(max_length=16,choices=Status.choices)
    destination=models.CharField(max_length=190)
    size_bytes=models.BigIntegerField(null=True,blank=True)
    checksum_sha256=models.CharField(max_length=64,blank=True)
    encrypted=models.BooleanField(default=False)
    encryption_method=models.CharField(max_length=60,blank=True)
    path=models.CharField(max_length=500,blank=True)
    started_at=models.DateTimeField()
    completed_at=models.DateTimeField(null=True,blank=True)
    expires_at=models.DateTimeField(null=True,blank=True)
    error_message=models.CharField(max_length=500,blank=True)


class BackupVerification(models.Model):
    backup=models.ForeignKey(Backup,on_delete=models.CASCADE,related_name="verifications")
    verification_type=models.CharField(max_length=16,default="integrity")
    status=models.CharField(max_length=12)
    checksum_sha256=models.CharField(max_length=64,blank=True)
    details=models.CharField(max_length=500,blank=True)
    restored_database=models.CharField(max_length=190,blank=True)
    verified_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="backup_verifications")
    verified_at=models.DateTimeField()
    completed_at=models.DateTimeField(null=True,blank=True)


class HomologationRun(models.Model):
    class Status(models.TextChoices):
        PASSED="passed","Aprovado"
        WARNING="warning","Aviso"
        BLOCKED="blocked","Bloqueado"

    status=models.CharField(max_length=12,choices=Status.choices)
    score=models.DecimalField(max_digits=5,decimal_places=2)
    results=models.JSONField()
    executed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="homologation_runs")
    created_at=models.DateTimeField(auto_now_add=True)


class PlatformOperationSettings(models.Model):
    id=models.PositiveSmallIntegerField(primary_key=True,default=1,editable=False)
    backup_retention_days=models.PositiveSmallIntegerField(default=30)
    backup_include_uploads=models.BooleanField(default=True)
    backup_encrypt=models.BooleanField(default=True)
    backup_before_update=models.BooleanField(default=True)
    lead_retention_days=models.PositiveSmallIntegerField(default=730)
    critical_alert_email=models.EmailField(blank=True)
    critical_alerts_enabled=models.BooleanField(default=False)
    cron_stale_minutes=models.PositiveSmallIntegerField(default=15)
    disk_min_free_mb=models.PositiveIntegerField(default=1024)
    updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="+")
    updated_at=models.DateTimeField(auto_now=True)


class OperationalIncident(TimeStampedModel):
    class Severity(models.TextChoices):
        INFO="info","Info"
        WARNING="warning","Aviso"
        CRITICAL="critical","Crítico"
    class Status(models.TextChoices):
        OPEN="open","Aberto"
        ACKNOWLEDGED="acknowledged","Reconhecido"
        RESOLVED="resolved","Resolvido"

    fingerprint=models.CharField(max_length=64,unique=True)
    category=models.CharField(max_length=20)
    severity=models.CharField(max_length=12,choices=Severity.choices)
    title=models.CharField(max_length=190)
    details=models.TextField(blank=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.OPEN,db_index=True)
    occurrence_count=models.PositiveIntegerField(default=1)
    first_seen_at=models.DateTimeField()
    last_seen_at=models.DateTimeField()
    acknowledged_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="+")
    acknowledged_at=models.DateTimeField(null=True,blank=True)
    resolved_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="+")
    resolved_at=models.DateTimeField(null=True,blank=True)
    alert_sent_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        indexes=[models.Index(fields=["status","severity","last_seen_at"],name="ops_incident_status_idx")]


class CronHeartbeat(models.Model):
    cron_key=models.CharField(max_length=80)
    started_at=models.DateTimeField()
    finished_at=models.DateTimeField(null=True,blank=True)
    status=models.CharField(max_length=12,default="running")
    duration_ms=models.PositiveIntegerField(null=True,blank=True)
    details=models.CharField(max_length=500,blank=True)
    host_name=models.CharField(max_length=190,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["cron_key","started_at"],name="uq_cron_heartbeat")]
        indexes=[models.Index(fields=["cron_key","status","finished_at"],name="ops_cron_health_idx")]


class CronAlertLog(models.Model):
    alert_key=models.CharField(max_length=190)
    channel=models.CharField(max_length=20)
    status=models.CharField(max_length=12)
    message=models.CharField(max_length=500)
    error_message=models.CharField(max_length=500,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
