from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("accounts","0003_normalize_auth_state"),
        ("billing","0006_tenant_payment_reconciliation"),
    ]
    operations=[
        migrations.AddField(
            model_name="plan",
            name="public_visible",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="plan",
            name="is_custom",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="plan",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_plans",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
