from datetime import timedelta
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.crypto import encrypt_json
from scheduling.models import Customer, CustomerImportBatch
from tenants.models import Tenant
from .customer_import_service import apply_batch, counts, preview_rows, read_source, suggested_mapping


class CustomerImportTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Destino", slug="import-destino")
        self.other = Tenant.objects.create(name="Outra", slug="import-outra")
        self.master = User.objects.create_superuser(email="import-master@example.test", password="Synthetic-only-123!")
        self.owner = User.objects.create_user(email="import-owner@example.test", role="owner", tenant=self.tenant)
        self.headers = ["Nome", "Telefone", "Email", "Nascimento", "Observacoes"]
        self.mapping = {"name": "0", "phone": "1", "email": "2", "birth_date": "3", "preferences": "4"}

    def batch(self, rows):
        return CustomerImportBatch.objects.create(tenant=self.tenant, created_by=self.master,
            source_name="base.csv", file_hash="a"*64,
            payload_encrypted=encrypt_json({"headers": self.headers, "rows": rows}),
            mapping=self.mapping, expires_at=timezone.now()+timedelta(hours=1))

    def test_csv_encoding_delimiter_mapping_and_preview_does_not_write(self):
        data = "Nome;Telefone;Email;Nascimento;Observacoes\r\nJoão Silva;(81) 90000-0001;JOAO@example.test;20/03/1990;Preferência\r\n"
        headers, rows = read_source(data.encode("cp1252"), "clientes.csv")
        self.assertEqual(suggested_mapping(headers), self.mapping)
        preview = preview_rows(self.tenant, headers, rows, self.mapping)
        self.assertEqual(counts(preview), {"create": 1, "skip": 0, "error": 0})
        self.assertEqual(preview[0]["data"]["phone"], "5581900000001")
        self.assertEqual(preview[0]["data"]["email"], "joao@example.test")
        self.assertEqual(Customer.objects.count(), 0)

    def test_same_phone_email_and_in_file_duplicates_preserve_existing(self):
        existing = Customer.objects.create(tenant=self.tenant, name="Nome original", phone="81900000001",
                                          email="old@example.test", preferences="Histórico original")
        batch = self.batch([["Nome novo", "81900000001", "old@example.test", "", ""],
                            ["Cliente novo", "81900000002", "new@example.test", "", "Preferência"],
                            ["Repetido", "81900000002", "new@example.test", "", ""]])
        applied = apply_batch(batch.pk, self.master, expected_mapping=self.mapping)
        self.assertEqual(applied.report["counts"], {"create": 1, "skip": 2, "error": 0})
        existing.refresh_from_db()
        self.assertEqual(existing.name, "Nome original")
        self.assertEqual(existing.preferences, "Histórico original")
        self.assertFalse(Customer.objects.get(phone="5581900000002").consent_marketing)
        self.assertEqual(applied.payload_encrypted, "")

    def test_cross_company_isolation_and_replay_are_safe(self):
        Customer.objects.create(tenant=self.other, name="Outra", phone="81900000001")
        batch = self.batch([["Novo", "81900000001", "", "", ""]])
        apply_batch(batch.pk, self.master, expected_mapping=self.mapping)
        apply_batch(batch.pk, self.master, expected_mapping=self.mapping)
        self.assertEqual(Customer.objects.filter(tenant=self.tenant).count(), 1)
        self.assertEqual(Customer.objects.filter(tenant=self.other).count(), 1)

    def test_ambiguous_identities_are_not_merged(self):
        Customer.objects.create(tenant=self.tenant, name="Um", phone="81900000001", email="one@example.test")
        Customer.objects.create(tenant=self.tenant, name="Dois", phone="81900000002", email="two@example.test")
        batch = self.batch([["Conflito", "81900000001", "two@example.test", "", ""]])
        with self.assertRaises(ValidationError):
            apply_batch(batch.pk, self.master, expected_mapping=self.mapping)
        self.assertEqual(Customer.objects.count(), 2)

    def test_errors_require_explicit_partial_import_authorization(self):
        batch = self.batch([["Válido", "81900000001", "", "", ""], ["Inválido", "123", "", "", ""]])
        with self.assertRaises(ValidationError):
            apply_batch(batch.pk, self.master, expected_mapping=self.mapping)
        self.assertEqual(Customer.objects.count(), 0)
        applied = apply_batch(batch.pk, self.master, allow_errors=True, expected_mapping=self.mapping)
        self.assertEqual(applied.report["counts"]["error"], 1)
        self.assertEqual(Customer.objects.count(), 1)

    def test_xlsx_support_and_formula_rejection(self):
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(self.headers)
        sheet.append(["Cliente", 81900000001, "", "", ""])
        output = BytesIO()
        workbook.save(output)
        headers, rows = read_source(output.getvalue(), "base.xlsx")
        self.assertEqual(rows[0][1], "81900000001")
        sheet["A2"] = '=HYPERLINK("https://example.test")'
        output = BytesIO()
        workbook.save(output)
        with self.assertRaises(ValidationError):
            read_source(output.getvalue(), "base.xlsx")
        self.assertEqual(headers, self.headers)

    def test_only_master_can_upload_preview_and_download(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("master-customer-import")).status_code, 403)
        batch = self.batch([["Cliente", "81900000001", "", "", ""]])
        self.assertEqual(self.client.get(reverse("master-customer-import-detail", args=[batch.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("master-customer-import-report", args=[batch.pk])).status_code, 403)

    def test_expiry_and_changed_mapping_prevent_apply(self):
        batch = self.batch([["Cliente", "81900000001", "", "", ""]])
        with self.assertRaises(ValidationError):
            apply_batch(batch.pk, self.master, expected_mapping={"name": "0"})
        CustomerImportBatch.objects.filter(pk=batch.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(ValidationError):
            apply_batch(batch.pk, self.master, expected_mapping=self.mapping)
        self.assertEqual(Customer.objects.count(), 0)

    def test_uploaded_preview_is_encrypted_and_apply_requires_signed_preview(self):
        self.client.force_login(self.master)
        source = SimpleUploadedFile("clientes.csv", b"Nome;Telefone\nCliente Importado;81900000001\n", content_type="text/csv")
        response = self.client.post(reverse("master-customer-import"), {"tenant": self.tenant.pk, "source": source})
        self.assertEqual(response.status_code, 302)
        batch = CustomerImportBatch.objects.get()
        self.assertNotIn("Cliente Importado", batch.payload_encrypted)
        detail = reverse("master-customer-import-detail", args=[batch.pk])
        self.assertEqual(self.client.get(detail).status_code, 200)
        self.client.post(detail, {"action": "apply", "preview_token": "forged"})
        self.assertEqual(Customer.objects.count(), 0)
        self.assertEqual(self.client.post(detail, {"action": "preview", "name": "0", "phone": "1",
            "email": "", "birth_date": "", "preferences": ""}).status_code, 200)

    def test_expired_staging_is_cleared_without_deleting_customer_data(self):
        from communications.platform_events import reconcile_platform_events
        existing = Customer.objects.create(tenant=self.tenant, name="Preservado", phone="81900000009")
        batch = self.batch([["Cliente", "81900000001", "", "", ""]])
        CustomerImportBatch.objects.filter(pk=batch.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        reconcile_platform_events()
        batch.refresh_from_db()
        self.assertEqual(batch.payload_encrypted, "")
        self.assertTrue(Customer.objects.filter(pk=existing.pk).exists())

    def test_xlsx_text_expansion_is_bounded(self):
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.append([f"Coluna {index}" for index in range(80)])
        for _ in range(100):
            sheet.append(["x" * 700] * 80)
        output = BytesIO()
        workbook.save(output)
        with self.assertRaises(ValidationError):
            read_source(output.getvalue(), "expanded.xlsx")

    def test_import_staging_does_not_block_authorized_company_deletion(self):
        batch = self.batch([["Cliente", "81900000001", "", "", ""]])
        batch_id = batch.pk
        self.tenant.delete()
        self.assertFalse(CustomerImportBatch.objects.filter(pk=batch_id).exists())
        self.assertTrue(User.objects.filter(pk=self.master.pk).exists())
