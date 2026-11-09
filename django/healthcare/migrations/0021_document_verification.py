import django.db.models.deletion
from django.db import migrations, models

KINDS = [("prescription", "Receituário"), ("certificate", "Atestado"), ("declaration", "Declaração"), ("budget", "Orçamento")]


class Migration(migrations.Migration):
    """Aditiva: tipo Orçamento, código público de validação (nulo nos documentos antigos) e registro de validações."""

    dependencies = [("healthcare", "0020_clinical_implementation_period")]

    operations = [
        migrations.AlterField(
            model_name="clinicaldocumenttemplate",
            name="kind",
            field=models.CharField(choices=KINDS, max_length=20),
        ),
        migrations.AlterField(
            model_name="clinicalissueddocument",
            name="kind",
            field=models.CharField(choices=KINDS, max_length=20),
        ),
        migrations.AddField(
            model_name="clinicalissueddocument",
            name="verification_code",
            field=models.CharField(blank=True, editable=False, max_length=40, null=True, unique=True),
        ),
        migrations.CreateModel(
            name="ClinicalDocumentValidation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("validator_name", models.CharField(max_length=120)),
                ("validator_role", models.CharField(blank=True, max_length=120)),
                ("ip_hash", models.CharField(blank=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("document", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="validations", to="healthcare.clinicalissueddocument")),
            ],
            options={"ordering": ["-created_at", "-pk"]},
        ),
    ]
