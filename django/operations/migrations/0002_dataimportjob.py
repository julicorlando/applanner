from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("operations","0001_initial"),
        ("tenants","0004_normalize_index_names"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations=[
        migrations.CreateModel(
            name="DataImportJob",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("source",models.CharField(default="appbarber",max_length=40)),
                ("original_name",models.CharField(max_length=255)),
                ("status",models.CharField(
                    choices=[("processing","Processando"),("completed","Concluído"),("failed","Falhou")],
                    db_index=True,default="processing",max_length=16,
                )),
                ("summary",models.JSONField(blank=True,default=dict)),
                ("error_message",models.CharField(blank=True,max_length=500)),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("completed_at",models.DateTimeField(blank=True,null=True)),
                ("tenant",models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="data_import_jobs",
                    to="tenants.tenant",
                )),
                ("user",models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="data_import_jobs",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "indexes":[models.Index(fields=["tenant","-created_at"],name="ops_import_tenant_idx")],
            },
        ),
    ]
