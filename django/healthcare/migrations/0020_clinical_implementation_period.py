import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Aditiva: não altera registros existentes (colunas novas nulas)."""

    dependencies = [
        ("healthcare", "0019_clinical_document_immutable_guard"),
        ("tenants", "0013_businessgroup_groupcompany_grouproyalty_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ClinicalImplementationPeriod",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("starts_on", models.DateField()),
                ("ends_on", models.DateField()),
                ("opened_at", models.DateTimeField(auto_now_add=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("closed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("opened_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="clinical_implementation_periods", to="tenants.tenant")),
            ],
            options={
                "indexes": [models.Index(fields=["tenant", "closed_at"], name="health_impl_tenant_idx")],
            },
        ),
        migrations.AddField(
            model_name="medicalrecordentry",
            name="clinical_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="medicalrecordentry",
            name="transcribed_in_period",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="entries", to="healthcare.clinicalimplementationperiod"),
        ),
    ]
