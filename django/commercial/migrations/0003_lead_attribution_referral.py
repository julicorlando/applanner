from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("commercial","0002_support_enabled"),
        ("tenants","0008_tenantonboarding_email_verification_waived_at_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations=[
        migrations.AddField(
            model_name="lead",name="source_medium",
            field=models.CharField(blank=True,max_length=80),
        ),
        migrations.AddField(
            model_name="lead",name="source_campaign",
            field=models.CharField(blank=True,max_length=120),
        ),
        migrations.AddField(
            model_name="lead",name="referrer_user",
            field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="referred_commercial_leads",to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="lead",name="converted_tenant",
            field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="originating_commercial_leads",to="tenants.tenant"),
        ),
    ]
