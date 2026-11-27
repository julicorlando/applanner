from django.db import migrations,models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[("communications","0004_marketing_referrer"),("tenants","0006_merge_onboarding_demo")]

    operations=[migrations.CreateModel(
        name="ChatbotFlow",
        fields=[
            ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
            ("created_at",models.DateTimeField(auto_now_add=True)),
            ("updated_at",models.DateTimeField(auto_now=True)),
            ("enabled",models.BooleanField(default=False)),
            ("greeting",models.CharField(default="Olá! Como podemos ajudar?",max_length=1000)),
            ("fallback",models.CharField(default="Vou encaminhar sua mensagem para nossa equipe.",max_length=1000)),
            ("handoff",models.CharField(default="Vou chamar um atendente para ajudar você.",max_length=1000)),
            ("rules",models.JSONField(blank=True,default=list)),
            ("tenant",models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,related_name="chatbot_flow",to="tenants.tenant")),
        ],
    )]
