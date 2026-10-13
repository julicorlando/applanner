from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[("scheduling","0006_barber_lifecycle")]
    operations=[
        migrations.AlterField(
            model_name="appointment",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending","Pendente"),("confirmed","Confirmado"),("waiting","Aguardando"),
                    ("in_progress","Em atendimento"),("completed","Concluído"),
                    ("cancelled","Cancelado"),("no_show","Faltou"),
                ],
                db_index=True,default="pending",max_length=20,
            ),
        ),
    ]
