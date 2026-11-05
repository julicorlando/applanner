from io import BytesIO
from unittest.mock import patch,Mock
import uuid
from django.test import TestCase
from django.urls import reverse
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from pypdf import PdfReader
from scheduling.models import Customer
from core.crypto import encrypt_text,decrypt_text
from . import test_clinical_security as fixtures
from .models import ClinicalRegistration
from .document_models import ClinicalIssuedDocument
from .document_services import save_signature,finalize_document
from .patient_scope import patients_for
from .drive_models import ClinicalDriveConfiguration,PatientDriveBackup
from .drive_backup import backup_patient,DriveBackupError,upload_pdf,snapshot,render_backup


class ClinicalDocumentDeliveryTests(TestCase):
    def create(self,**kwargs):
        return fixtures.ClinicalSecurityTests.create(self,**kwargs)
    def setUp(self):
        fixtures.ClinicalSecurityTests.setUp(self)
        self.tenant.category='odontologia';self.tenant.save()
        ClinicalRegistration.objects.create(professional=self.professional,council='CRO',number='12345',jurisdiction='PE',professional_name='Dra. Teste')
        self.entry=fixtures.ClinicalSecurityTests.create(self)
        self.client.force_login(self.doctor)

    def image(self):
        stream=BytesIO();Image.new('RGBA',(300,100),(0,0,255,100)).save(stream,'PNG')
        return SimpleUploadedFile('assinatura.png',stream.getvalue(),content_type='image/png')

    def document(self,creator=None):
        return ClinicalIssuedDocument.objects.create(tenant=self.tenant,customer=self.patient,professional=self.professional,
            kind='declaration',title='Declaração de comparecimento',body_encrypted=encrypt_text('Compareceu à clínica nesta data.'),created_by=creator or self.doctor)

    def test_clinical_patient_scope_preserves_nonclinical_segment_customer_list(self):
        from core.portal import _tenant_queryset
        from tenants.models import Tenant
        from accounts.models import User
        tenant=Tenant.objects.create(name='Barbearia fictícia',slug='nonclinical-scope',category='barbearia')
        barber=User.objects.create_user(email='barber-scope@test.invalid',tenant=tenant,role='professional')
        customer=Customer.objects.create(tenant=tenant,name='Cliente da barbearia')
        self.assertTrue(_tenant_queryset(Customer,tenant,user=barber).filter(pk=customer.pk).exists())
        self.assertFalse(_tenant_queryset(Customer,self.tenant,user=self.doctor).filter(pk=customer.pk).exists())

    def test_signature_is_encrypted_private_and_only_owned_professional_can_upload(self):
        row=save_signature(self.doctor,self.image())
        self.assertNotIn(b'PNG',bytes(row.image_encrypted)[:12]);self.assertTrue(row.sha256)
        self.assertEqual(self.client.get(reverse('clinical-signature-image')).status_code,200)
        self.client.force_login(self.reception)
        self.assertEqual(self.client.post(reverse('clinical-signature'),{'authorization':'on','upload':self.image()}).status_code,403)
        with self.assertRaises(PermissionDenied):save_signature(self.master,self.image())
        with self.assertRaises(ValidationError):save_signature(self.doctor,SimpleUploadedFile('bad.svg',b'<svg onload=alert(1)>'))

    def test_emission_requires_confirmation_and_preserves_pdf_after_signature_replacement(self):
        row=self.document();save_signature(self.doctor,self.image())
        with self.assertRaises(ValidationError):finalize_document(user=self.doctor,document=row,body='Revisado',title=row.title,version=1,confirmed=False)
        result=finalize_document(user=self.doctor,document=row,body='Compareceu hoje.',title=row.title,version=1,confirmed=True)
        self.assertEqual(result.status,'finalized');self.assertTrue(result.entry_id)
        response=self.client.get(reverse('clinical-document-pdf',args=[row.pk]))
        self.assertEqual(response.status_code,200);self.assertTrue(response.content.startswith(b'%PDF-'))
        text=''.join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
        self.assertIn('CRO 12345/PE',text);self.assertIn(self.patient.name,text)
        original=response.content;save_signature(self.doctor,remove=True)
        self.assertEqual(self.client.get(reverse('clinical-document-pdf',args=[row.pk])).content,original)
        with self.assertRaises(ValidationError):result.save()
        with self.assertRaises(ValidationError):ClinicalIssuedDocument.objects.filter(pk=row.pk).update(title='Alterado')
        self.assertEqual(self.client.post(reverse('clinical-document-detail',args=[row.pk]),{'action':'draft'}).status_code,409)

    def test_postgresql_trigger_rejects_raw_updates_of_issued_document(self):
        from django.db import connection,transaction,DatabaseError
        if connection.vendor!='postgresql':self.skipTest('PostgreSQL-only immutable trigger')
        row=self.document();save_signature(self.doctor,self.image())
        finalize_document(user=self.doctor,document=row,body='Registro preservado',title=row.title,version=1,confirmed=True)
        with self.assertRaises(DatabaseError),transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('UPDATE healthcare_clinicalissueddocument SET title=%s WHERE id=%s',['Alterado',row.pk])
        row.refresh_from_db();self.assertEqual(row.status,'finalized')

    def test_reception_can_prepare_only_own_draft_and_cannot_emit_or_download(self):
        row=self.document(self.reception);self.client.force_login(self.reception)
        self.assertEqual(self.client.get(reverse('clinical-document-detail',args=[row.pk])).status_code,200)
        response=self.client.post(reverse('clinical-document-detail',args=[row.pk]),{'action':'finalize','title':row.title,'body':'Texto preparado','version':1,'confirmed':'on'})
        self.assertEqual(response.status_code,403);row.refresh_from_db();self.assertEqual(row.status,'draft')
        self.assertEqual(self.client.get(reverse('clinical-document-pdf',args=[row.pk])).status_code,403)
        self.client.force_login(self.doctor);save_signature(self.doctor,self.image())
        finalize_document(user=self.doctor,document=row,body='Revisado',title=row.title,version=1,confirmed=True)
        self.client.force_login(self.reception)
        self.assertEqual(self.client.get(reverse('clinical-document-detail',args=[row.pk])).status_code,404)

    def test_shared_template_creates_patient_draft_without_applying_signature(self):
        from .document_models import ClinicalDocumentTemplate
        template=ClinicalDocumentTemplate.objects.create(tenant=self.tenant,name='Declaração padrão',kind='declaration',text_encrypted=encrypt_text('Declaramos comparecimento de {nome_paciente} em {data}.'),created_by=self.doctor)
        result=self.client.post(reverse('clinical-documents'),{'customer':self.patient.pk,'professional':self.professional.pk,'template':template.pk,'kind':'declaration','title':'Declaração','request_id':str(uuid.uuid4()),'body':''})
        self.assertEqual(result.status_code,302,result.content[:200])
        document=ClinicalIssuedDocument.objects.get(template=template)
        self.assertIn(self.patient.name,decrypt_text(document.body_encrypted));self.assertEqual(document.status,'draft');self.assertFalse(document.pdf_encrypted)

    def test_healthcare_role_cannot_use_legacy_company_lists(self):
        self.client.force_login(self.colleague)
        self.assertEqual(self.client.get(reverse('portal-resource-list',args=['agenda','agendamentos'])).status_code,403)
        self.assertEqual(self.client.get(reverse('operation-today')).status_code,403)
        self.assertEqual(self.client.get(reverse('operation-calendar')).status_code,200)

    def test_same_clinic_other_professional_cannot_find_patient_or_document(self):
        row=self.document();other=Customer.objects.create(tenant=self.tenant,name='Paciente de outro profissional')
        from .services import create_record
        create_record(tenant=self.tenant,customer=other,professional=self.colleague_profile,user=self.colleague,title='Outro',content='Privado')
        self.assertFalse(patients_for(self.doctor).filter(pk=other.pk).exists())
        self.assertTrue(patients_for(self.reception,administrative=True).filter(pk=other.pk).exists())
        self.assertEqual(self.client.get(reverse('clinical-patient',args=[other.pk])).status_code,404)
        self.client.force_login(self.colleague)
        self.assertEqual(self.client.get(reverse('clinical-document-detail',args=[row.pk])).status_code,404)
        self.assertEqual(self.client.get(reverse('clinical-document-pdf',args=[row.pk])).status_code,404)


class ClinicalDriveTests(ClinicalDocumentDeliveryTests):
    def setUp(self):
        super().setUp()
        self.config=ClinicalDriveConfiguration.objects.create(tenant=self.tenant,enabled=True,client_id='oauth-client',
            client_secret_encrypted=encrypt_text('secret-not-visible'),refresh_token_encrypted=encrypt_text('refresh-not-visible'),
            account_email='backup@example.invalid',folder_id='folder_fictitious_01',authorized_by=self.master,authorized_at=timezone.now())
        self.job=PatientDriveBackup.objects.create(configuration=self.config,customer=self.patient,generation=1)

    def test_backup_uses_stable_id_and_replaces_when_patient_changes(self):
        with patch('healthcare.drive_backup.access_token',return_value='fake'),patch('healthcare.drive_backup.generated_id',return_value='file_fictitious_01'),patch('healthcare.drive_backup.upload_pdf') as upload:
            self.assertEqual(backup_patient(self.job.pk),'success')
            self.job.refresh_from_db();first_id=self.job.file_id;first_hash=self.job.source_sha256
            self.assertEqual(first_id,'file_fictitious_01');self.assertTrue(upload.call_args.args[2].startswith(b'%PDF-'))
            self.patient.name='Paciente atualizado';self.patient.save()
            self.assertEqual(backup_patient(self.job.pk),'success')
            self.job.refresh_from_db();self.assertEqual(self.job.file_id,first_id);self.assertNotEqual(self.job.source_sha256,first_hash)
            self.assertEqual(upload.call_count,2)

    def test_unchanged_source_checks_remote_integrity_without_reuploading(self):
        with patch('healthcare.drive_backup.access_token',return_value='fake'),patch('healthcare.drive_backup.generated_id',return_value='file_fictitious_01'),patch('healthcare.drive_backup.upload_pdf'):
            backup_patient(self.job.pk)
        self.job.refresh_from_db()
        response=Mock(status_code=200);response.json.return_value={'parents':[self.config.folder_id],'trashed':False,'md5Checksum':self.job.pdf_md5}
        with patch('healthcare.drive_backup.access_token',return_value='fake'),patch('healthcare.drive_backup.google',return_value=response),patch('healthcare.drive_backup.upload_pdf') as upload:
            self.assertEqual(backup_patient(self.job.pk),'unchanged');upload.assert_not_called()

    def test_failed_upload_retries_same_reserved_file_and_records_no_clinical_text(self):
        with patch('healthcare.drive_backup.access_token',return_value='fake'),patch('healthcare.drive_backup.generated_id',return_value='file_fictitious_01'),patch('healthcare.drive_backup.upload_pdf',side_effect=DriveBackupError('google_http_503')):
            with self.assertRaises(DriveBackupError):backup_patient(self.job.pk)
        self.job.refresh_from_db();self.assertEqual(self.job.file_id,'file_fictitious_01');self.assertEqual(self.job.status,'failed')
        self.assertEqual(self.job.last_error_code,'google_http_503');self.assertFalse(self.job.source_sha256)
        self.config.enabled=False;self.config.save()
        with patch('healthcare.drive_backup.google') as google:
            self.assertEqual(backup_patient(self.job.pk),'skipped');google.assert_not_called()

    def test_drive_update_keeps_file_in_authorized_folder_and_validates_upload_host(self):
        self.job.file_id='file_fictitious_01'
        existing=Mock(status_code=200);existing.json.return_value={'parents':[self.config.folder_id],'mimeType':'application/pdf','trashed':False}
        session=Mock(status_code=200,headers={'Location':'https://www.googleapis.com/upload/drive/v3/files/file_fictitious_01?upload_id=fake'})
        completed=Mock(status_code=200);completed.json.return_value={'id':self.job.file_id}
        with patch('healthcare.drive_backup.google',side_effect=[existing,session,completed]) as google:
            upload_pdf(self.config,self.job,b'%PDF-fake','fake-token')
            self.assertEqual(google.call_args_list[1].args[0],'PATCH');self.assertEqual(google.call_args_list[2].args[0],'PUT')
        session.headers={'Location':'http://127.0.0.1/private'}
        with patch('healthcare.drive_backup.google',side_effect=[existing,session]):
            with self.assertRaises(DriveBackupError):upload_pdf(self.config,self.job,b'%PDF-fake','fake')

    def test_master_configuration_never_exposes_tokens_or_clinical_pdf(self):
        self.master.is_staff=True;self.master.save()
        self.client.force_login(self.master)
        response=self.client.get(reverse('master-clinical-drive',args=[self.tenant.pk]))
        self.assertEqual(response.status_code,200);self.assertNotContains(response,'secret-not-visible');self.assertNotContains(response,'refresh-not-visible')
        self.assertNotContains(response,self.patient.name)
        self.client.force_login(self.reception)
        self.assertEqual(self.client.get(reverse('master-clinical-drive',args=[self.tenant.pk])).status_code,403)
        self.assertEqual(self.client.get(reverse('master-clinical-drive-callback')+'?state=bad').status_code,403)

    def test_export_pdf_has_history_and_original_attachments(self):
        from .clinical import attach_document
        image=self.image();attach_document(entry=self.entry,user=self.doctor,upload=image,kind='image')
        content,files,digest=snapshot(self.patient);pdf=render_backup(content,files)
        reader=PdfReader(BytesIO(pdf));self.assertTrue(reader.pages);self.assertTrue(files)
        self.assertIn('Cópia de segurança',reader.pages[0].extract_text());self.assertEqual(len(digest),64)
        self.assertTrue(reader.attachments)

    def test_invalid_oauth_state_cannot_connect_account(self):
        self.master.is_staff=True;self.master.save();self.client.force_login(self.master)
        response=self.client.get(reverse('master-clinical-drive-callback')+'?state=invalid&code=fake')
        self.assertEqual(response.status_code,400)

    def test_daily_queue_is_idempotent_and_does_not_send_without_authorization(self):
        from .drive_tasks import enqueue_company
        from unittest.mock import patch
        self.config.hour=0;self.config.save()
        with patch('healthcare.drive_tasks.send_patient_drive_backup.delay') as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(enqueue_company(self.config.pk),1)
                self.assertEqual(dispatch.call_count,0)
            self.assertEqual(dispatch.call_count,1)
        self.config.authorized_at=None;self.config.save()
        with patch('healthcare.drive_tasks.send_patient_drive_backup.delay') as dispatch:
            self.assertEqual(enqueue_company(self.config.pk),0);dispatch.assert_not_called()
