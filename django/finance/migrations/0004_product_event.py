from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("finance","0003_platformfinancecategory_platformbankaccount_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations=[
        migrations.CreateModel(
            name="ProductEvent",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("event_type",models.CharField(db_index=True,max_length=80)),
                ("metadata",models.JSONField(blank=True,default=dict)),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("tenant",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="product_events",to="tenants.tenant")),
                ("user",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="product_events",to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(model_name="productevent",index=models.Index(fields=["event_type","created_at"],name="finance_product_evt_idx")),
        migrations.AddIndex(model_name="productevent",index=models.Index(fields=["tenant","created_at"],name="finance_product_tenant_idx")),
    ]
