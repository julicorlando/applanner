from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("finance","0004_product_event"),
        ("scheduling","0014_appointment_customer_name_snapshot"),
        ("tenants","0001_initial"),
    ]

    operations=[
        migrations.CreateModel(
            name="ProductReservation",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("quantity",models.DecimalField(decimal_places=3,default=1,max_digits=12)),
                ("unit_price_snapshot",models.DecimalField(decimal_places=2,max_digits=10)),
                ("appointment",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="product_reservations",to="scheduling.appointment")),
                ("product",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name="reservations",to="finance.product")),
                ("tenant",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="product_reservations",to="tenants.tenant")),
            ],
            options={
                "indexes":[
                    models.Index(fields=["tenant","product"],name="finance_pro_tenant__056c87_idx"),
                    models.Index(fields=["appointment"],name="finance_pro_appointm_43ca6e_idx"),
                ],
                "constraints":[
                    models.UniqueConstraint(fields=("appointment","product"),name="uq_appointment_product_reservation"),
                    models.CheckConstraint(condition=models.Q(("quantity__gt",0)),name="product_reservation_quantity_gt_0"),
                ],
            },
        ),
    ]
