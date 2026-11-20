from django.db import migrations,models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("engagement","0002_behavior_intelligence"),
        ("finance","0004_product_event"),
    ]
    operations=[
        migrations.AddField(
            model_name="customerpackage",
            name="membership",
            field=models.ForeignKey(
                blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,
                related_name="purchased_packages",to="engagement.customermembership",
            ),
        ),
        migrations.AddField(
            model_name="customerpackage",
            name="financial_transaction",
            field=models.OneToOneField(
                blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,
                related_name="customer_package",to="finance.financialtransaction",
            ),
        ),
    ]
