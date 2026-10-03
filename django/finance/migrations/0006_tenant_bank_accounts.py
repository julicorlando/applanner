from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("finance","0005_product_reservation"),
        ("tenants","0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations=[
        migrations.CreateModel(
            name="TenantBankAccount",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("bank_name",models.CharField(max_length=120)),
                ("bank_code",models.CharField(blank=True,max_length=10)),
                ("account_type",models.CharField(choices=[("checking","Corrente"),("savings","Poupança"),("payment","Pagamento"),("business","Empresarial")],default="checking",max_length=16)),
                ("agency_encrypted",models.TextField(blank=True)),
                ("account_encrypted",models.TextField(blank=True)),
                ("holder_name",models.CharField(max_length=150)),
                ("pix_key_type",models.CharField(blank=True,max_length=16)),
                ("pix_key_encrypted",models.TextField(blank=True)),
                ("is_primary",models.BooleanField(default=False)),
                ("active",models.BooleanField(default=True)),
                ("created_by",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="tenant_bank_accounts_created",to=settings.AUTH_USER_MODEL)),
                ("tenant",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="bank_accounts",to="tenants.tenant")),
            ],
            options={
                "indexes":[models.Index(fields=["tenant","active","is_primary"],name="tenant_bank_active_idx")],
                "constraints":[models.UniqueConstraint(condition=models.Q(("active",True),("is_primary",True)),fields=("tenant",),name="uq_tenant_primary_bank")],
            },
        ),
    ]
