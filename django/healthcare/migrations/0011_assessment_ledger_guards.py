from django.db import migrations


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
    CREATE FUNCTION applanner_guard_assessment() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'DELETE' OR OLD.status = 'finalized' THEN
        RAISE EXCEPTION 'Avaliacao preservada; utilize retificacao' USING ERRCODE='23514';
      END IF;
      IF NEW.tenant_id <> OLD.tenant_id OR NEW.customer_id <> OLD.customer_id
         OR NEW.professional_id <> OLD.professional_id OR NEW.created_by_id <> OLD.created_by_id THEN
        RAISE EXCEPTION 'Vinculo clinico imutavel' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER assessment_ledger_guard BEFORE UPDATE OR DELETE ON healthcare_physiotherapyassessment
      FOR EACH ROW EXECUTE FUNCTION applanner_guard_assessment();
    CREATE TRIGGER assessment_version_immutable BEFORE UPDATE OR DELETE ON healthcare_physiotherapyassessmentversion
      FOR EACH ROW EXECUTE FUNCTION applanner_preserve_clinical_record();
    CREATE FUNCTION applanner_guard_assessment_document() RETURNS trigger AS $$
    DECLARE assessment_status text;
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Documento preservado' USING ERRCODE='23514';
      END IF;
      IF TG_OP = 'UPDATE' AND NEW.assessment_id <> OLD.assessment_id THEN
        RAISE EXCEPTION 'Vinculo de documento imutavel' USING ERRCODE='23514';
      END IF;
      SELECT status INTO assessment_status FROM healthcare_physiotherapyassessment
        WHERE id=NEW.assessment_id FOR UPDATE;
      IF assessment_status = 'finalized' THEN
        RAISE EXCEPTION 'Documento de avaliacao finalizada e imutavel' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER assessment_document_guard BEFORE INSERT OR UPDATE OR DELETE ON healthcare_physiotherapyassessmentdocument
      FOR EACH ROW EXECUTE FUNCTION applanner_guard_assessment_document();
    """)


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
    DROP TRIGGER IF EXISTS assessment_document_guard ON healthcare_physiotherapyassessmentdocument;
    DROP FUNCTION IF EXISTS applanner_guard_assessment_document();
    DROP TRIGGER IF EXISTS assessment_version_immutable ON healthcare_physiotherapyassessmentversion;
    DROP TRIGGER IF EXISTS assessment_ledger_guard ON healthcare_physiotherapyassessment;
    DROP FUNCTION IF EXISTS applanner_guard_assessment();
    """)


class Migration(migrations.Migration):
    dependencies = [
        ("healthcare", "0010_clinicalregistration_professional_name_and_more")
    ]
    operations = [migrations.RunPython(install, uninstall)]
