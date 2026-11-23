from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("healthcare", "0026_more_document_kinds")]

    operations = [
        migrations.AlterField(
            model_name="patientnoterectification", name="replacement",
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                       related_name="replaces_note", to="healthcare.dentalevolution"),
        ),
    ]
