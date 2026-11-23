from django.db import migrations
from django.db.models.functions import Coalesce


def forwards(apps, schema_editor):
    """Pacientes cujo plano só existe nas versões antigas ganham a tabela do plano com o último plano salvo."""
    from core.crypto import decrypt_text, encrypt_text
    from healthcare.legacy_plan import parse
    PatientNote = apps.get_model("healthcare", "PatientNote")
    DentalPlanItem = apps.get_model("healthcare", "DentalPlanItem")
    with_items = set(DentalPlanItem.objects.values_list("tenant_id", "customer_id").distinct())
    done = set()
    notes = (PatientNote.objects.annotate(effective=Coalesce("occurred_at", "created_at"))
             .order_by("tenant_id", "customer_id", "-effective", "-created_at", "-pk"))
    for note in notes.iterator(chunk_size=500):
        key = (note.tenant_id, note.customer_id)
        if key in done or key in with_items:
            continue
        try:
            items = parse(decrypt_text(note.text_encrypted))
        except Exception:
            continue
        if items is None:
            continue
        done.add(key)  # the newest plan note decides, even when all its items were removed
        for position, item in enumerate(items[:40]):
            DentalPlanItem.objects.create(tenant_id=note.tenant_id, customer_id=note.customer_id, tooth=item["tooth"],
                                          procedure_encrypted=encrypt_text(item["procedure"]), price=item["price"],
                                          position=position, status="planned", created_by_id=note.author_id)


class Migration(migrations.Migration):
    dependencies = [("healthcare", "0027_note_void")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
