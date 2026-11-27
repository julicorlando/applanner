from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[("billing","0010_subscription_checkout_url")]
    operations=[
        migrations.AddField(
            model_name="subscription",name="provider_environment",
            field=models.CharField(blank=True,max_length=16),
        ),
    ]
