from django.db import migrations, models


class Migration(migrations.Migration):
    """Aditiva: data original e chave de importação das fichas clínicas antigas."""

    dependencies = [("healthcare", "0022_budget_revision_patient_notes")]

    operations = [
        migrations.AddField(model_name="patientnote", name="occurred_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="patientnote", name="import_key",
                            field=models.CharField(blank=True, default="", editable=False, max_length=80)),
        migrations.AddConstraint(model_name="patientnote", constraint=models.UniqueConstraint(
            condition=~models.Q(import_key=""), fields=("tenant", "import_key"), name="uq_patient_note_import_key")),
    ]
