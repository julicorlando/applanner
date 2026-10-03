from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("engagement","0006_waitlistentry_appointment"),
        ("tenants","0008_tenantonboarding_email_verification_waived_at_and_more"),
        ("scheduling","0014_appointment_customer_name_snapshot"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations=[
        migrations.CreateModel(
            name="ReferralIncentiveCampaign",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("name",models.CharField(max_length=160)),
                ("active",models.BooleanField(db_index=True,default=True)),
                ("reward_type",models.CharField(choices=[("fixed","Valor fixo"),("percent","Percentual")],default="fixed",max_length=12)),
                ("reward_value",models.DecimalField(decimal_places=2,default=0,max_digits=10)),
                ("qualification_payments",models.PositiveSmallIntegerField(default=2)),
                ("company_referrals_enabled",models.BooleanField(default=True)),
                ("professional_referrals_enabled",models.BooleanField(default=True)),
                ("starts_at",models.DateTimeField(blank=True,null=True)),
                ("ends_at",models.DateTimeField(blank=True,null=True)),
                ("created_by",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="referral_incentive_campaigns_created",to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="ReferralReward",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("referrer_kind",models.CharField(choices=[("company","Empresa"),("professional","Profissional")],max_length=16)),
                ("status",models.CharField(choices=[("pending","Aguardando qualificação"),("eligible","Qualificada"),("applied","Desconto aplicado"),("pix_required","Aguardando chave Pix"),("ready","Pronta para pagamento"),("paid","Paga"),("cancelled","Cancelada")],db_index=True,default="pending",max_length=20)),
                ("qualified_payment_count",models.PositiveSmallIntegerField(default=0)),
                ("reward_amount",models.DecimalField(decimal_places=2,default=0,max_digits=10)),
                ("pix_key_encrypted",models.TextField(blank=True)),
                ("pix_key_last4",models.CharField(blank=True,max_length=4)),
                ("pix_requested_at",models.DateTimeField(blank=True,null=True)),
                ("pix_received_at",models.DateTimeField(blank=True,null=True)),
                ("earned_at",models.DateTimeField(blank=True,null=True)),
                ("applied_at",models.DateTimeField(blank=True,null=True)),
                ("paid_at",models.DateTimeField(blank=True,null=True)),
                ("campaign",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name="rewards",to="engagement.referralincentivecampaign")),
                ("referred_tenant",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="referral_rewards",to="tenants.tenant")),
                ("referrer_user",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name="referral_rewards",to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes":[
                    models.Index(fields=["referrer_user","status"],name="eng_refreward_user_idx"),
                    models.Index(fields=["status","created_at"],name="eng_refreward_status_idx"),
                ],
                "constraints":[
                    models.UniqueConstraint(fields=("campaign","referred_tenant"),name="uq_referral_reward_campaign_tenant"),
                ],
            },
        ),
        migrations.CreateModel(
            name="CustomerContactThrottle",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("last_contact_at",models.DateTimeField()),
                ("reason",models.CharField(blank=True,max_length=40)),
                ("customer",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="contact_throttles",to="scheduling.customer")),
                ("sent_by",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="customer_contact_throttles_sent",to=settings.AUTH_USER_MODEL)),
                ("tenant",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="customer_contact_throttles",to="tenants.tenant")),
            ],
            options={
                "indexes":[models.Index(fields=["tenant","last_contact_at"],name="eng_contact_throttle_idx")],
                "constraints":[models.UniqueConstraint(fields=("tenant","customer"),name="uq_customer_contact_throttle")],
            },
        ),
    ]
