from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("operations","0002_dataimportjob"),
        ("tenants","0005_onboarding_status_history"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations=[
        migrations.CreateModel(
            name="BillingSupportRequest",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("request_type",models.CharField(choices=[("account_deletion","Exclusão de conta"),("invoice","Nota/fatura")],max_length=20)),
                ("status",models.CharField(choices=[("pending","Pendente"),("approved","Aprovado"),("completed","Concluído"),("rejected","Rejeitado"),("cancelled","Cancelado")],db_index=True,default="pending",max_length=16)),
                ("reference_period",models.CharField(blank=True,max_length=20)),
                ("deadline_at",models.DateTimeField(blank=True,null=True)),
                ("reviewed_at",models.DateTimeField(blank=True,null=True)),
                ("completed_at",models.DateTimeField(blank=True,null=True)),
                ("attachment_message",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="+",to="operations.supportmessage")),
                ("reviewed_by",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="billing_support_reviews",to=settings.AUTH_USER_MODEL)),
                ("tenant",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="billing_support_requests",to="tenants.tenant")),
                ("ticket",models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,related_name="billing_request",to="operations.supportticket")),
                ("user",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="billing_support_requests",to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(model_name="billingsupportrequest",index=models.Index(fields=["tenant","request_type","status"],name="ops_billing_req_idx")),
        migrations.CreateModel(
            name="PlatformSetting",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("key",models.CharField(max_length=150)),
                ("value",models.TextField(blank=True)),
                ("is_secret",models.BooleanField(default=False)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("tenant",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.CASCADE,related_name="platform_settings",to="tenants.tenant")),
            ],
        ),
        migrations.AddConstraint(model_name="platformsetting",constraint=models.UniqueConstraint(fields=("tenant","key"),name="uq_platform_setting_tenant_key")),
        migrations.AddIndex(model_name="platformsetting",index=models.Index(fields=["key"],name="ops_setting_key_idx")),
    ]
