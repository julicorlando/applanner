from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("tenants","0004_normalize_index_names"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations=[
        migrations.CreateModel(
            name="TenantOnboarding",
            fields=[
                ("tenant",models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,primary_key=True,related_name="onboarding",serialize=False,to="tenants.tenant")),
                ("company_done",models.BooleanField(default=False)),
                ("branding_done",models.BooleanField(default=False)),
                ("unit_done",models.BooleanField(default=False)),
                ("professional_done",models.BooleanField(default=False)),
                ("service_done",models.BooleanField(default=False)),
                ("schedule_done",models.BooleanField(default=False)),
                ("payment_done",models.BooleanField(default=False)),
                ("public_page_done",models.BooleanField(default=False)),
                ("completed_at",models.DateTimeField(blank=True,null=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="TenantStatusHistory",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("from_status",models.CharField(max_length=40)),
                ("to_status",models.CharField(max_length=40)),
                ("reason",models.CharField(max_length=500)),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("changed_by",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name="tenant_status_changes",to=settings.AUTH_USER_MODEL)),
                ("tenant",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="status_history",to="tenants.tenant")),
            ],
        ),
        migrations.AddIndex(model_name="tenantstatushistory",index=models.Index(fields=["tenant","created_at"],name="tenant_status_hist_idx")),
    ]
