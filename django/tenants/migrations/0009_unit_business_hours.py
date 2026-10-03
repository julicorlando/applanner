from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[("tenants","0008_tenantonboarding_email_verification_waived_at_and_more")]

    operations=[
        migrations.CreateModel(
            name="UnitBusinessHours",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("weekday",models.PositiveSmallIntegerField()),
                ("opens_at",models.TimeField(blank=True,null=True)),
                ("closes_at",models.TimeField(blank=True,null=True)),
                ("closed",models.BooleanField(default=False)),
                ("active",models.BooleanField(default=True)),
                ("tenant",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="unit_business_hours",to="tenants.tenant")),
                ("unit",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="business_hours",to="tenants.unit")),
            ],
            options={"ordering":["weekday"]},
        ),
        migrations.AddConstraint(
            model_name="unitbusinesshours",
            constraint=models.UniqueConstraint(fields=("unit","weekday"),name="uq_unit_business_hours_day"),
        ),
        migrations.AddConstraint(
            model_name="unitbusinesshours",
            constraint=models.CheckConstraint(condition=models.Q(("weekday__gte",1),("weekday__lte",7)),name="unit_business_hours_weekday_iso"),
        ),
        migrations.AddIndex(
            model_name="unitbusinesshours",
            index=models.Index(fields=["tenant","unit","active"],name="unit_hours_tenant_unit_idx"),
        ),
    ]
