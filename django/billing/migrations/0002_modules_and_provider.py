from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("billing","0001_initial"),
        ("tenants","0002_public_identity"),
    ]
    operations=[
        migrations.CreateModel(
            name="Module",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("slug",models.SlugField(max_length=80,unique=True)),
                ("name",models.CharField(max_length=120)),
                ("active",models.BooleanField(default=True)),
            ],
        ),
        migrations.AddField(model_name="plan",name="trial_days",field=models.PositiveSmallIntegerField(default=14)),
        migrations.AddField(model_name="subscription",name="trial_started_at",field=models.DateTimeField(blank=True,null=True)),
        migrations.AddField(model_name="subscription",name="trial_ends_at",field=models.DateTimeField(blank=True,null=True)),
        migrations.AddField(model_name="subscription",name="trial_days_snapshot",field=models.PositiveSmallIntegerField(blank=True,null=True)),
        migrations.AddField(model_name="subscription",name="provider_customer_id",field=models.CharField(blank=True,max_length=190)),
        migrations.AddField(model_name="subscription",name="provider_subscription_id",field=models.CharField(blank=True,db_index=True,max_length=190)),
        migrations.AddField(model_name="subscription",name="provider_plan_id",field=models.CharField(blank=True,max_length=190)),
        migrations.AddField(model_name="payment",name="provider_status",field=models.CharField(blank=True,max_length=80)),
        migrations.AddField(model_name="payment",name="provider_payment_id",field=models.CharField(blank=True,max_length=190)),
        migrations.CreateModel(
            name="PlanModule",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("enabled",models.BooleanField(default=True)),
                ("module",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="plan_links",to="billing.module")),
                ("plan",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="module_links",to="billing.plan")),
            ],
        ),
        migrations.CreateModel(
            name="TenantModule",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("enabled",models.BooleanField(default=True)),
                ("module",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="tenant_links",to="billing.module")),
                ("tenant",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="module_links",to="tenants.tenant")),
            ],
        ),
        migrations.AddField(model_name="plan",name="modules",field=models.ManyToManyField(blank=True,related_name="plans",through="billing.PlanModule",to="billing.module")),
        migrations.AddConstraint(model_name="planmodule",constraint=models.UniqueConstraint(fields=("plan","module"),name="uq_plan_module")),
        migrations.AddConstraint(model_name="tenantmodule",constraint=models.UniqueConstraint(fields=("tenant","module"),name="uq_tenant_module")),
        migrations.AddConstraint(model_name="payment",constraint=models.UniqueConstraint(condition=~models.Q(("provider_payment_id","")),fields=("provider","provider_payment_id"),name="uq_payment_provider_id")),
    ]
