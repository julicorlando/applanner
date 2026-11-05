from django.db import migrations


def install(apps,schema_editor):
    if schema_editor.connection.vendor!='postgresql':return
    schema_editor.execute('''
    CREATE OR REPLACE FUNCTION applanner_clinical_document_guard() RETURNS trigger AS $$
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Documento clinico preservado'; END IF;
      IF TG_OP='UPDATE' THEN
        IF OLD.status='finalized' THEN RAISE EXCEPTION 'Documento emitido imutavel'; END IF;
        IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
          OR NEW.professional_id IS DISTINCT FROM OLD.professional_id OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
          THEN RAISE EXCEPTION 'Vinculo do documento preservado'; END IF;
      END IF;
      IF NEW.tenant_id IS DISTINCT FROM (SELECT tenant_id FROM scheduling_customer WHERE id=NEW.customer_id)
        OR NEW.tenant_id IS DISTINCT FROM (SELECT tenant_id FROM scheduling_professional WHERE id=NEW.professional_id)
        THEN RAISE EXCEPTION 'Documento de outra clinica'; END IF;
      IF NEW.status='finalized' AND (NEW.entry_id IS NULL OR octet_length(NEW.pdf_encrypted)=0 OR NEW.sha256='')
        THEN RAISE EXCEPTION 'Emissao incompleta'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER clinical_document_immutable BEFORE INSERT OR UPDATE OR DELETE ON healthcare_clinicalissueddocument
    FOR EACH ROW EXECUTE FUNCTION applanner_clinical_document_guard();
    ''')


def uninstall(apps,schema_editor):
    if schema_editor.connection.vendor!='postgresql':return
    schema_editor.execute('DROP TRIGGER IF EXISTS clinical_document_immutable ON healthcare_clinicalissueddocument; DROP FUNCTION IF EXISTS applanner_clinical_document_guard();')


class Migration(migrations.Migration):
    dependencies=[('healthcare','0018_clinicaldocumenttemplate_clinicaldriveconfiguration_and_more')]
    operations=[migrations.RunPython(install,uninstall)]
