from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[("contenthub","0003_platformhomepage")]

    operations=[
        migrations.AddField(
            model_name="platformhomepage",
            name="medical_segment_visible",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="FAQItem",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("question",models.CharField(max_length=220)),
                ("answer",models.TextField()),
                ("sort_order",models.PositiveSmallIntegerField(default=0)),
                ("active",models.BooleanField(default=True)),
            ],
            options={"ordering":["sort_order","id"]},
        ),
    ]
