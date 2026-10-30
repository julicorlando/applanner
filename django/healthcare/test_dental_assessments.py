import json
import uuid
from io import BytesIO
from unittest import skipUnless
from django.test import TestCase
from django.db import connection, transaction, IntegrityError
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from . import test_assessments as fixtures
from .dental_assessment_forms import AssessmentForm
from .dental_assessment_services import save_assessment, read_assessment, assessments_for, AssessmentConflict
from .models import DentalAssessment, DentalAssessmentVersion
from .dentistry import dental_history


class DentalAssessmentTests(TestCase):
    def create(self, **kwargs):
        return fixtures.AssessmentTests.create(self, **kwargs)

    def setUp(self):
        fixtures.AssessmentTests.setUp(self)
        self.tenant.category = 'odontologia'
        self.tenant.save()
        reg = self.professional.clinical_registration
        reg.council = 'CRO'
        reg.jurisdiction = 'PE'
        reg.save()

    def data(self, **changes):
        data = dict(submission_key=str(uuid.uuid4()), customer=self.patient.pk, professional=self.professional.pk, evaluation_date='2026-10-29', version=0, chief_complaint='Dor dentária confidencial', findings='Exame confidencial', medical_history='Histórico confidencial', systemic_flags=['Uso de medicamentos'], dental_flags=['Bruxismo'], goals=json.dumps([{'text':'Hipótese em avaliação'}]), treatment_plan=json.dumps([{'text':'Restauração','tooth':'46','amount':'180.00','status':'pending'}]), odontogram_json=json.dumps({'46':[{'condition':'carie','surfaces':['oclusal'],'note':'Observação confidencial'}]}))
        data.update(changes)
        return data

    def save(self, row=None, final=False, **changes):
        if row:
            changes.setdefault('version', row.version)
            changes.setdefault('submission_key', str(row.submission_key))
        if final:
            changes.update(appointment=self.appointment.pk, attestation='on')
        form = AssessmentForm(self.data(**changes), user=self.doctor, assessment=row, finalizing=final)
        self.assertTrue(form.is_valid(), form.errors)
        return save_assessment(form=form, user=self.doctor, assessment_id=row.pk if row else None, finalize=final)

    def test_draft_encryption_revision_and_stale_write(self):
        row=self.save()
        self.assertNotIn('confidencial',row.payload_encrypted)
        self.assertEqual(read_assessment(assessment=row,user=self.doctor)['sections']['chief_complaint'],'Dor dentária confidencial')
        self.save(row, chief_complaint='Revisão')
        with self.assertRaises(AssessmentConflict):
            self.save(row,chief_complaint='Sessão desatualizada')
        self.assertEqual(row.versions.count(),2)
        self.assertEqual(read_assessment(assessment=row,user=self.doctor,version=1)['sections']['chief_complaint'],'Dor dentária confidencial')

    def test_finalization_is_idempotent_and_appears_in_existing_dental_history(self):
        row=self.save(final=True)
        self.assertEqual(row.status,'finalized')
        self.assertEqual(str(row.treatment_plan.total),'180.00')
        self.assertEqual(row.treatment_plan.status,'proposed')
        payload=read_assessment(assessment=row,user=self.doctor)
        self.assertEqual(payload['signature']['council'],'CRO')
        self.assertEqual(payload['professional']['jurisdiction'],'PE')
        self.assertEqual(payload['sections']['treatment_plan'][0]['amount'],'180.00')
        self.assertEqual(dental_history(tenant=self.tenant,customer=self.patient,user=self.doctor)[-1]['data']['odontogram']['46'][0]['condition'],'carie')
        self.assertEqual(self.save(row,final=True).pk,row.pk)
        self.assertEqual(row.versions.count(),1)
        with self.assertRaises(ValidationError):
            row.save()
        with self.assertRaises(ValidationError):
            DentalAssessmentVersion.objects.filter(assessment=row).update(status='draft')

    def test_finalization_requires_appointment_signature_attestation_and_cro(self):
        form=AssessmentForm(self.data(),user=self.doctor,finalizing=True)
        self.assertFalse(form.is_valid())
        reg=self.professional.clinical_registration
        reg.council='CREFITO';reg.jurisdiction='1';reg.save()
        with self.assertRaises(ValidationError):
            self.save(final=True)

    def test_reception_master_owner_other_clinician_cannot_read_draft_or_documents(self):
        row=self.save()
        for user in (self.reception,self.master,self.owner,self.colleague):
            with self.subTest(role=user.role):
                with self.assertRaises(PermissionDenied):
                    read_assessment(assessment=row,user=user)
                self.client.force_login(user)
                self.assertIn(self.client.get(reverse('dental-assessment-detail',args=[row.pk])).status_code,{403,404})

    def test_invalid_tooth_price_status_and_foreign_identity_rejected(self):
        for changes in [dict(odontogram_json='{"99":[]}'),dict(treatment_plan='[{"text":"X","amount":"NaN"}]'),dict(treatment_plan='[{"text":"X","amount":"1.111"}]'),dict(treatment_plan='[{"text":"X","tooth":"99"}]'),dict(treatment_plan='[{"text":"X","status":"fake"}]'),dict(customer=999999),dict(professional=self.colleague_profile.pk)]:
            with self.subTest(changes=changes):
                self.assertFalse(AssessmentForm(self.data(**changes),user=self.doctor).is_valid())

    def test_editor_reference_sections_and_private_clinical_access(self):
        self.client.force_login(self.doctor)
        response=self.client.get(reverse('dental-assessment-create'),{'customer':self.patient.pk})
        self.assertEqual(response.status_code,200)
        for text in ('Prontuário Odontológico','Histórico médico e odontológico','Odontograma interativo','Imagens e exames','Finalizar atendimento','Salvar rascunho','Diagnóstico','Plano de tratamento','Anamnese odontológica','Assinatura do profissional','data-layout="rows"','Menu Odontologia'):
            self.assertContains(response,text)
        self.assertNotContains(response,'Menu Fisioterapia')
        self.assertContains(response,'id="pa-sidebar"',count=1)

    def test_existing_dental_owner_and_reception_get_workspace_without_clinical_permission(self):
        for user in (self.owner,self.reception):
            self.client.force_login(user)
            response=self.client.get(reverse('dental-dashboard'))
            self.assertEqual(response.status_code,200)
            self.assertContains(response,'Menu Odontologia')
            self.assertEqual(self.client.get(reverse('dental-assessment-create')).status_code,403)

    def test_private_upload_encrypted_and_restricted(self):
        stream=BytesIO();Image.new('RGB',(32,32),'white').save(stream,format='PNG')
        upload=SimpleUploadedFile('exame-ficticio.png',stream.getvalue(),content_type='image/png')
        form=AssessmentForm(self.data(),{'documents':[upload]},user=self.doctor)
        self.assertTrue(form.is_valid(),form.errors)
        row=save_assessment(form=form,user=self.doctor)
        document=row.documents.get()
        self.assertNotIn(b'PNG',bytes(document.content_encrypted))
        self.client.force_login(self.doctor)
        response=self.client.get(reverse('dental-assessment-document',args=[document.pk])+'?preview=1')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['X-Content-Type-Options'],'nosniff')
        self.client.force_login(self.reception)
        self.assertEqual(self.client.get(reverse('dental-assessment-document',args=[document.pk])).status_code,403)

    def test_fisioterapia_does_not_gain_dental_authorization_by_category_alone(self):
        from billing.models import TenantModule
        self.tenant.category='fisioterapia';self.tenant.save()
        TenantModule.objects.filter(tenant=self.tenant,module__slug='dentistry').delete()
        with self.assertRaises(PermissionDenied):
            assessments_for(self.doctor)

    def test_foreign_patient_and_unrelated_appointment_are_rejected(self):
        from scheduling.models import Customer
        foreign = Customer.objects.create(tenant=self.other, name="Outro paciente")
        self.assertFalse(AssessmentForm(self.data(customer=foreign.pk),user=self.doctor).is_valid())
        other_patient = Customer.objects.create(tenant=self.tenant, name="Paciente diferente")
        form=AssessmentForm(self.data(customer=other_patient.pk,appointment=self.appointment.pk,attestation="on"),user=self.doctor,finalizing=True)
        self.assertFalse(form.is_valid())
        self.assertFalse(DentalAssessment.objects.exists())

    def test_invalid_upload_rolls_back_and_final_documents_are_preserved(self):
        form=AssessmentForm(self.data(),{'documents':[SimpleUploadedFile('exame.png',b'<script>invalid</script>',content_type='image/png')]},user=self.doctor)
        self.assertTrue(form.is_valid(),form.errors)
        with self.assertRaises(ValidationError):
            save_assessment(form=form,user=self.doctor)
        self.assertFalse(DentalAssessment.objects.exists())

    def test_category_odontologia_wins_when_both_clinical_modules_are_enabled(self):
        from billing.models import Module, TenantModule
        module,_=Module.objects.get_or_create(slug='physiotherapy',defaults={'name':'Fisioterapia'})
        TenantModule.objects.create(tenant=self.tenant,module=module,enabled=True)
        self.client.force_login(self.owner)
        response=self.client.get(reverse('dental-dashboard'))
        self.assertContains(response,'Menu Odontologia')
        self.assertNotContains(response,'Menu Fisioterapia')

    def test_dicom_part10_is_encrypted_private_and_invalid_header_is_rejected(self):
        from pydicom.dataset import FileDataset, FileMetaDataset
        from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid
        from .dental_documents import validate_document_upload
        meta=FileMetaDataset()
        meta.TransferSyntaxUID=ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID=SecondaryCaptureImageStorage
        meta.MediaStorageSOPInstanceUID=generate_uid()
        ds=FileDataset(None,{},file_meta=meta,preamble=b"\0"*128)
        ds.SOPClassUID=meta.MediaStorageSOPClassUID
        ds.SOPInstanceUID=meta.MediaStorageSOPInstanceUID
        stream=BytesIO();ds.save_as(stream,enforce_file_format=True)
        form=AssessmentForm(self.data(upload_kind='radiograph'),{'documents':[SimpleUploadedFile('exame.dcm',stream.getvalue(),content_type='application/dicom')]},user=self.doctor)
        self.assertTrue(form.is_valid(),form.errors)
        row=save_assessment(form=form,user=self.doctor)
        document=row.documents.get()
        self.assertEqual(document.mime_type,'application/dicom')
        self.assertEqual(document.kind,'radiograph')
        self.assertNotIn(b'DICM',bytes(document.content_encrypted))
        with self.assertRaises(ValidationError):
            validate_document_upload(upload=SimpleUploadedFile('invalido.dcm',b'bad'))

    @skipUnless(connection.vendor=='postgresql','PostgreSQL ledger triggers')
    def test_postgresql_preserves_finalized_content_and_versions(self):
        row=self.save(final=True)
        with self.assertRaises(IntegrityError),transaction.atomic(),connection.cursor() as cursor:
            cursor.execute('UPDATE healthcare_dentalassessment SET payload_encrypted=%s WHERE id=%s',['tamper',row.pk])
        with self.assertRaises(IntegrityError),transaction.atomic(),connection.cursor() as cursor:
            cursor.execute('DELETE FROM healthcare_dentalassessmentversion WHERE assessment_id=%s',[row.pk])
