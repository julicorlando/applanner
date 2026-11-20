from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[("scheduling","0014_appointment_customer_name_snapshot")]

    operations=[
        migrations.AddField(
            model_name="appointment",name="idempotency_key",
            field=models.CharField(blank=True,max_length=100),
        ),
        migrations.AddField(
            model_name="appointment",name="idempotency_fingerprint",
            field=models.CharField(blank=True,max_length=64),
        ),
        migrations.AddConstraint(
            model_name="appointment",
            constraint=models.UniqueConstraint(
                fields=("tenant","idempotency_key"),
                condition=~models.Q(("idempotency_key","")),
                name="uq_appointment_idempotency",
            ),
        ),
    ]
