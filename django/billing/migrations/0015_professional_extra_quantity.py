from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[("billing","0014_tenant_bank_account")]

    operations=[
        migrations.AddField(
            model_name="tenantmoduleaddon",name="quantity",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="tenantmoduleaddon",name="pricing_components",
            field=models.JSONField(blank=True,default=list),
        ),
    ]
