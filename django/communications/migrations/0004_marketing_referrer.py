from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("communications","0003_marketingdelivery_clicked_at_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations=[
        migrations.CreateModel(
            name="MarketingCampaignReferrer",
            fields=[
                ("campaign",models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,primary_key=True,related_name="referrer",serialize=False,to="communications.marketingcampaign")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("referrer_user",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="referred_marketing_campaigns",to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
