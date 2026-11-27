from django.db import migrations


def register(apps, schema_editor):
    Module = apps.get_model('billing', 'Module')
    Module.objects.get_or_create(slug='waiting-room-tv', defaults={
        'name': 'Chamar na TV', 'description': 'Chamadas de pacientes, sala e mídias na sala de espera.',
        'active': True, 'sort_order': 65,
    })


class Migration(migrations.Migration):
    dependencies = [('healthcare', '0015_offline_waiting_room'), ('billing', '0024_alter_modulerequest_quantity')]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
