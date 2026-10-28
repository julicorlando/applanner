"""Register physiotherapy as a separately manageable Master module.

This migration only adds catalog metadata; it does not alter existing plan
entitlements or disable clinical records for existing customers.
"""
from django.db import migrations


def add_physiotherapy_module(apps, schema_editor):
    Module = apps.get_model("billing", "Module")
    Module.objects.get_or_create(
        slug="physiotherapy",
        defaults={
            "name": "Fisioterapia",
            "description": "Avaliação fisioterapêutica, evolução por sessão e mapa corporal. Requer acesso ao módulo de prontuários clínicos.",
            "active": True,
            "sort_order": 55,
        },
    )


class Migration(migrations.Migration):
    dependencies = [("healthcare", "0002_physiotherapy_record_types"), ("billing", "0001_initial")]
    operations = [migrations.RunPython(add_physiotherapy_module, migrations.RunPython.noop)]
