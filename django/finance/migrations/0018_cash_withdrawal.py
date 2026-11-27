import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0017_cash_delete_and_line_removal"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ClinicCashWithdrawal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("method_name", models.CharField(max_length=60)),
                ("withdrawn_by", models.CharField(max_length=120)),
                ("destination", models.CharField(choices=[("bank", "Depósito no banco"), ("partner", "Retirada do profissional ou sócio"), ("other", "Outro")], max_length=12)),
                ("notes", models.CharField(blank=True, max_length=500)),
                ("occurred_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("request_id", models.UUIDField(unique=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("cancel_reason", models.CharField(blank=True, max_length=300)),
                ("cancelled_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("converted_from", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="converted_to", to="finance.clinicexpense")),
                ("method", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="finance.clinicpaymentmethod")),
                ("recorded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="clinic_withdrawals", to=settings.AUTH_USER_MODEL)),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="clinical_withdrawals", to="finance.cashsession")),
            ],
            options={"indexes": [models.Index(fields=["session", "cancelled_at"], name="finance_withdraw_session_idx")]},
        ),
    ]
