from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)

    class Meta:
        abstract=True


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
    created_at=models.DateTimeField(auto_now_add=True,db_index=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","-created_at"])]
