"""Guardas no banco (PostgreSQL) para o ciclo de vida da evolução clínica e cópia do plano atual.

- healthcare_dentalevolution: DELETE só de rascunho; FINALIZADO só muda para RETIFICADO (sem tocar
  nos campos clínicos); RETIFICADO nunca muda; vínculo de clínica/paciente/autor é imutável.
- healthcare_dentalplanitem: item EXECUTADO não é apagado nem tem dente/procedimento/valor alterados.
- healthcare_patientnoterectification: append-only.
- Dados: o plano atual de cada paciente (última versão salva como PatientNote) vira itens PLANEJADOS.
  As notas antigas ficam intactas."""
import json
import re
from decimal import Decimal, InvalidOperation

from django.db import migrations

GUARDS = """
CREATE FUNCTION applanner_guard_dental_evolution() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Evolucao finalizada preservada; utilize retificacao' USING ERRCODE='23514';
    END IF;
    RETURN OLD;
  END IF;
  IF NEW.tenant_id <> OLD.tenant_id OR NEW.customer_id <> OLD.customer_id
     OR NEW.created_by_id <> OLD.created_by_id OR NEW.created_at <> OLD.created_at THEN
    RAISE EXCEPTION 'Vinculo clinico imutavel' USING ERRCODE='23514';
  END IF;
  IF OLD.status = 'rectified' THEN
    RAISE EXCEPTION 'Evolucao retificada e preservada sem alteracoes' USING ERRCODE='23514';
  END IF;
  IF OLD.status = 'draft' AND NEW.status = 'rectified' THEN
    RAISE EXCEPTION 'Rascunho nao se retifica' USING ERRCODE='23514';
  END IF;
  IF OLD.status = 'finalized' THEN
    IF NEW.status <> 'rectified'
       OR NEW.tooth IS DISTINCT FROM OLD.tooth
       OR NEW.procedure_encrypted IS DISTINCT FROM OLD.procedure_encrypted
       OR NEW.orthodontic_encrypted IS DISTINCT FROM OLD.orthodontic_encrypted
       OR NEW.notes_encrypted IS DISTINCT FROM OLD.notes_encrypted
       OR NEW.clinical_date IS DISTINCT FROM OLD.clinical_date
       OR NEW.professional_id IS DISTINCT FROM OLD.professional_id
       OR NEW.plan_item_id IS DISTINCT FROM OLD.plan_item_id
       OR NEW.previous_id IS DISTINCT FROM OLD.previous_id
       OR NEW.author_name IS DISTINCT FROM OLD.author_name
       OR NEW.finalized_at IS DISTINCT FROM OLD.finalized_at
       OR NEW.finalized_by_id IS DISTINCT FROM OLD.finalized_by_id
       OR NEW.finalized_automatically IS DISTINCT FROM OLD.finalized_automatically
       OR NEW.content_sha256 IS DISTINCT FROM OLD.content_sha256 THEN
      RAISE EXCEPTION 'Evolucao finalizada e imutavel; utilize retificacao' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER dental_evolution_lifecycle_guard BEFORE UPDATE OR DELETE ON healthcare_dentalevolution
  FOR EACH ROW EXECUTE FUNCTION applanner_guard_dental_evolution();

CREATE FUNCTION applanner_guard_dental_plan_item() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status = 'executed' THEN
      RAISE EXCEPTION 'Item executado preservado' USING ERRCODE='23514';
    END IF;
    RETURN OLD;
  END IF;
  IF NEW.tenant_id <> OLD.tenant_id OR NEW.customer_id <> OLD.customer_id THEN
    RAISE EXCEPTION 'Vinculo do plano imutavel' USING ERRCODE='23514';
  END IF;
  IF OLD.status = 'executed' AND (NEW.tooth IS DISTINCT FROM OLD.tooth
       OR NEW.procedure_encrypted IS DISTINCT FROM OLD.procedure_encrypted OR NEW.price IS DISTINCT FROM OLD.price) THEN
    RAISE EXCEPTION 'Item executado nao pode ser editado' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER dental_plan_item_guard BEFORE UPDATE OR DELETE ON healthcare_dentalplanitem
  FOR EACH ROW EXECUTE FUNCTION applanner_guard_dental_plan_item();

CREATE TRIGGER patient_note_rectification_immutable BEFORE UPDATE OR DELETE ON healthcare_patientnoterectification
  FOR EACH ROW EXECUTE FUNCTION applanner_preserve_clinical_record();
"""

UNGUARD = """
DROP TRIGGER IF EXISTS patient_note_rectification_immutable ON healthcare_patientnoterectification;
DROP TRIGGER IF EXISTS dental_plan_item_guard ON healthcare_dentalplanitem;
DROP FUNCTION IF EXISTS applanner_guard_dental_plan_item();
DROP TRIGGER IF EXISTS dental_evolution_lifecycle_guard ON healthcare_dentalevolution;
DROP FUNCTION IF EXISTS applanner_guard_dental_evolution();
"""

PLAN_LINE = re.compile(r"^\d+\.\s+(?:Dente\s+(?P<tooth>.+?)\s+·\s+)?(?P<procedure>.+?)\s+·\s+R\$\s*(?P<price>[\d.]+,\d{2})$")
RESPONSIBLE = re.compile(r"^Dentista responsável:\s*(?P<name>.+)$")


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(GUARDS)


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(UNGUARD)


def _items(data):
    if isinstance(data.get("plan_items"), list):
        for raw in data["plan_items"][:30]:
            try:
                yield str(raw.get("tooth", ""))[:20], str(raw["procedure"])[:200], Decimal(str(raw.get("price", "0")))
            except (KeyError, TypeError, AttributeError, InvalidOperation):
                continue
        return
    for line in str(data.get("plan") or "").splitlines():
        match = PLAN_LINE.match(line.strip())
        if match:
            yield (match["tooth"] or "").strip(), match["procedure"].strip(), Decimal(match["price"].replace(".", "").replace(",", "."))


def copy_current_plans(apps, schema_editor):
    from core.crypto import decrypt_text, encrypt_text
    PatientNote = apps.get_model("healthcare", "PatientNote")
    PlanItem = apps.get_model("healthcare", "DentalPlanItem")
    Professional = apps.get_model("scheduling", "Professional")
    done = set()
    for note in PatientNote.objects.order_by("customer_id", "-occurred_at", "-created_at", "-pk").iterator():
        if note.customer_id in done:
            continue
        try:
            data = json.loads(decrypt_text(note.text_encrypted))
        except Exception:
            continue
        if not isinstance(data, dict) or not str(data.get("plan") or "").strip():
            continue
        done.add(note.customer_id)  # the newest plan note is the current plan
        professional = None
        for line in str(data["plan"]).splitlines():
            match = RESPONSIBLE.match(line.strip())
            if match:
                professional = Professional.objects.filter(tenant_id=note.tenant_id, name=match["name"].strip()).first()
                break
        for position, (tooth, procedure, price) in enumerate(_items(data)):
            if not procedure.strip() or not price.is_finite() or not 0 <= price <= Decimal("99999999.99"):
                continue
            PlanItem.objects.create(tenant_id=note.tenant_id, customer_id=note.customer_id, professional=professional,
                                    tooth=tooth, procedure_encrypted=encrypt_text(procedure), price=price.quantize(Decimal("0.01")),
                                    position=position, status="planned", created_by_id=note.author_id,
                                    created_at=note.created_at)


class Migration(migrations.Migration):
    dependencies = [("healthcare", "0024_dental_plan_evolution"), ("scheduling", "__first__")]
    operations = [
        migrations.RunPython(install, uninstall),
        migrations.RunPython(copy_current_plans, migrations.RunPython.noop),
    ]
