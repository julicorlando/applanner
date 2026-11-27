from django.db import migrations, models


def create_draft(apps, schema_editor):
    from legal import use_policy
    LegalDocument = apps.get_model("legal", "LegalDocument")
    # Draft only: nobody is asked to accept it until the platform team fills the blanks and publishes it.
    LegalDocument.objects.get_or_create(
        type="use_policy", version=use_policy.VERSION,
        defaults={"title": use_policy.TITLE, "content": use_policy.CONTENT, "status": "draft", "requires_acceptance": True},
    )


class Migration(migrations.Migration):
    dependencies = [("legal", "0003_data_subject_request")]

    operations = [
        migrations.AlterField(
            model_name="legaldocument", name="type",
            field=models.CharField(max_length=32, choices=[
                ("terms", "Termos gerais"), ("terms_company", "Termos de uso · Empresas"),
                ("terms_customer", "Termos de uso · Clientes"), ("privacy", "Política de privacidade"),
                ("cancellation_company", "Política de cancelamento · Empresas"),
                ("cancellation_customer", "Política de cancelamento · Clientes"),
                ("use_policy", "Política de Uso e Responsabilidade")]),
        ),
        migrations.AddField(model_name="legalacceptance", name="role",
                            field=models.CharField(blank=True, default="", max_length=30)),
        migrations.AddField(model_name="legalacceptance", name="statements",
                            field=models.JSONField(blank=True, default=list)),
        migrations.RunPython(create_draft, migrations.RunPython.noop),
    ]
