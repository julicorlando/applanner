import io
import zipfile
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.crypto import decrypt_text
from scheduling.models import Customer

from . import test_dental_assessments as dental
from .document_models import PatientNote
from .record_import_parser import parse_sheet, read_upload

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _cell(text):
    paras = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{line}</w:t></w:r></w:p>" for line in text.split("\n"))
    return f"<w:tc>{paras}</w:tc>"


def _table(rows):
    return "<w:tbl>" + "".join("<w:tr>" + "".join(_cell(c) for c in row) + "</w:tr>" for row in rows) + "</w:tbl>"


def sheet_xml(name="Paciente Ficha Exemplo", birth="21/04/1996", phone="(81) 99305-0322 (Mãe)"):
    budget = _table([["Orçamentos/Procedimentos\n14/07/2026\nRestauração 26(O) = R$ 90,00", "Observações\nFoi dado desconto."]])
    visits = _table([
        ["Data", "Procedimento Clínico", "Valor recebido", "Valor pago", "Profissional"],
        ["06/05/2023", "Selamento 36 e 46", "100,00", "100,00", "Dr. Exemplo"],
        ["", "Raspagem + Profilaxia + Flúor", "120,00", "–", ""],
        ["", "", "", "", ""],
        ["TRATAMENTO ORTODÔNTICO"],
        ["Data", "Procedimento Clínico", "Valor recebido", "Valor pago", "Profissional"],
        ["02/10/2026", "Sup. 0,17 x 0,25 Niti", "80,00", "80,00", "Dr. Exemplo"],
    ])
    header = _table([[f"Paciente: {name}", f"Data de Nascimento: {birth}"],
                     ["Cidade: Paudalho      Estado: PE", f"Telefone: {phone}"]])
    return f"<w:document {W}><w:body>{budget}{visits}{header}</w:body></w:document>".encode()


def docx(xml):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


class SheetParserTests(TestCase):
    def test_reads_every_field_and_keeps_sections_apart(self):
        sheet = parse_sheet("Paciente Ficha Exemplo - Só Rx.docx", sheet_xml())
        self.assertEqual(sheet["name"], "Paciente Ficha Exemplo")
        self.assertEqual(sheet["birth_date"], "1996-04-21")
        self.assertEqual(sheet["phone"], "5581993050322")
        self.assertEqual((sheet["city"], sheet["state"]), ("Paudalho", "PE"))
        visit = sheet["visits"]["2023-05-06"]
        self.assertEqual(visit["procedure"], [
            "Selamento 36 e 46 · Valor recebido: R$ 100,00 · Valor pago: R$ 100,00 · Profissional: Dr. Exemplo",
            "Raspagem + Profilaxia + Flúor · Valor recebido: R$ 120,00"])
        self.assertEqual(sheet["visits"]["2026-10-02"]["orthodontic"],
                         ["Sup. 0,17 x 0,25 Niti · Valor recebido: R$ 80,00 · Valor pago: R$ 80,00 · Profissional: Dr. Exemplo"])
        self.assertEqual(sheet["budgets"], {"2026-07-14": "Restauração 26(O) = R$ 90,00"})
        self.assertEqual(sheet["observations"], "Foi dado desconto.")
        self.assertEqual(sheet["remarks"], ["Só Rx"])
        self.assertIn("Telefone na ficha: (81) 99305-0322 (Mãe)", sheet["sheet_details"])

    def test_unknown_birth_year_is_kept_as_text_and_template_is_ignored(self):
        sheet = parse_sheet("x.docx", sheet_xml(birth="19/10/xxxx"))
        self.assertEqual(sheet["birth_date"], "")
        self.assertIn("Data de nascimento na ficha: 19/10/xxxx", sheet["sheet_details"])
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("Fichas/0-FICHA CLÍNICA E ORTODÔNTICA PARA EDITAR.docx", docx(sheet_xml(name="")))
            z.writestr("Fichas/Paciente Ficha Exemplo.docx", docx(sheet_xml()))
        sheets, problems = read_upload("fichas.zip", archive.getvalue())
        self.assertEqual([s["name"] for s in sheets], ["Paciente Ficha Exemplo"])
        self.assertEqual(problems, [])


def ortho_xml(name="Paciente Orto Exemplo", birth="26/08/1988"):
    header = _table([[f"Paciente: {name}", f"Data de Nascimento: {birth}"],
                     ["Documentação digital: [ X ] SIM [ ] NÃO", "Cidade: Carpina"]])
    visits = _table([
        ["Aparelho Metálico Convencional", "R$ 70,00"],
        ["Data", "Procedimento Clínico", "Próx. Consulta"],
        ["29/03/2023", "Sup. 0,18 Niti / Inf. CDB 35 e 45", "CDT 16 e 26"],
        ["03/2024", "Sup. 0,16 Niti", "Evoluir"],
        ["08/01/2025", "", ""],
        ["A realizar", "Contenção", ""],
    ])
    return f"<w:document {W}><w:body>{header}{visits}</w:body></w:document>".encode()


class OrthoSheetTests(TestCase):
    def test_orthodontic_sheet_and_windows_zip_names(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            info = zipfile.ZipInfo("PACIENTES DE ORTO/Pacientes com TTO em Andamento/Ortodôntico.docx".encode("cp850").decode("cp437"))
            z.writestr(info, docx(ortho_xml()))
        (sheet,), problems = read_upload("orto.zip", archive.getvalue())
        self.assertEqual(problems, [])
        self.assertEqual(sheet["file"], "Ortodôntico.docx")
        self.assertEqual((sheet["name"], sheet["birth_date"], sheet["city"]), ("Paciente Orto Exemplo", "1988-08-26", "Carpina"))
        self.assertEqual(sheet["visits"]["2023-03-29"]["orthodontic"],
                         ["Sup. 0,18 Niti / Inf. CDB 35 e 45 · Próx. consulta: CDT 16 e 26"])
        self.assertEqual(sheet["visits"]["2024-03-01"]["orthodontic"], ["[Data na ficha: 03/2024] Sup. 0,16 Niti · Próx. consulta: Evoluir"])
        self.assertEqual(sheet["visits"]["2025-01-08"]["orthodontic"], ["Consulta registrada na ficha, sem procedimento descrito."])
        self.assertEqual(sheet["visits"][""]["orthodontic"], ["[A realizar] Contenção"])
        self.assertIn("Documentação digital: Sim", sheet["sheet_details"])
        self.assertIn("Aparelho/tratamento: Aparelho Metálico Convencional · R$ 70,00", sheet["sheet_details"])
        self.assertIn("Pasta da ficha: PACIENTES DE ORTO / Pacientes com TTO em Andamento", sheet["sheet_details"])

    def test_same_name_different_birth_year_stays_two_patients(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("F/a.docx", docx(ortho_xml(name="Carla Exemplo", birth="20/08/1990")))
            z.writestr("F/b.docx", docx(ortho_xml(name="Carla Exemplo", birth="21/10/2006")))
        sheets, _ = read_upload("f.zip", archive.getvalue())
        self.assertEqual(len({s["key"] for s in sheets}), 2)


class RecordImportTests(TestCase):
    create = dental.DentalAssessmentTests.create

    def setUp(self):
        dental.DentalAssessmentTests.setUp(self)

    def upload(self, *files):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            for name, xml in files:
                z.writestr(name, docx(xml))
        return self.client.post(reverse("dental-record-import"),
                                {"file": SimpleUploadedFile("fichas.zip", archive.getvalue(), content_type="application/zip")})

    def test_preview_then_import_on_original_dates_without_duplicates(self):
        existing = Customer.objects.create(tenant=self.tenant, name="Rosa Exemplo de Lima", phone="5581989880142")
        self.client.force_login(self.doctor)
        response = self.upload(("Nova Ficha.docx", sheet_xml()), ("Rosa.docx", sheet_xml(name="Rosa Exemplo de Lima")))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Novo paciente")
        self.assertContains(response, "Já cadastrado")
        self.assertContains(response, "Selamento 36 e 46")
        self.assertEqual(PatientNote.objects.count(), 0)
        payload = response.context["payload"]
        result = self.client.post(reverse("dental-record-import"), {"action": "confirm", "payload": payload})
        self.assertRedirects(result, reverse("dental-assessments"), fetch_redirect_response=False)
        created = Customer.objects.get(tenant=self.tenant, name="Paciente Ficha Exemplo")
        self.assertEqual(created.birth_date, date(1996, 4, 21))
        self.assertEqual(created.city, "Paudalho")
        self.assertEqual(created.registered_by, self.doctor)
        existing.refresh_from_db()
        self.assertIsNone(existing.birth_date)  # cadastro existente não é alterado
        self.assertEqual(existing.phone, "5581989880142")
        notes = PatientNote.objects.filter(customer=created).order_by("occurred_at")
        self.assertEqual([timezone.localtime(n.occurred_at).date() for n in notes],
                         [date(2023, 5, 6), date(2026, 7, 14), date(2026, 10, 2), date(2026, 10, 2)])
        self.assertIn("Selamento 36 e 46", decrypt_text(notes[0].text_encrypted))
        self.client.post(reverse("dental-record-import"), {"action": "confirm", "payload": payload})
        self.assertEqual(PatientNote.objects.filter(customer=created).count(), 4)
        record = self.client.get(reverse("dental-patient-record", args=[created.pk]))
        self.assertContains(record, "Ficha antiga")
        self.assertContains(record, "06/05/2023")
        self.assertContains(record, "Sup. 0,17 x 0,25 Niti")

    def test_reception_cannot_import_and_tampered_preview_is_refused(self):
        self.client.force_login(self.reception)
        self.assertEqual(self.client.get(reverse("dental-record-import")).status_code, 403)
        self.client.force_login(self.doctor)
        response = self.client.post(reverse("dental-record-import"), {"action": "confirm", "payload": "x"})
        self.assertRedirects(response, reverse("dental-record-import"), fetch_redirect_response=False)
        self.assertEqual(PatientNote.objects.count(), 0)

    def test_master_reads_records_and_imports_for_the_clinic(self):
        from core.models import AuditLog
        self.client.force_login(self.master)
        listing = self.client.get(reverse("master-patient-records", args=[self.tenant.pk]))
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, self.patient.name)
        record = self.client.get(reverse("master-patient-record", args=[self.tenant.pk, self.patient.pk]))
        self.assertEqual(record.status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action="master.patient_record.viewed", entity_id=self.patient.pk).exists())
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("Nova.docx", docx(sheet_xml(name="Paciente Do Master")))
        url = reverse("master-record-import", args=[self.tenant.pk])
        preview = self.client.post(url, {"file": SimpleUploadedFile("f.zip", archive.getvalue(), content_type="application/zip"),
                                         "owner": self.doctor.pk})
        self.assertContains(preview, "Paciente Do Master")
        done = self.client.post(url, {"action": "confirm", "payload": preview.context["payload"], "owner": self.doctor.pk})
        self.assertEqual(done.status_code, 302)
        created = Customer.objects.get(tenant=self.tenant, name="Paciente Do Master")
        self.assertEqual(created.registered_by, self.doctor)
        self.assertEqual(PatientNote.objects.filter(customer=created).count(), 4)
        self.client.force_login(self.reception)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_master_operating_the_clinic_is_sent_to_master_records(self):
        self.client.force_login(self.master)
        session = self.client.session
        session["portal_tenant_id"] = self.tenant.pk
        session.save()
        self.assertRedirects(self.client.get("/app/clinica/"), reverse("master-patient-records", args=[self.tenant.pk]),
                             fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("portal-resource-list", args=["saude", "prontuarios"])),
                             reverse("clinical-dashboard"), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("dental-patient-record", args=[self.patient.pk])),
                             reverse("master-patient-record", args=[self.tenant.pk, self.patient.pk]), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("master-patient-records", args=[self.tenant.pk])).status_code, 200)
