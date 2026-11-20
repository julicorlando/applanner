import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Aditiva: revisão de orçamento (aponta para o emitido que substitui) e observações do prontuário."""

    dependencies = [
        ("healthcare", "0021_document_verification"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="clinicalissueddocument",
            name="replaces",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="revisions", to="healthcare.clinicalissueddocument"),
        ),
        migrations.CreateModel(
            name="PatientNote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("text_encrypted", models.TextField()),
                ("author_name", models.CharField(max_length=160)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("author", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="patient_notes",
                                               to="scheduling.customer")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.tenant")),
            ],
            options={"ordering": ["-created_at", "-pk"]},
        ),
    ]
