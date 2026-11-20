from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[
        ("billing","0008_legacy_subscription_parity"),
    ]
    operations=[
        migrations.AddField(
            model_name="tenantpaymentconnection",
            name="auth_type",
            field=models.CharField(
                choices=[
                    ("oauth","OAuth"),
                    ("api_credentials","Credenciais de API"),
                    ("manual","Manual"),
                ],
                default="api_credentials",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="tenantpaymentconnection",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending","Pendente"),
                    ("connected","Conectado"),
                    ("error","Erro"),
                    ("disabled","Desabilitado"),
                ],
                db_index=True,
                default="pending",
                max_length=16,
            ),
        ),
    ]
