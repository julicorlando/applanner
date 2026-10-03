from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[("finance","0005_product_reservation")]

    operations=[
        migrations.AddField(
            model_name="sale",name="idempotency_key",
            field=models.CharField(blank=True,max_length=100),
        ),
        migrations.AddConstraint(
            model_name="sale",
            constraint=models.UniqueConstraint(
                fields=("tenant","idempotency_key"),
                condition=~models.Q(("idempotency_key","")),
                name="uq_sale_idempotency",
            ),
        ),
    ]
