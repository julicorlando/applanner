from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("scheduling","0003_agenda_2"),
        ("tenants","0003_branding_multiunit"),
    ]
    operations=[
        migrations.AddField(
            model_name="professional",
            name="unit",
            field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="professionals",to="tenants.unit"),
        ),
    ]
