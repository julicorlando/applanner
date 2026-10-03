from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("commercial","0002_support_enabled"),
        ("tenants","0001_initial"),
    ]

    operations=[
        migrations.AddField(model_name="lead",name="source_medium",field=models.CharField(blank=True,max_length=80)),
        migrations.AddField(model_name="lead",name="source_campaign",field=models.CharField(blank=True,max_length=120)),
        migrations.AddField(model_name="lead",name="source_detail",field=models.CharField(blank=True,max_length=190)),
        migrations.AddField(
            model_name="lead",name="converted_tenant",
            field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="origin_leads",to="tenants.tenant"),
        ),
    ]
