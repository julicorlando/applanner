from django.db import migrations, models
import django.db.models.deletion


def backfill_waitlist_units(apps,schema_editor):
    Unit=apps.get_model("tenants","Unit")
    WaitlistEntry=apps.get_model("engagement","WaitlistEntry")
    for tenant_id in Unit.objects.values_list("tenant_id",flat=True).distinct():
        primary=Unit.objects.filter(tenant_id=tenant_id,active=True).order_by("-is_primary","id").first()
        if primary:
            WaitlistEntry.objects.filter(tenant_id=tenant_id,unit__isnull=True).update(unit_id=primary.pk)


class Migration(migrations.Migration):
    dependencies=[
        ("engagement","0007_referral_incentives_and_contact_throttle"),
        ("tenants","0008_tenantonboarding_email_verification_waived_at_and_more"),
    ]

    operations=[
        migrations.AddField(
            model_name="waitlistentry",name="unit",
            field=models.ForeignKey(
                blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,
                related_name="waitlist_entries",to="tenants.unit",
            ),
        ),
        migrations.RunPython(backfill_waitlist_units,migrations.RunPython.noop),
    ]
