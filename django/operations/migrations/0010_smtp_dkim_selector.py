from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[("operations","0009_maintenance_status_settings")]

    operations=[
        migrations.AddField(
            model_name="platformsmtpsettings",name="dkim_selector",
            field=models.CharField(blank=True,default="default",max_length=80),
        ),
    ]
