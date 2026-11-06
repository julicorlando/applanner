from django.db import migrations


class Migration(migrations.Migration):
    dependencies=[("billing","0003_commercial_billing")]
    operations=[
        migrations.RenameIndex(
            model_name="payment",
            old_name="billing_pay_purpose_idx",
            new_name="billing_pay_purpose_4a23a3_idx",
        ),
    ]
