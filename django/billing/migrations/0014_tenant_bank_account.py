from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("billing","0013_module_per_unit_billing"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations=[
        migrations.CreateModel(
            name="TenantBankAccount",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("bank_code",models.CharField(blank=True,max_length=12)),
                ("bank_name",models.CharField(max_length=120)),
                ("holder_name",models.CharField(max_length=160)),
                ("details_encrypted",models.TextField()),
                ("account_last4",models.CharField(blank=True,max_length=4)),
                ("pix_key_last4",models.CharField(blank=True,max_length=4)),
                ("is_primary",models.BooleanField(default=False)),
                ("active",models.BooleanField(default=True)),
                ("created_by",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="tenant_bank_accounts_created",to=settings.AUTH_USER_MODEL)),
                ("tenant",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="bank_accounts",to="tenants.tenant")),
            ],
            options={
                "indexes":[models.Index(fields=["tenant","active"],name="billing_bank_tenant_idx")],
                "constraints":[
                    models.UniqueConstraint(
                        condition=models.Q(("active",True),("is_primary",True)),
                        fields=("tenant",),
                        name="uq_primary_bank_account_tenant",
                    ),
                ],
            },
        ),
    ]
