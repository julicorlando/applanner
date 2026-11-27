import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_professional(apps, schema_editor):
    """Despesas e retiradas lançadas no caixa de um profissional ficam marcadas para ele."""
    Expense = apps.get_model("finance", "ClinicExpense")
    Withdrawal = apps.get_model("finance", "ClinicCashWithdrawal")
    for model in (Expense, Withdrawal):
        for row in model.objects.filter(session__professional__isnull=False, professional__isnull=True).select_related("session"):
            model.objects.filter(pk=row.pk).update(professional_id=row.session.professional_id)


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0018_cash_withdrawal"),
        ("scheduling", "0028_customer_registered_by"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="clinicexpense", name="professional",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="clinic_expenses", to="scheduling.professional")),
        migrations.AddField(
            model_name="cliniccashwithdrawal", name="professional",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="clinic_withdrawals", to="scheduling.professional")),
        migrations.CreateModel(
            name="ClinicCashMerge",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("moved", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("merged_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("source", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="merged_out", to="finance.cashsession")),
                ("target", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="merges_in", to="finance.cashsession")),
            ],
        ),
        migrations.RunPython(backfill_professional, migrations.RunPython.noop),
    ]
