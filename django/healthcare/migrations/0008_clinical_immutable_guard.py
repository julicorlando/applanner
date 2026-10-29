from django.db import migrations


def install(apps,schema_editor):
    if schema_editor.connection.vendor!="postgresql":return
    schema_editor.execute("""
    CREATE FUNCTION applanner_preserve_clinical_record() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'Registro clinico preservado; utilize retificacao ou nova versao'
        USING ERRCODE='23514',CONSTRAINT='clinical_record_immutable';
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER clinical_record_immutable BEFORE UPDATE OR DELETE ON healthcare_medicalrecordentry
    FOR EACH ROW EXECUTE FUNCTION applanner_preserve_clinical_record();
    CREATE TRIGGER clinical_attachment_immutable BEFORE UPDATE OR DELETE ON healthcare_clinicalattachment
    FOR EACH ROW EXECUTE FUNCTION applanner_preserve_clinical_record();
    """)


def uninstall(apps,schema_editor):
    if schema_editor.connection.vendor!="postgresql":return
    schema_editor.execute("""
    DROP TRIGGER IF EXISTS clinical_record_immutable ON healthcare_medicalrecordentry;
    DROP TRIGGER IF EXISTS clinical_attachment_immutable ON healthcare_clinicalattachment;
    DROP FUNCTION IF EXISTS applanner_preserve_clinical_record();
    """)


class Migration(migrations.Migration):
    dependencies=[("healthcare","0007_alter_medicalrecordentry_appointment")]
    operations=[migrations.RunPython(install,uninstall)]
