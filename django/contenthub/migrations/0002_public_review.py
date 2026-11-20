from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("contenthub","0001_initial"),
        ("tenants","0005_onboarding_status_history"),
    ]
    operations=[
        migrations.CreateModel(
            name="PublicReview",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("customer_name",models.CharField(max_length=120)),
                ("rating",models.PositiveSmallIntegerField()),
                ("comment",models.CharField(max_length=500)),
                ("active",models.BooleanField(default=True)),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("tenant",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="public_reviews",to="tenants.tenant")),
            ],
        ),
        migrations.AddIndex(model_name="publicreview",index=models.Index(fields=["tenant","active","created_at"],name="content_review_tenant_idx")),
    ]
