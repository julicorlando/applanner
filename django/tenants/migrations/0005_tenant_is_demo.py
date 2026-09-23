from django.db import migrations,models


class Migration(migrations.Migration):
    dependencies=[("tenants","0004_normalize_index_names")]
    operations=[
        migrations.AddField(
            model_name="tenant",
            name="is_demo",
            field=models.BooleanField(default=False),
        ),
    ]
