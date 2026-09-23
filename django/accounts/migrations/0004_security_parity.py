from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("accounts","0003_normalize_auth_state"),
        ("tenants","0005_onboarding_status_history"),
    ]
    operations=[
        migrations.AddField(
            model_name="trusteddevice",name="revoked_at",
            field=models.DateTimeField(blank=True,null=True),
        ),
        migrations.CreateModel(
            name="LoginAudit",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("email_attempted",models.EmailField(max_length=254)),
                ("event_type",models.CharField(max_length=40)),
                ("result",models.CharField(max_length=20)),
                ("ip_address",models.GenericIPAddressField(blank=True,null=True)),
                ("user_agent",models.CharField(blank=True,max_length=500)),
                ("device_info",models.CharField(blank=True,max_length=255)),
                ("failure_reason_code",models.CharField(blank=True,max_length=60)),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("tenant",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="login_audit",to="tenants.tenant")),
                ("user",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="login_audit",to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(model_name="loginaudit",index=models.Index(fields=["created_at","result"],name="accounts_login_audit_idx")),
        migrations.AddIndex(model_name="loginaudit",index=models.Index(fields=["email_attempted","created_at"],name="accounts_login_email_idx")),
        migrations.CreateModel(
            name="SecurityEvent",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("event_type",models.CharField(db_index=True,max_length=80)),
                ("severity",models.CharField(choices=[("low","Baixa"),("medium","Média"),("high","Alta"),("critical","Crítica")],max_length=12)),
                ("ip_address",models.GenericIPAddressField(blank=True,null=True)),
                ("user_agent",models.CharField(blank=True,max_length=500)),
                ("metadata",models.JSONField(blank=True,default=dict)),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("tenant",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="security_events",to="tenants.tenant")),
                ("user",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="security_events",to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(model_name="securityevent",index=models.Index(fields=["tenant","created_at"],name="accounts_security_tenant_idx")),
        migrations.CreateModel(
            name="UserBlock",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("reason_code",models.CharField(max_length=40)),
                ("reason_text",models.CharField(blank=True,max_length=500)),
                ("blocked_at",models.DateTimeField()),
                ("expires_at",models.DateTimeField(blank=True,null=True)),
                ("unblocked_at",models.DateTimeField(blank=True,null=True)),
                ("blocked_by",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="user_blocks_created",to=settings.AUTH_USER_MODEL)),
                ("tenant",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="user_blocks",to="tenants.tenant")),
                ("unblocked_by",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="user_blocks_removed",to=settings.AUTH_USER_MODEL)),
                ("user",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="blocks",to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(model_name="userblock",index=models.Index(fields=["user","unblocked_at"],name="accounts_user_block_idx")),
    ]
