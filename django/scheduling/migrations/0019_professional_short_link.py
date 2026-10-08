import secrets
from django.db import migrations, models


def backfill(apps, schema_editor):
    for label in ('tenants.Tenant', 'scheduling.Professional'):
        Model = apps.get_model(label)
        rows = Model.objects.using(schema_editor.connection.alias)
        for row in rows.filter(models.Q(public_short_code__isnull=True) | models.Q(public_short_code='')).iterator():
            code = secrets.token_hex(6)
            while rows.filter(public_short_code=code).exists():
                code = secrets.token_hex(6)
            rows.filter(pk=row.pk).update(public_short_code=code)


class Migration(migrations.Migration):
    dependencies = [('scheduling', '0018_customer_preferences'), ('tenants', '0012_tenant_simple_mode')]
    operations = [
        migrations.AddField(model_name='professional', name='public_short_code',
            field=models.CharField(max_length=16, unique=True, null=True, blank=True, editable=False)),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
