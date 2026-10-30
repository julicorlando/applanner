from django.db import migrations, models


def preserve_existing_names(apps, schema_editor):
    Appointment = apps.get_model("scheduling", "Appointment")
    Customer = apps.get_model("scheduling", "Customer")
    alias = schema_editor.connection.alias
    names = Customer.objects.using(alias).filter(pk=models.OuterRef("customer_id")).values("name")[:1]
    Appointment.objects.using(alias).filter(customer_name_snapshot="").update(customer_name_snapshot=models.Subquery(names))


class Migration(migrations.Migration):
    dependencies = [("scheduling", "0013_professional_services_restricted")]
    operations = [
        migrations.AddField(model_name="appointment", name="customer_name_snapshot",
            field=models.CharField(max_length=160, blank=True, editable=False)),
        migrations.RunPython(preserve_existing_names, migrations.RunPython.noop),
    ]
