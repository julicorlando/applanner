from django.db import migrations, models


class Migration(migrations.Migration):
    initial=True
    dependencies=[]
    operations=[
        migrations.CreateModel(
            name="Tenant",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("name",models.CharField(max_length=150)),
                ("slug",models.SlugField(max_length=120,unique=True)),
                ("document",models.CharField(blank=True,max_length=32)),
                ("email",models.EmailField(blank=True,max_length=254)),
                ("phone",models.CharField(blank=True,max_length=32)),
                ("status",models.CharField(choices=[("trial","Teste"),("active","Ativo"),("suspended","Suspenso"),("cancelled","Cancelado")],db_index=True,default="trial",max_length=16)),
                ("locale",models.CharField(default="pt-br",max_length=10)),
                ("timezone",models.CharField(default="America/Recife",max_length=64)),
                ("metadata",models.JSONField(blank=True,default=dict)),
            ],
        ),
    ]
