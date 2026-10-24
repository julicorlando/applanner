from django.db import migrations


class Migration(migrations.Migration):
    dependencies=[("core","0001_initial")]
    operations=[
        migrations.RenameIndex(
            model_name="auditlog",
            old_name="core_auditl_tenant__34487e_idx",
            new_name="core_auditl_tenant__93f9ab_idx",
        ),
    ]
