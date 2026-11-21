from django.db import migrations, models
import django.db.models.deletion


def fill_business_date(apps, schema_editor):
    from zoneinfo import ZoneInfo
    from django.conf import settings
    CashSession = apps.get_model("finance", "CashSession")
    for row in CashSession.objects.filter(business_date__isnull=True).select_related("tenant").iterator():
        try:
            zone = ZoneInfo(getattr(row.tenant, "timezone", "") or settings.TIME_ZONE)
        except Exception:  # noqa: BLE001
            zone = ZoneInfo(settings.TIME_ZONE)
        CashSession.objects.filter(pk=row.pk).update(business_date=row.opened_at.astimezone(zone).date())


class Migration(migrations.Migration):
    """Aditiva: caixa por profissional e por dia."""

    dependencies = [("finance", "0015_clinic_cash_sheet"), ("scheduling", "__latest__")]

    operations = [
        migrations.AddField(model_name="cashsession", name="professional", field=models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="cash_sessions", to="scheduling.professional")),
        migrations.AddField(model_name="cashsession", name="business_date", field=models.DateField(blank=True, db_index=True, null=True)),
        migrations.AddIndex(model_name="cashsession", index=models.Index(fields=["tenant", "unit", "business_date"], name="finance_cas_tenant__bd_idx")),
        migrations.RunPython(fill_business_date, migrations.RunPython.noop),
    ]
