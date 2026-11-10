from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts","0001_initial"),
    ]
    operations=[
        migrations.CreateModel(
            name="Capability",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("slug",models.CharField(max_length=120,unique=True)),
                ("name",models.CharField(max_length=150)),
            ],
        ),
        migrations.CreateModel(
            name="PlatformRole",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("slug",models.CharField(max_length=60,unique=True)),
                ("name",models.CharField(max_length=100)),
            ],
        ),
        migrations.CreateModel(
            name="RoleCapability",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("capability",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="role_links",to="accounts.capability")),
                ("role",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="capability_links",to="accounts.platformrole")),
            ],
        ),
        migrations.CreateModel(
            name="UserRole",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("role",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="user_links",to="accounts.platformrole")),
                ("user",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="role_links",to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="LoginHistory",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("email",models.EmailField(max_length=254)),
                ("successful",models.BooleanField()),
                ("ip_address",models.GenericIPAddressField(blank=True,null=True)),
                ("user_agent",models.CharField(blank=True,max_length=500)),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("user",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="login_history",to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddField(
            model_name="platformrole",
            name="capabilities",
            field=models.ManyToManyField(blank=True,related_name="roles",through="accounts.RoleCapability",to="accounts.capability"),
        ),
        migrations.AddConstraint(model_name="rolecapability",constraint=models.UniqueConstraint(fields=("role","capability"),name="uq_role_capability")),
        migrations.AddConstraint(model_name="userrole",constraint=models.UniqueConstraint(fields=("user","role"),name="uq_user_platform_role")),
        migrations.AddIndex(model_name="loginhistory",index=models.Index(fields=["user","created_at"],name="accounts_login_user_idx")),
        migrations.AddIndex(model_name="loginhistory",index=models.Index(fields=["email","created_at"],name="accounts_login_email_idx")),
    ]
