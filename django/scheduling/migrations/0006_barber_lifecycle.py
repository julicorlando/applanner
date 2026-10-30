from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[("scheduling","0005_normalize_index_names")]
    operations=[
        migrations.AddField(model_name="appointment",name="checked_in_at",field=models.DateTimeField(blank=True,null=True)),
        migrations.AddField(model_name="appointment",name="service_started_at",field=models.DateTimeField(blank=True,null=True)),
        migrations.AddField(model_name="appointment",name="service_completed_at",field=models.DateTimeField(blank=True,null=True)),
    ]
