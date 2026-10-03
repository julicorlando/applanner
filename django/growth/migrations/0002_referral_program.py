from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("growth","0001_initial"),
        ("billing","0013_addon_quantity_unit_price"),
        ("scheduling","0014_appointment_customer_name_snapshot"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations=[
        migrations.CreateModel(
            name="ReferralCampaign",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("name",models.CharField(max_length=160)),
                ("active",models.BooleanField(db_index=True,default=False)),
                ("company_reward_type",models.CharField(choices=[("fixed","Valor fixo"),("percent","Percentual")],default="fixed",max_length=12)),
                ("company_reward_value",models.DecimalField(decimal_places=2,default=0,max_digits=10)),
                ("professional_reward_amount",models.DecimalField(decimal_places=2,default=0,max_digits=10)),
                ("payment_threshold",models.PositiveSmallIntegerField(default=2)),
                ("starts_at",models.DateTimeField(blank=True,null=True)),
                ("ends_at",models.DateTimeField(blank=True,null=True)),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("created_by",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="referral_campaigns_created",to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="PlatformReferral",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("code_snapshot",models.CharField(max_length=32)),
                ("status",models.CharField(choices=[("pending","Aguardando pagamentos"),("qualified","Qualificada"),("awaiting_pix","Aguardando chave Pix"),("ready","Pronta para pagamento"),("paid","Paga"),("cancelled","Cancelada")],db_index=True,default="pending",max_length=16)),
                ("payment_count",models.PositiveSmallIntegerField(default=0)),
                ("company_discount_amount",models.DecimalField(decimal_places=2,default=0,max_digits=10)),
                ("professional_reward_amount",models.DecimalField(decimal_places=2,default=0,max_digits=10)),
                ("pix_key_encrypted",models.TextField(blank=True)),
                ("pix_requested_at",models.DateTimeField(blank=True,null=True)),
                ("qualified_at",models.DateTimeField(blank=True,null=True)),
                ("paid_at",models.DateTimeField(blank=True,null=True)),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("campaign",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name="referrals",to="growth.referralcampaign")),
                ("referred_tenant",models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,related_name="platform_referral",to="tenants.tenant")),
                ("referrer_professional",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="platform_referrals",to="scheduling.professional")),
                ("referrer_tenant",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="referrals_made",to="tenants.tenant")),
                ("referrer_user",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name="platform_referrals",to=settings.AUTH_USER_MODEL)),
            ],
            options={"indexes":[models.Index(fields=["status","created_at"],name="growth_ref_status_idx")]},
        ),
        migrations.CreateModel(
            name="ReferralPaymentCredit",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("payment",models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,related_name="referral_credit",to="billing.payment")),
                ("referral",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="payment_credits",to="growth.platformreferral")),
            ],
        ),
    ]
