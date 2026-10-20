from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("scheduling", "0023_tenantschedulesettings_card_booking_payments_enabled"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="CustomerImportBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("source_name", models.CharField(max_length=160)),
                ("file_hash", models.CharField(max_length=64)),
                ("payload_encrypted", models.TextField(blank=True)),
                ("mapping", models.JSONField(default=dict)),
                ("report", models.JSONField(default=dict)),
                ("state", models.CharField(choices=[("preview", "Prévia"), ("applied", "Importada")], default="preview", max_length=16)),
                ("expires_at", models.DateTimeField()),
                ("applied_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="customer_imports", to="tenants.tenant")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("tenant", "file_hash"), name="uq_customer_import_file")]},
        ),
    ]
