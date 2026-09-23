from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("engagement","0003_customerpackage_legacy_links"),
        ("communications","0004_marketing_referrer"),
    ]
    operations=[
        migrations.AddField(
            model_name="referralvisit",
            name="campaign",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="referral_visits",
                to="communications.marketingcampaign",
            ),
        ),
    ]
