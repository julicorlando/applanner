from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial=True
    dependencies=[
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tenants","0001_initial"),
    ]
    operations=[
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("action",models.CharField(db_index=True,max_length=120)),
                ("entity_type",models.CharField(blank=True,max_length=120)),
                ("entity_id",models.BigIntegerField(blank=True,null=True)),
                ("ip_address",models.GenericIPAddressField(blank=True,null=True)),
                ("user_agent",models.CharField(blank=True,max_length=500)),
                ("before",models.JSONField(blank=True,null=True)),
                ("after",models.JSONField(blank=True,null=True)),
                ("created_at",models.DateTimeField(auto_now_add=True,db_index=True)),
                ("tenant",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,to="tenants.tenant")),
                ("user",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(model_name="auditlog",index=models.Index(fields=["tenant","-created_at"],name="core_auditl_tenant__34487e_idx")),
    ]
