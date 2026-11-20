import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Aditiva: linhas do caixa diário e autorizações de correção após o fechamento."""

    dependencies = [
        ("finance", "0014_alter_clinicexpense_review_status"),
        ("scheduling", "0028_customer_registered_by"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ClinicCashCorrection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.CharField(max_length=500)),
                ("status", models.CharField(choices=[("requested", "Aguardando gestor"), ("approved", "Liberada para correção"), ("rejected", "Recusada"), ("done", "Concluída")], default="requested", max_length=12)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_note", models.CharField(blank=True, max_length=500)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("decided_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="clinical_corrections", to="finance.cashsession")),
            ],
            options={"ordering": ["-created_at", "-pk"]},
        ),
        migrations.CreateModel(
            name="ClinicCashEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("number", models.PositiveIntegerField()),
                ("professional_name", models.CharField(max_length=120)),
                ("dentist_amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("clinic_amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("other_amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("total", models.DecimalField(decimal_places=2, max_digits=12)),
                ("method_name", models.CharField(blank=True, max_length=60)),
                ("status", models.CharField(choices=[("paid", "Recebido"), ("open", "Em aberto"), ("cancelled", "Cancelado")], default="paid", max_length=12)),
                ("notes", models.CharField(blank=True, max_length=300)),
                ("request_id", models.UUIDField(unique=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="clinic_cash_entries", to=settings.AUTH_USER_MODEL)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cash_entries", to="scheduling.customer")),
                ("method", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="finance.clinicpaymentmethod")),
                ("professional", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="cash_entries", to="scheduling.professional")),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="clinical_entries", to="finance.cashsession")),
                ("transaction", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="clinic_cash_entry", to="finance.financialtransaction")),
            ],
            options={"ordering": ["number"]},
        ),
        migrations.AddConstraint(
            model_name="cliniccashentry",
            constraint=models.UniqueConstraint(fields=("session", "number"), name="uq_clinic_cash_entry_number"),
        ),
    ]
