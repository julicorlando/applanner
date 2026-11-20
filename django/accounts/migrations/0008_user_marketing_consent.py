from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[("accounts","0007_user_deleted_at")]

    operations=[
        migrations.AddField(
            model_name="user",name="marketing_consent",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",name="marketing_consent_at",
            field=models.DateTimeField(blank=True,null=True),
        ),
    ]
