from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial=True
    dependencies=[
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tenants","0001_initial"),
    ]
    operations=[
        migrations.CreateModel(
            name="Customer",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("name",models.CharField(max_length=150)),
                ("phone",models.CharField(blank=True,max_length=32)),
                ("email",models.EmailField(blank=True,max_length=254)),
                ("birth_date",models.DateField(blank=True,null=True)),
                ("consent_marketing",models.BooleanField(default=False)),
                ("active",models.BooleanField(default=True)),
                ("tenant",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="customers",to="tenants.tenant")),
            ],
        ),
        migrations.CreateModel(
            name="Professional",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("name",models.CharField(max_length=150)),
                ("active",models.BooleanField(default=True)),
                ("tenant",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="professionals",to="tenants.tenant")),
                ("user",models.OneToOneField(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="Service",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("name",models.CharField(max_length=150)),
                ("description",models.TextField(blank=True)),
                ("duration_minutes",models.PositiveSmallIntegerField()),
                ("price",models.DecimalField(decimal_places=2,default=0,max_digits=10)),
                ("active",models.BooleanField(default=True)),
                ("tenant",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="services",to="tenants.tenant")),
            ],
        ),
        migrations.CreateModel(
            name="Appointment",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("starts_at",models.DateTimeField(db_index=True)),
                ("ends_at",models.DateTimeField()),
                ("status",models.CharField(choices=[("pending","Pendente"),("confirmed","Confirmado"),("in_progress","Em atendimento"),("completed","Concluído"),("cancelled","Cancelado"),("no_show","Faltou")],db_index=True,default="pending",max_length=20)),
                ("source",models.CharField(choices=[("public","Público"),("internal","Interno"),("whatsapp","WhatsApp"),("api","API")],default="internal",max_length=20)),
                ("notes",models.TextField(blank=True)),
                ("created_by",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,to=settings.AUTH_USER_MODEL)),
                ("customer",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name="appointments",to="scheduling.customer")),
                ("professional",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="appointments",to="scheduling.professional")),
                ("service",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name="appointments",to="scheduling.service")),
                ("tenant",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="appointments",to="tenants.tenant")),
            ],
        ),
        migrations.AddIndex(model_name="customer",index=models.Index(fields=["tenant","name"],name="scheduling__tenant__e3124e_idx")),
        migrations.AddIndex(model_name="customer",index=models.Index(fields=["tenant","phone"],name="scheduling__tenant__2d72c4_idx")),
        migrations.AddIndex(model_name="appointment",index=models.Index(fields=["tenant","starts_at"],name="scheduling__tenant__ef093f_idx")),
        migrations.AddIndex(model_name="appointment",index=models.Index(fields=["tenant","status","starts_at"],name="scheduling__tenant__fe8e3e_idx")),
        migrations.AddConstraint(model_name="appointment",constraint=models.CheckConstraint(condition=models.Q(("ends_at__gt",models.F("starts_at"))),name="appointment_end_after_start")),
    ]
