from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial=True
    dependencies=[("tenants","0001_initial")]
    operations=[
        migrations.CreateModel(
            name="Plan",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("name",models.CharField(max_length=100)),
                ("slug",models.SlugField(max_length=80,unique=True)),
                ("monthly_price",models.DecimalField(decimal_places=2,default=0,max_digits=10)),
                ("active",models.BooleanField(default=True)),
                ("features",models.JSONField(blank=True,default=dict)),
            ],
        ),
        migrations.CreateModel(
            name="Subscription",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("status",models.CharField(choices=[("trial","Teste"),("active","Ativa"),("past_due","Em atraso"),("cancelled","Cancelada")],db_index=True,default="trial",max_length=20)),
                ("started_at",models.DateTimeField()),
                ("next_billing_at",models.DateTimeField(blank=True,db_index=True,null=True)),
                ("cancelled_at",models.DateTimeField(blank=True,null=True)),
                ("plan",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to="billing.plan")),
                ("tenant",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="subscriptions",to="tenants.tenant")),
            ],
        ),
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("provider",models.CharField(blank=True,max_length=60)),
                ("provider_reference",models.CharField(blank=True,db_index=True,max_length=190)),
                ("amount",models.DecimalField(decimal_places=2,max_digits=10)),
                ("status",models.CharField(choices=[("pending","Pendente"),("paid","Pago"),("failed","Falhou"),("refunded","Estornado"),("cancelled","Cancelado")],db_index=True,default="pending",max_length=20)),
                ("due_at",models.DateTimeField(blank=True,null=True)),
                ("paid_at",models.DateTimeField(blank=True,null=True)),
                ("metadata",models.JSONField(blank=True,default=dict)),
                ("subscription",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="payments",to="billing.subscription")),
                ("tenant",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="payments",to="tenants.tenant")),
            ],
        ),
    ]
