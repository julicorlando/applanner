from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("healthcare", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="medicalrecordentry",
            name="record_type",
            field=models.CharField(
                choices=[
                    ("evolution", "Evolução"),
                    ("physio_evaluation", "Avaliação fisioterápica"),
                    ("physio_evolution", "Evolução fisioterápica"),
                    ("anamnesis", "Anamnese"),
                    ("procedure", "Procedimento"),
                    ("observation", "Observação"),
                    ("follow_up", "Acompanhamento"),
                ],
                default="evolution",
                max_length=20,
            ),
        ),
    ]
