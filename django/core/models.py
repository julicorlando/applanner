from django.conf import settings
from django.db import models,transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
import hashlib
import json


class TimeStampedModel(models.Model):
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)

    class Meta:
        abstract=True


class AuditChainState(models.Model):
    chain_key=models.CharField(max_length=80,unique=True)
    last_hash=models.CharField(max_length=64,blank=True)
    last_audit_id=models.BigIntegerField(null=True,blank=True)
    updated_at=models.DateTimeField(auto_now=True)


class AuditLog(models.Model):
    tenant=models.ForeignKey("tenants.Tenant",null=True,blank=True,on_delete=models.SET_NULL)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL)
    action=models.CharField(max_length=120,db_index=True)
    entity_type=models.CharField(max_length=120,blank=True)
    entity_id=models.BigIntegerField(null=True,blank=True)
    ip_address=models.GenericIPAddressField(null=True,blank=True)
    user_agent=models.CharField(max_length=500,blank=True)
    before=models.JSONField(null=True,blank=True)
    after=models.JSONField(null=True,blank=True)
    chain_key=models.CharField(max_length=80,blank=True,db_index=True)
    previous_hash=models.CharField(max_length=64,blank=True)
    entry_hash=models.CharField(max_length=64,blank=True,unique=True)
    created_at=models.DateTimeField(default=timezone.now,db_index=True,editable=False)

    class Meta:
        indexes=[models.Index(fields=["tenant","-created_at"])]

    def _canonical_payload(self):
        return json.dumps({
            "tenant_id":self.tenant_id,
            "user_id":self.user_id,
            "action":self.action,
            "entity_type":self.entity_type,
            "entity_id":self.entity_id,
            "ip_address":str(self.ip_address or ""),
            "user_agent":self.user_agent or "",
            "before":self.before,
            "after":self.after,
            "created_at":self.created_at.isoformat() if self.created_at else "",
        },sort_keys=True,separators=(",",":"),ensure_ascii=False,default=str)

    def save(self,*args,**kwargs):
        if self.pk:
            raise ValidationError("Logs de auditoria são imutáveis.")
        self.chain_key=self.chain_key or (f"tenant:{self.tenant_id}" if self.tenant_id else "platform")
        with transaction.atomic():
            state,_=AuditChainState.objects.select_for_update().get_or_create(chain_key=self.chain_key)
            self.previous_hash=state.last_hash or ""
            material=(self.previous_hash+"|"+self._canonical_payload()).encode("utf-8")
            self.entry_hash=hashlib.sha256(material).hexdigest()
            super().save(*args,**kwargs)
            state.last_hash=self.entry_hash
            state.last_audit_id=self.pk
            state.save(update_fields=["last_hash","last_audit_id","updated_at"])

    def delete(self,*args,**kwargs):
        raise ValidationError("Logs de auditoria são append-only e não podem ser excluídos.")
