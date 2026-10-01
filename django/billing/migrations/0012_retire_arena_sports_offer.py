from django.db import migrations


def retire_offer(apps, schema_editor):
    # Preserve contracts and module entitlements; remove only the sales offer.
    apps.get_model('billing', 'Plan').objects.using(schema_editor.connection.alias).filter(
        name__iexact='Arena Sports'
    ).update(public_visible=False, featured=False)


class Migration(migrations.Migration):
    dependencies = [('billing', '0011_subscription_provider_environment')]
    operations = [migrations.RunPython(retire_offer, migrations.RunPython.noop)]
