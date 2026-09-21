import accounts.models
import django.contrib.auth.models
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial=True
    dependencies=[
        ("auth","0012_alter_user_first_name_max_length"),
        ("tenants","0001_initial"),
    ]
    operations=[
        migrations.CreateModel(
            name="User",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("password",models.CharField(max_length=128,verbose_name="password")),
                ("last_login",models.DateTimeField(blank=True,null=True,verbose_name="last login")),
                ("is_superuser",models.BooleanField(default=False,help_text="Designates that this user has all permissions without explicitly assigning them.",verbose_name="superuser status")),
                ("first_name",models.CharField(blank=True,max_length=150,verbose_name="first name")),
                ("last_name",models.CharField(blank=True,max_length=150,verbose_name="last name")),
                ("is_staff",models.BooleanField(default=False,help_text="Designates whether the user can log into this admin site.",verbose_name="staff status")),
                ("is_active",models.BooleanField(default=True,help_text="Designates whether this user should be treated as active. Unselect this instead of deleting accounts.",verbose_name="active")),
                ("date_joined",models.DateTimeField(default=django.utils.timezone.now,verbose_name="date joined")),
                ("email",models.EmailField(max_length=254,unique=True)),
                ("role",models.CharField(db_index=True,default="user",max_length=60)),
                ("must_change_password",models.BooleanField(default=False)),
                ("locale",models.CharField(default="pt-br",max_length=10)),
                ("session_version",models.PositiveIntegerField(default=1)),
                ("two_factor_secret_encrypted",models.TextField(blank=True)),
                ("two_factor_enabled_at",models.DateTimeField(blank=True,null=True)),
                ("two_factor_last_step",models.BigIntegerField(default=0)),
                ("groups",models.ManyToManyField(blank=True,help_text="The groups this user belongs to.",related_name="user_set",related_query_name="user",to="auth.group",verbose_name="groups")),
                ("tenant",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.CASCADE,related_name="users",to="tenants.tenant")),
                ("user_permissions",models.ManyToManyField(blank=True,help_text="Specific permissions for this user.",related_name="user_set",related_query_name="user",to="auth.permission",verbose_name="user permissions")),
            ],
            options={"abstract":False},
            managers=[("objects",accounts.models.UserManager())],
        ),
        migrations.CreateModel(
            name="RecoveryCode",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("code_hash",models.CharField(max_length=64)),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("used_at",models.DateTimeField(blank=True,null=True)),
                ("user",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="recovery_codes",to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="TrustedDevice",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("selector",models.CharField(max_length=64,unique=True)),
                ("verifier_hash",models.CharField(max_length=64)),
                ("label",models.CharField(blank=True,max_length=180)),
                ("user_agent",models.CharField(blank=True,max_length=500)),
                ("ip_address",models.GenericIPAddressField(blank=True,null=True)),
                ("session_version",models.PositiveIntegerField()),
                ("expires_at",models.DateTimeField(db_index=True)),
                ("last_used_at",models.DateTimeField(blank=True,null=True)),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("user",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="trusted_devices",to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(model_name="recoverycode",index=models.Index(fields=["user","used_at"],name="accounts_re_user_id_8af79a_idx")),
        migrations.AddIndex(model_name="trusteddevice",index=models.Index(fields=["user","expires_at"],name="accounts_tr_user_id_f09367_idx")),
    ]
