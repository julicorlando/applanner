from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[("accounts","0002_rbac")]
    operations=[
        migrations.AlterModelOptions(
            name="user",
            options={"verbose_name":"user","verbose_name_plural":"users"},
        ),
        migrations.RenameIndex(
            model_name="loginhistory",
            old_name="accounts_login_user_idx",
            new_name="accounts_lo_user_id_a5a726_idx",
        ),
        migrations.RenameIndex(
            model_name="loginhistory",
            old_name="accounts_login_email_idx",
            new_name="accounts_lo_email_b612a3_idx",
        ),
        migrations.RenameIndex(
            model_name="recoverycode",
            old_name="accounts_re_user_id_8af79a_idx",
            new_name="accounts_re_user_id_51e9a4_idx",
        ),
        migrations.RenameIndex(
            model_name="trusteddevice",
            old_name="accounts_tr_user_id_f09367_idx",
            new_name="accounts_tr_user_id_9458da_idx",
        ),
        migrations.AlterField(
            model_name="user",
            name="groups",
            field=models.ManyToManyField(
                blank=True,
                help_text="The groups this user belongs to. A user will get all permissions granted to each of their groups.",
                related_name="user_set",
                related_query_name="user",
                to="auth.group",
                verbose_name="groups",
            ),
        ),
    ]
