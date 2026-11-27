from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[("accounts","0005_merge_identity_security"),("tenants","0006_merge_onboarding_demo")]
    operations=[
        migrations.CreateModel(
            name="PersonalAPIToken",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("name",models.CharField(max_length=100)),
                ("prefix",models.CharField(max_length=16)),
                ("secret_hash",models.CharField(max_length=64,unique=True)),
                ("scopes",models.JSONField(default=list)),
                ("session_version",models.PositiveIntegerField()),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("expires_at",models.DateTimeField()),
                ("last_used_at",models.DateTimeField(blank=True,null=True)),
                ("revoked_at",models.DateTimeField(blank=True,null=True)),
                ("tenant",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.CASCADE,to="tenants.tenant")),
                ("user",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="api_tokens",to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering":["-created_at"]},
        ),
    ]
