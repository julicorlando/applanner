from django.db import migrations, models


def mark_multiunit(apps,schema_editor):
    Module=apps.get_model("billing","Module")
    Module.objects.filter(slug="multiunit").update(per_unit_billing=True)


class Migration(migrations.Migration):
    dependencies=[("billing","0012_retire_arena_sports_offer")]

    operations=[
        migrations.AddField(
            model_name="module",
            name="per_unit_billing",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(mark_multiunit,migrations.RunPython.noop),
    ]
