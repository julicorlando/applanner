from django.db import migrations


class Migration(migrations.Migration):
    dependencies=[("tenants","0003_branding_multiunit")]
    operations=[
        migrations.RenameIndex(model_name="unit",old_name="tenant_unit_active_idx",new_name="tenants_uni_tenant__5de758_idx"),
        migrations.RenameIndex(model_name="unit",old_name="tenant_unit_geo_idx",new_name="tenants_uni_active_9ea6e6_idx"),
    ]
