from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[("operations","0008_backfill_account_deletion_requests")]

    operations=[
        migrations.AddField(
            model_name="platformoperationsettings",name="maintenance_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="platformoperationsettings",name="maintenance_message",
            field=models.CharField(
                blank=True,default="Estamos realizando uma manutenção programada. Tente novamente em alguns minutos.",
                max_length=300,
            ),
        ),
        migrations.AddField(
            model_name="platformoperationsettings",name="status_page_enabled",
            field=models.BooleanField(default=True),
        ),
    ]
