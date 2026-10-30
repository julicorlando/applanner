import hashlib
import json

from django.db import migrations, models
from django.utils import timezone


def backfill_audit_chain(apps,schema_editor):
    AuditLog=apps.get_model("core","AuditLog")
    AuditChainState=apps.get_model("core","AuditChainState")
    states={}
    for row in AuditLog.objects.order_by("created_at","pk").iterator():
        chain_key=f"tenant:{row.tenant_id}" if row.tenant_id else "platform"
        previous=states.get(chain_key,"")
        payload=json.dumps({
            "tenant_id":row.tenant_id,
            "user_id":row.user_id,
            "action":row.action,
            "entity_type":row.entity_type,
            "entity_id":row.entity_id,
            "ip_address":str(row.ip_address or ""),
            "user_agent":row.user_agent or "",
            "before":row.before,
            "after":row.after,
            "created_at":row.created_at.isoformat() if row.created_at else "",
        },sort_keys=True,separators=(",",":"),ensure_ascii=False,default=str)
        entry=hashlib.sha256((previous+"|"+payload).encode("utf-8")).hexdigest()
        AuditLog.objects.filter(pk=row.pk).update(
            chain_key=chain_key,previous_hash=previous,entry_hash=entry
        )
        states[chain_key]=entry
    for chain_key,last_hash in states.items():
        last=AuditLog.objects.filter(chain_key=chain_key).order_by("-created_at","-pk").first()
        AuditChainState.objects.update_or_create(
            chain_key=chain_key,
            defaults={"last_hash":last_hash,"last_audit_id":last.pk if last else None},
        )


class Migration(migrations.Migration):
    dependencies=[("core","0002_normalize_index_names")]

    operations=[
        migrations.CreateModel(
            name="AuditChainState",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("chain_key",models.CharField(max_length=80,unique=True)),
                ("last_hash",models.CharField(blank=True,max_length=64)),
                ("last_audit_id",models.BigIntegerField(blank=True,null=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AlterField(
            model_name="auditlog",name="created_at",
            field=models.DateTimeField(db_index=True,default=timezone.now,editable=False),
        ),
        migrations.AddField(
            model_name="auditlog",name="chain_key",
            field=models.CharField(blank=True,db_index=True,max_length=80),
        ),
        migrations.AddField(
            model_name="auditlog",name="previous_hash",
            field=models.CharField(blank=True,max_length=64),
        ),
        migrations.AddField(
            model_name="auditlog",name="entry_hash",
            field=models.CharField(blank=True,max_length=64),
        ),
        migrations.RunPython(backfill_audit_chain,migrations.RunPython.noop),
        migrations.AlterField(
            model_name="auditlog",name="entry_hash",
            field=models.CharField(blank=True,max_length=64,unique=True),
        ),
    ]
