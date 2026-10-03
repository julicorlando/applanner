from django.db import migrations, models
import django.db.models.deletion


def backfill_units(apps,schema_editor):
    Unit=apps.get_model("tenants","Unit")
    Professional=apps.get_model("scheduling","Professional")
    Appointment=apps.get_model("scheduling","Appointment")
    for tenant_id in Unit.objects.values_list("tenant_id",flat=True).distinct():
        primary=Unit.objects.filter(tenant_id=tenant_id,active=True).order_by("-is_primary","id").first()
        if not primary:
            continue
        Professional.objects.filter(tenant_id=tenant_id,unit__isnull=True).update(unit_id=primary.pk)
        Appointment.objects.filter(
            tenant_id=tenant_id,unit__isnull=True,professional__unit__isnull=False
        ).update(unit_id=models.F("professional__unit"))
        Appointment.objects.filter(tenant_id=tenant_id,unit__isnull=True).update(unit_id=primary.pk)


class Migration(migrations.Migration):
    dependencies=[
        ("scheduling","0015_appointment_idempotency"),
        ("tenants","0008_tenantonboarding_email_verification_waived_at_and_more"),
    ]

    operations=[
        migrations.AddField(
            model_name="appointment",name="unit",
            field=models.ForeignKey(
                blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,
                related_name="appointments",to="tenants.unit",
            ),
        ),
        migrations.RunPython(backfill_units,migrations.RunPython.noop),
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(fields=["tenant","unit","starts_at"],name="sched_appt_unit_start_idx"),
        ),
    ]
