from django.db import migrations, models
import django.db.models.deletion


def backfill_financial_units(apps,schema_editor):
    Unit=apps.get_model("tenants","Unit")
    FinancialTransaction=apps.get_model("finance","FinancialTransaction")
    for tenant_id in Unit.objects.values_list("tenant_id",flat=True).distinct():
        primary=Unit.objects.filter(tenant_id=tenant_id,active=True).order_by("-is_primary","id").first()
        if not primary:
            continue
        for transaction in FinancialTransaction.objects.filter(
            tenant_id=tenant_id,unit__isnull=True,appointment__unit__isnull=False
        ).select_related("appointment").iterator():
            FinancialTransaction.objects.filter(pk=transaction.pk).update(unit_id=transaction.appointment.unit_id)
        FinancialTransaction.objects.filter(tenant_id=tenant_id,unit__isnull=True).update(unit_id=primary.pk)


class Migration(migrations.Migration):
    dependencies=[
        ("finance","0006_sale_idempotency"),
        ("scheduling","0016_appointment_unit"),
        ("tenants","0008_tenantonboarding_email_verification_waived_at_and_more"),
    ]

    operations=[
        migrations.AddField(
            model_name="financialtransaction",name="unit",
            field=models.ForeignKey(
                blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,
                related_name="financial_transactions",to="tenants.unit",
            ),
        ),
        migrations.RunPython(backfill_financial_units,migrations.RunPython.noop),
        migrations.AddIndex(
            model_name="financialtransaction",
            index=models.Index(
                fields=["tenant","unit","status","paid_at"],
                name="finance_tx_unit_paid_idx",
            ),
        ),
    ]
