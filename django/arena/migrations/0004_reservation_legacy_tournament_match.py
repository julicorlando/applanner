from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[
        ("arena","0003_v2_support"),
    ]
    operations=[
        migrations.AddField(
            model_name="reservation",
            name="legacy_tournament_match_id",
            field=models.BigIntegerField(blank=True,db_index=True,null=True),
        ),
    ]
