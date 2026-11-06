from django.db import migrations


def register_dentistry(apps, schema_editor):
    Module = apps.get_model("billing", "Module")
    db = schema_editor.connection.alias
    for slug, name, description, addon in [
        ("dentistry", "Odontologia", "Prontuário odontológico, odontograma e evolução por atendimento.", False),
        ("dental-professional-extra", "Dentista adicional", "Vaga adicional de profissional odontológico, sujeita à aprovação do Master e cobrança recorrente.", True),
    ]:
        Module.objects.using(db).get_or_create(
            slug=slug,
            defaults={"name": name, "description": description, "active": True,
                      "addon_sellable": addon, "sort_order": 58 if not addon else 59},
        )


class Migration(migrations.Migration):
    dependencies = [("billing", "0021_verified_business_module")]
    operations = [migrations.RunPython(register_dentistry, migrations.RunPython.noop)]
