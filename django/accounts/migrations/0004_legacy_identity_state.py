from django.conf import settings
from django.db import migrations,models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[("accounts","0003_normalize_auth_state")]
    operations=[
        migrations.AddField(
            model_name="user",
            name="email_verified_at",
            field=models.DateTimeField(blank=True,null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="password_changed_at",
            field=models.DateTimeField(blank=True,null=True),
        ),
        migrations.CreateModel(
            name="EmailVerificationToken",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("token_hash",models.CharField(max_length=64,unique=True)),
                ("expires_at",models.DateTimeField(db_index=True)),
                ("used_at",models.DateTimeField(blank=True,null=True)),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("user",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="email_verification_tokens",to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="PasswordResetToken",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("token_hash",models.CharField(max_length=64,unique=True)),
                ("expires_at",models.DateTimeField(db_index=True)),
                ("used_at",models.DateTimeField(blank=True,null=True)),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("user",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="password_reset_tokens",to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(model_name="emailverificationtoken",index=models.Index(fields=["user","expires_at"],name="accounts_em_user_id_b5ffac_idx")),
        migrations.AddIndex(model_name="passwordresettoken",index=models.Index(fields=["user","expires_at"],name="accounts_pa_user_id_e5b29b_idx")),
    ]
