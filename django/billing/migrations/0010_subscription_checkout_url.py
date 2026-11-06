from django.db import migrations,models


class Migration(migrations.Migration):
    dependencies=[("billing","0009_connection_auth_type")]
    operations=[migrations.AddField(model_name="subscription",name="provider_checkout_url",field=models.URLField(blank=True,max_length=1000))]
