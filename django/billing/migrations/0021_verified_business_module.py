from django.db import migrations


def create_module(apps, schema_editor):
    apps.get_model('billing', 'Module').objects.using(schema_editor.connection.alias).get_or_create(
        slug='verified-business', defaults={
            'name':'Empresa verificada',
            'description':'Selo de cadastro completo após sete dias, exibido na página pública e no Explorar. Valor definido pelo Master.',
            'active':True, 'addon_sellable':True, 'sort_order':85,
        })


class Migration(migrations.Migration):
    dependencies = [('billing', '0020_fiscaldocumentrequest_notice_queued_at')]
    operations = [migrations.RunPython(create_module, migrations.RunPython.noop)]
