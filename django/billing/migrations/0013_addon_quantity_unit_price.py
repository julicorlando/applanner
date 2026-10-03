from django.db import migrations, models


def backfill(apps,schema_editor):
    Addon=apps.get_model("billing","TenantModuleAddon")
    for row in Addon.objects.all().iterator():
        row.unit_price=row.monthly_price
        row.quantity=1
        row.save(update_fields=["unit_price","quantity"])


class Migration(migrations.Migration):
    dependencies=[("billing","0012_retire_arena_sports_offer")]

    operations=[
        migrations.AddField(
            model_name="tenantmoduleaddon",
            name="unit_price",
            field=models.DecimalField(blank=True,decimal_places=2,max_digits=10,null=True),
        ),
        migrations.AddField(
            model_name="tenantmoduleaddon",
            name="quantity",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.RunPython(backfill,migrations.RunPython.noop),
    ]
