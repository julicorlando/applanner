"""Plano de tratamento x evolução clínica: rascunho, finalização, retificação e auditoria."""
import json
from datetime import timedelta
from unittest import skipUnless

from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.crypto import decrypt_text, encrypt_text
from core.models import AuditLog

from . import test_dental_assessments as dental
from .document_models import PatientNote
from .evolution_models import DentalEvolution, DentalPlanItem, PatientNoteRectification
from .evolution_services import finalize_expired


class DentalEvolutionTests(TestCase):
    create = dental.DentalAssessmentTests.create
    def setUp(self):
        dental.DentalAssessmentTests.setUp(self)
        self.client.force_login(self.doctor)

    def url(self, **query):
        base = reverse("dental-patient-record", args=[self.patient.pk])
        return base + ("?" + "&".join(f"{k}={v}" for k, v in query.items()) if query else "")

    def post(self, **data):
        return self.client.post(self.url(), data, REMOTE_ADDR="203.0.113.7")

    def history(self, response):
        return [e for day in response.context["timeline"] for e in day["evolutions"]]

    def draft(self, **data):
        self.post(action="evolution", tooth=data.pop("tooth", "46"), procedure=data.pop("procedure", "Restauração classe II"),
                  **data)
        return DentalEvolution.objects.filter(customer=self.patient).latest("pk")

    # ------------------------------------------------------------ rascunho

    def test_draft_is_editable_and_deletable_by_author_and_kept_out_of_history(self):
        evolution = self.draft()
        self.assertEqual(evolution.status, "draft")
        self.assertNotIn("Restauração", evolution.procedure_encrypted)  # encrypted at rest
        page = self.client.get(self.url())
        self.assertEqual(len(page.context["drafts"]), 1)
        self.assertEqual(self.history(page), [])
        self.assertContains(page, "Salvar e finalizar atendimento")
        self.post(action="evolution-edit", evolution=evolution.pk, tooth="36", procedure="Restauração classe I")
        evolution.refresh_from_db()
        self.assertEqual((evolution.tooth, decrypt_text(evolution.procedure_encrypted)), ("36", "Restauração classe I"))
        self.client.force_login(self.reception)
        self.assertEqual(self.post(action="evolution-delete", evolution=evolution.pk).status_code, 403)
        self.client.force_login(self.doctor)
        self.post(action="evolution-delete", evolution=evolution.pk)
        self.assertFalse(DentalEvolution.objects.filter(pk=evolution.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action="clinical.dental.evolution.draft_deleted", entity_id=evolution.pk).exists())

    def test_empty_evolution_is_refused_and_future_date_too(self):
        response = self.post(action="evolution", procedure="", notes="")
        self.assertContains(response, "Escreva o procedimento")
        response = self.post(action="evolution", procedure="Profilaxia",
                             clinical_date=(timezone.localdate() + timedelta(days=1)).isoformat())
        self.assertContains(response, "não pode ser no futuro")
        self.assertFalse(DentalEvolution.objects.exists())

    # ------------------------------------------------------------ finalização

    def test_finish_attendance_makes_records_immutable(self):
        first = self.draft()
        self.post(action="evolution", procedure="Profilaxia", finish="1")
        rows = DentalEvolution.objects.filter(customer=self.patient)
        self.assertEqual(set(rows.values_list("status", flat=True)), {"finalized"})
        first.refresh_from_db()
        self.assertEqual(len(first.content_sha256), 64)
        self.assertEqual(first.finalized_by, self.doctor)
        page = self.client.get(self.url())
        self.assertEqual(len(self.history(page)), 2)
        self.assertContains(page, "Retificar lançamento")
        self.assertNotContains(page, f'data-edit="{first.pk}"')
        # The UI, the model and the bulk API all refuse to change or delete it.
        self.post(action="evolution-edit", evolution=first.pk, procedure="Outra coisa")
        self.post(action="evolution-delete", evolution=first.pk)
        first.refresh_from_db()
        self.assertEqual(decrypt_text(first.procedure_encrypted), "Restauração classe II")
        first.tooth = "11"
        with self.assertRaises(ValidationError):
            first.save()
        with self.assertRaises(ValidationError):
            DentalEvolution.objects.get(pk=first.pk).delete()
        with self.assertRaises(ValidationError):
            DentalEvolution.objects.filter(pk=first.pk).update(tooth="11")
        with self.assertRaises(ValidationError):
            DentalEvolution.objects.filter(pk=first.pk).delete()

    def test_finish_button_alone_closes_existing_drafts(self):
        self.draft()
        self.post(action="evolution", finish="1")
        self.assertEqual(DentalEvolution.objects.get().status, "finalized")

    @override_settings(DENTAL_EVOLUTION_DRAFT_HOURS=2)
    def test_draft_finalizes_by_itself_after_the_configured_hours(self):
        evolution = self.draft()
        self.assertEqual(finalize_expired(now=timezone.now() + timedelta(hours=1)), 0)
        self.assertEqual(finalize_expired(now=timezone.now() + timedelta(hours=3)), 1)
        evolution.refresh_from_db()
        self.assertEqual(evolution.status, "finalized")
        self.assertTrue(evolution.finalized_automatically)
        log = AuditLog.objects.get(action="clinical.dental.evolution.auto_finalized", entity_id=evolution.pk)
        self.assertEqual((log.before["status"], log.after["status"]), ("draft", "finalized"))

    @override_settings(DENTAL_EVOLUTION_DRAFT_HOURS=1)
    def test_opening_the_record_finalizes_expired_drafts(self):
        evolution = DentalEvolution.objects.create(tenant=self.tenant, customer=self.patient, created_by=self.doctor,
                                                   author_name="Dra. Ana", clinical_date=timezone.localdate(),
                                                   procedure_encrypted=encrypt_text("Profilaxia"),
                                                   created_at=timezone.now() - timedelta(hours=2))
        page = self.client.get(self.url())
        evolution.refresh_from_db()
        self.assertEqual(evolution.status, "finalized")
        self.assertEqual(page.context["drafts"], [])

    # ------------------------------------------------------------ retificação

    def finalized(self):
        evolution = self.draft()
        self.post(action="finalize")
        evolution.refresh_from_db()
        return evolution

    def test_rectification_keeps_original_links_new_record_and_hides_it_by_default(self):
        original = self.finalized()
        refused = self.post(action="rectify", evolution=original.pk, reason="", tooth="36", procedure="Restauração classe II")
        self.assertEqual(refused.status_code, 302)
        original.refresh_from_db()
        self.assertEqual(original.status, "finalized")
        self.post(action="rectify", evolution=original.pk, reason="Dente incorreto — era o 36", tooth="36",
                  procedure="Restauração classe II")
        original.refresh_from_db()
        self.assertEqual(original.status, "rectified")
        self.assertEqual(original.rectified_by, self.doctor)
        self.assertIsNotNone(original.rectified_at)
        self.assertEqual(decrypt_text(original.rectification_reason_encrypted), "Dente incorreto — era o 36")
        self.assertEqual((original.tooth, decrypt_text(original.procedure_encrypted)), ("46", "Restauração classe II"))
        correction = DentalEvolution.objects.get(previous=original)
        self.assertEqual((correction.status, correction.tooth), ("finalized", "36"))
        page = self.client.get(self.url())
        shown = self.history(page)
        self.assertEqual([e["id"] for e in shown], [correction.pk])
        self.assertIsNotNone(shown[0]["corrects"])
        self.assertContains(page, "Exibir registros retificados (Auditoria)")
        self.assertEqual(page.context["hidden_rectified"], 1)
        audit = self.client.get(self.url(auditoria=1))
        self.assertEqual({e["id"] for e in self.history(audit)}, {original.pk, correction.pk})
        self.assertContains(audit, "Motivo: Dente incorreto — era o 36")
        self.assertTrue(AuditLog.objects.filter(action="clinical.dental.patient_record.audit_viewed").exists())
        # A rectified record can never be rectified, edited or deleted again.
        again = self.post(action="rectify", evolution=original.pk, reason="Outra tentativa", procedure="X y z")
        self.assertEqual(again.status_code, 302)
        self.assertEqual(DentalEvolution.objects.filter(previous=original).count(), 1)
        with self.assertRaises(ValidationError):
            original.save()

    def test_drafts_cannot_be_rectified_and_reception_cannot_rectify_a_dentist_record(self):
        evolution = self.draft()
        self.post(action="rectify", evolution=evolution.pk, reason="Erro de digitação", procedure="Corrigido")
        evolution.refresh_from_db()
        self.assertEqual(evolution.status, "draft")
        self.post(action="finalize")
        self.client.force_login(self.reception)
        page = self.client.get(self.url())
        self.assertNotContains(page, "data-rectify=")
        self.assertEqual(self.post(action="rectify", evolution=evolution.pk, reason="Erro de digitação",
                                   procedure="Corrigido").status_code, 403)

    def test_legacy_note_is_rectified_without_touching_it(self):
        note = PatientNote.objects.create(tenant=self.tenant, customer=self.patient, author=self.doctor, author_name="Dra. Ana",
                                          text_encrypted=encrypt_text(json.dumps({"procedure": "Canal no 11", "text": ""})))
        page = self.client.get(self.url())
        self.assertContains(page, f'data-rectify="{note.pk}" data-kind="note"')
        self.post(action="rectify-note", note=note.pk, reason="Dente incorreto", tooth="21", procedure="Canal no 21")
        link = PatientNoteRectification.objects.get(note=note)
        self.assertEqual(link.replacement.tooth, "21")
        self.assertIn("Canal no 11", decrypt_text(PatientNote.objects.get(pk=note.pk).text_encrypted))
        page = self.client.get(self.url())
        self.assertEqual([n for day in page.context["timeline"] for n in day["notes"]], [])
        self.assertContains(self.client.get(self.url(auditoria=1)), "Canal no 11")
        with self.assertRaises(ValidationError):
            link.save()

    def test_wrong_entries_are_voided_out_of_history_and_kept_for_audit(self):
        original = self.finalized()
        note = PatientNote.objects.create(tenant=self.tenant, customer=self.patient, author=self.doctor, author_name="Dra. Ana",
                                          text_encrypted=encrypt_text(json.dumps({"procedure": "Canal no 11", "text": ""})))
        page = self.client.get(self.url())
        self.assertContains(page, "Anular (lançado por engano)")
        self.post(action="void", evolution=original.pk, reason="")  # reason is required
        original.refresh_from_db()
        self.assertEqual(original.status, "finalized")
        self.post(action="void", evolution=original.pk, reason="Lançado no paciente errado")
        self.post(action="void-note", note=note.pk, reason="Lançado no paciente errado")
        original.refresh_from_db()
        self.assertEqual(original.status, "rectified")
        self.assertFalse(DentalEvolution.objects.filter(previous=original).exists())
        self.assertIsNone(PatientNoteRectification.objects.get(note=note).replacement)
        page = self.client.get(self.url())
        self.assertEqual(self.history(page), [])
        self.assertEqual([n for day in page.context["timeline"] for n in day["notes"]], [])
        audit = self.client.get(self.url(auditoria=1))
        self.assertContains(audit, "Anulado em")
        self.assertContains(audit, "Canal no 11")
        self.assertTrue(AuditLog.objects.filter(action="clinical.dental.evolution.voided").exists())
        self.assertTrue(AuditLog.objects.filter(action="clinical.dental.patient_note.voided").exists())

    def test_reception_cannot_void_a_dentist_record(self):
        original = self.finalized()
        self.client.force_login(self.reception)
        self.assertNotContains(self.client.get(self.url()), "Anular (lançado por engano)")
        self.assertEqual(self.post(action="void", evolution=original.pk, reason="Lançado errado").status_code, 403)

    # ------------------------------------------------------------ auditoria

    def test_audit_log_has_user_ip_and_states_without_clinical_text(self):
        original = self.finalized()
        self.post(action="rectify", evolution=original.pk, reason="Erro de digitação", procedure="Restauração classe III")
        actions = ["clinical.dental.evolution.created", "clinical.dental.evolution.finalized", "clinical.dental.evolution.rectified"]
        for action in actions:
            log = AuditLog.objects.filter(action=action, entity_id=original.pk).first()
            self.assertIsNotNone(log, action)
            self.assertEqual(log.user, self.doctor)
            self.assertEqual(str(log.ip_address), "203.0.113.7")
            self.assertIn("content_sha256", json.dumps(log.after))
            self.assertNotIn("Restauração", json.dumps([log.before, log.after], ensure_ascii=False))
        rectified = AuditLog.objects.get(action="clinical.dental.evolution.rectified")
        self.assertEqual((rectified.before["status"], rectified.after["status"]), ("finalized", "rectified"))
        self.assertNotIn("digitação", json.dumps(rectified.after, ensure_ascii=False))

    # ------------------------------------------------------------ plano de tratamento

    def plan(self, **data):
        base = {"action": "plan", "plan_id": [""], "plan_tooth": ["16"], "plan_procedure": ["Restauração"],
                "plan_price": ["150,00"], "plan_status": ["planned"]}
        base.update(data)
        return self.client.post(self.url(), base)

    def test_plan_items_are_free_to_edit_and_never_in_the_history(self):
        self.plan(plan_id=["", ""], plan_tooth=["16", ""], plan_procedure=["Restauração", "Limpeza"],
                  plan_price=["150,00", "120"], plan_status=["planned", "quoted"])
        items = list(DentalPlanItem.objects.filter(customer=self.patient))
        self.assertEqual([i.status for i in items], ["planned", "quoted"])
        page = self.client.get(self.url())
        self.assertEqual(page.context["plan"]["total"], 270)
        self.assertEqual(self.history(page), [])
        self.assertContains(page, 'value="Limpeza"')
        # Removing a row deletes the planned item physically; changing it updates in place.
        self.plan(plan_id=[str(items[0].pk)], plan_tooth=["17"], plan_procedure=["Restauração"], plan_price=["160"])
        self.assertEqual(list(DentalPlanItem.objects.filter(customer=self.patient).values_list("tooth", "price")),
                         [("17", 160)])
        self.assertTrue(AuditLog.objects.filter(action="clinical.dental.plan_item.deleted", entity_id=items[1].pk).exists())

    def test_executing_plan_item_creates_draft_and_locks_item(self):
        self.plan()
        item = DentalPlanItem.objects.get()
        self.plan(plan_id=[str(item.pk)], execute=str(item.pk))
        item.refresh_from_db()
        self.assertEqual(item.status, "executed")
        evolution = DentalEvolution.objects.get(plan_item=item)
        self.assertEqual((evolution.status, evolution.tooth, decrypt_text(evolution.procedure_encrypted)),
                         ("draft", "16", "Restauração"))
        # An executed item no longer accepts edits or deletion from the plan table.
        self.plan(plan_id=[""], plan_tooth=[""], plan_procedure=[""], plan_price=[""])
        self.assertTrue(DentalPlanItem.objects.filter(pk=item.pk, status="executed").exists())
        with self.assertRaises(ValidationError):
            item.delete()
        # Discarding the draft gives the item back to the plan.
        self.post(action="evolution-delete", evolution=evolution.pk)
        item.refresh_from_db()
        self.assertEqual(item.status, "planned")

    def test_reception_plan_permission_still_applies(self):
        from finance import reception_permissions as perms
        self.client.force_login(self.reception)
        self.plan()
        self.assertEqual(DentalPlanItem.objects.count(), 1)
        values = perms.current(self.tenant)
        values.update(plano=False)
        perms.save(self.tenant, self.owner, values)
        self.assertNotContains(self.client.get(self.url()), 'id="plano"')
        self.assertEqual(self.plan().status_code, 403)

    def test_current_legacy_plan_is_copied_to_plan_items(self):
        import importlib
        from django.apps import apps
        migration = importlib.import_module("healthcare.migrations.0025_dental_evolution_guards")
        PatientNote.objects.create(tenant=self.tenant, customer=self.patient, author=self.doctor, author_name="Dra. Ana",
                                   text_encrypted=encrypt_text(json.dumps({"plan": "1. Dente 16 · Restauração · R$ 150,00",
                                                                           "plan_items": [{"tooth": "16", "procedure": "Restauração", "price": "150.00"},
                                                                                          {"tooth": "", "procedure": "Limpeza", "price": "120"}]})))
        migration.copy_current_plans(apps, connection.schema_editor())
        self.assertEqual(sorted(decrypt_text(i.procedure_encrypted) for i in DentalPlanItem.objects.all()), ["Limpeza", "Restauração"])


@skipUnless(connection.vendor == "postgresql", "Triggers clínicos existem apenas no PostgreSQL")
class DentalEvolutionDatabaseGuardTests(TestCase):
    create = dental.DentalAssessmentTests.create
    def setUp(self):
        dental.DentalAssessmentTests.setUp(self)
        self.client.force_login(self.doctor)
        self.client.post(reverse("dental-patient-record", args=[self.patient.pk]),
                         {"action": "evolution", "procedure": "Restauração", "finish": "1"})
        self.evolution = DentalEvolution.objects.get()

    def raw(self, sql):
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql, [self.evolution.pk])

    def test_finalized_row_rejects_raw_update_and_delete(self):
        self.raw("UPDATE healthcare_dentalevolution SET tooth='11' WHERE id=%s")
        self.raw("UPDATE healthcare_dentalevolution SET status='draft' WHERE id=%s")
        self.raw("DELETE FROM healthcare_dentalevolution WHERE id=%s")


class PatientRecordDocumentTests(TestCase):
    create = dental.DentalAssessmentTests.create

    def setUp(self):
        dental.DentalAssessmentTests.setUp(self)
        self.patient.cpf = "529.982.247-25"
        self.patient.save()

    def test_record_offers_every_document_and_opens_it_with_patient_data(self):
        from .document_models import KINDS
        record = reverse("dental-patient-record", args=[self.patient.pk])
        for user in (self.doctor, self.reception):
            self.client.force_login(user)
            page = self.client.get(record)
            self.assertContains(page, 'id="documentos"')
            for value, label in KINDS:
                self.assertContains(page, f"?customer={self.patient.pk}&amp;kind={value}")
            for kind in ("referral", "report", "exam_request", "certificate"):
                editor = self.client.get(reverse("clinical-documents") + f"?customer={self.patient.pk}&kind={kind}")
                self.assertEqual(editor.status_code, 200)
                body = editor.context["form"].initial.get("body", "")
                self.assertIn(self.patient.name, body, (user.role, kind))
        self.assertIn("CPF", self.client.get(reverse("clinical-documents") + f"?customer={self.patient.pk}&kind=report")
                      .context["form"].initial["body"])


class LegacyPlanTests(TestCase):
    def test_parses_both_saved_formats(self):
        from decimal import Decimal
        from .legacy_plan import parse
        text = "1. Dente 11 · Restauração estética · R$ 90,00\n2. Limpeza · R$ 1.200,50\nTotal do plano: R$ 1.290,50"
        self.assertEqual(parse(json.dumps({"plan": text})), [
            {"tooth": "11", "procedure": "Restauração estética", "price": Decimal("90.00")},
            {"tooth": "", "procedure": "Limpeza", "price": Decimal("1200.50")}])
        self.assertEqual(parse(json.dumps({"plan": "x", "plan_items": [{"tooth": "21", "procedure": "Canal", "price": "400"}]})),
                         [{"tooth": "21", "procedure": "Canal", "price": Decimal("400.00")}])
        self.assertIsNone(parse(json.dumps({"procedure": "Canal"})))

    def test_migration_moves_latest_plan_into_the_table(self):
        import importlib
        from django.apps import apps
        mig = importlib.import_module("healthcare.migrations.0028_legacy_plan_to_items")
        base = dental.DentalAssessmentTests()
        dental.DentalAssessmentTests.setUp(base)
        old = "1. Dente 11 · Restauração estética · R$ 90,00\nTotal do plano: R$ 90,00"
        new = "1. Dente 12 · Restauração estética · R$ 90,00\n2. Dente 21 · Restauração estética · R$ 90,00"
        for text, when in ((old, timezone.now() - timedelta(days=6)), (new, timezone.now())):
            PatientNote.objects.create(tenant=base.tenant, customer=base.patient, author=base.doctor, author_name="Dra",
                                       occurred_at=when, text_encrypted=encrypt_text(json.dumps({"plan": text})))
        mig.forwards(apps, None)
        mig.forwards(apps, None)  # running again changes nothing
        items = DentalPlanItem.objects.filter(customer=base.patient).order_by("position")
        self.assertEqual([(i.tooth, decrypt_text(i.procedure_encrypted)) for i in items],
                         [("12", "Restauração estética"), ("21", "Restauração estética")])
