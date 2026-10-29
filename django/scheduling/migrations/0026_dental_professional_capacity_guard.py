"""Enforce dental seats below the ORM, serialized per clinic on PostgreSQL.

Existing active profiles remain editable even if a legacy clinic exceeds its
contract. Adding/reactivating/transferring profiles must respect paid capacity.
"""
from django.db import migrations

SQL = """
CREATE FUNCTION applanner_guard_dental_capacity() RETURNS trigger AS $$
DECLARE dental boolean; category_name text; extra_seats bigint; used_seats bigint;
BEGIN
    IF NOT NEW.active THEN RETURN NEW; END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.active AND OLD.tenant_id = NEW.tenant_id THEN RETURN NEW; END IF;
    END IF;
    SELECT lower(trim(category)) INTO category_name
      FROM tenants_tenant WHERE id = NEW.tenant_id;
    dental := category_name IN ('odontologia','odontologica','odontológico','odontologico');
    IF NOT coalesce(dental,false) THEN
        SELECT coalesce(
            (SELECT tm.enabled FROM billing_tenantmodule tm
             JOIN billing_module m ON m.id=tm.module_id
             WHERE tm.tenant_id=NEW.tenant_id AND m.slug='dentistry' AND m.active LIMIT 1),
            (SELECT pm.enabled FROM billing_planmodule pm
             JOIN billing_module m ON m.id=pm.module_id
             WHERE pm.plan_id=(SELECT plan_id FROM billing_subscription
                 WHERE tenant_id=NEW.tenant_id AND status IN ('trial','active')
                 AND (status<>'trial' OR trial_ends_at IS NULL OR trial_ends_at>=CURRENT_TIMESTAMP)
                 ORDER BY started_at DESC LIMIT 1)
             AND m.slug='dentistry' AND m.active LIMIT 1),false) INTO dental;
    END IF;
    IF NOT dental THEN RETURN NEW; END IF;
    -- Only dental writes acquire the capacity lock. Other segments retain their
    -- existing transaction behavior and must not inherit this extra row lock.
    PERFORM 1 FROM tenants_tenant WHERE id=NEW.tenant_id FOR UPDATE;
    SELECT coalesce(sum(a.quantity),0) INTO extra_seats
      FROM billing_tenantmoduleaddon a JOIN billing_module m ON m.id=a.module_id
      WHERE a.tenant_id=NEW.tenant_id AND m.slug='dental-professional-extra' AND a.status='active';
    SELECT count(*) INTO used_seats FROM scheduling_professional
      WHERE tenant_id=NEW.tenant_id AND active AND id<>NEW.id;
    IF used_seats >= 1+extra_seats THEN
        RAISE EXCEPTION 'Limite de profissionais odontológicos contratados atingido'
          USING ERRCODE='23514',CONSTRAINT='dental_professional_capacity';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER dental_professional_capacity
BEFORE INSERT OR UPDATE OF active,tenant_id ON scheduling_professional
FOR EACH ROW EXECUTE FUNCTION applanner_guard_dental_capacity();
"""


def install(apps,schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(SQL)


def uninstall(apps,schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("DROP TRIGGER IF EXISTS dental_professional_capacity ON scheduling_professional; DROP FUNCTION IF EXISTS applanner_guard_dental_capacity();")


class Migration(migrations.Migration):
    dependencies=[("scheduling","0025_appointmentworknote_technical_encrypted"),
                  ("billing","0022_dentistry_module")]
    operations=[migrations.RunPython(install,uninstall)]
