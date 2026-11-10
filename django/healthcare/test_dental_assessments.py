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

    def test_dashboard_lists_own_followups_and_pending_budgets_only_for_author(self):
        from django.utils import timezone
        from .clinical import schedule_followup
        row=self.save(final=True)
        followup=schedule_followup(entry=row.treatment_plan.entry,user=self.doctor,due_at=timezone.localdate(),note='Retorno fictício')
        self.client.force_login(self.doctor)
        pending=self.client.get(reverse('dental-dashboard')).context['dental_pending']
        self.assertEqual(pending['followups'],[followup])
        self.assertEqual(pending['plans'],[row.treatment_plan])
        for user in (self.owner,self.reception):
            self.client.force_login(user)
            response=self.client.get(reverse('dental-dashboard'))
            self.assertEqual(response.status_code,200)
            pending=response.context['dental_pending']
            self.assertFalse(pending and (pending['followups'] or pending['plans']))

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

    def test_patient_demographics_are_encrypted_and_reused_only_with_clinical_access(self):
        row=self.save(patient_address='Endereço fictício confidencial',patient_gender='male',patient_coverage='Convênio fictício')
        self.assertNotIn('Endereço',row.payload_encrypted)
        payload=read_assessment(assessment=row,user=self.doctor)
        self.assertEqual(payload['patient']['gender_label'],'Masculino')
        self.client.force_login(self.doctor)
        response=self.client.get(reverse('dental-assessment-patient-options',args=[self.patient.pk]),{'professional':self.professional.pk})
        self.assertEqual(response.json()['patient']['address'],'Endereço fictício confidencial')
        self.client.force_login(self.reception)
        self.assertEqual(self.client.get(reverse('dental-assessment-patient-options',args=[self.patient.pk])).status_code,403)

    def test_new_visit_with_preselected_patient_starts_from_last_authorized_odontogram(self):
        self.save(final=True)
        self.client.force_login(self.doctor)
        response=self.client.get(reverse('dental-assessment-create'),{'customer':self.patient.pk})
        self.assertEqual(response.status_code,200)
        chart=json.loads(response.context['form']['odontogram_json'].value())
        self.assertEqual(chart['46'][0]['condition'],'carie')
        self.assertEqual(chart['46'][0]['surfaces'],['oclusal'])

    @skipUnless(connection.vendor=='postgresql','PostgreSQL ledger triggers')
    def test_postgresql_preserves_finalized_content_and_versions(self):
        row=self.save(final=True)
        with self.assertRaises(IntegrityError),transaction.atomic(),connection.cursor() as cursor:
            cursor.execute('UPDATE healthcare_dentalassessment SET payload_encrypted=%s WHERE id=%s',['tamper',row.pk])
        with self.assertRaises(IntegrityError),transaction.atomic(),connection.cursor() as cursor:
            cursor.execute('DELETE FROM healthcare_dentalassessmentversion WHERE assessment_id=%s',[row.pk])

    def test_minimal_draft_is_saved_and_redirects_to_patient_list(self):
        self.client.force_login(self.doctor)
        data=self.data(chief_complaint='',findings='',medical_history='',goals='[]',treatment_plan='[]',odontogram_json='{}',action='draft')
        response=self.client.post(reverse('dental-assessment-create'),data)
        self.assertEqual(response.status_code,302)
        self.assertIn(reverse('dental-assessments'),response['Location'])
        self.assertContains(self.client.get(response['Location']),self.patient.name)
        self.assertEqual(DentalAssessment.objects.get().status,'draft')

    def test_finalize_only_evolution_without_diagnosis_or_plan(self):
        row=self.save(final=True,chief_complaint='',findings='',medical_history='',goals='[]',treatment_plan='[]',initial_evolution='Paciente orientado após avaliação.')
        self.assertEqual(row.status,'finalized')
        self.assertIsNone(row.treatment_plan_id)
        self.client.force_login(self.doctor)
        self.assertEqual(self.client.get(reverse('dental-assessment-detail',args=[row.pk])).status_code,200)
        self.assertEqual(read_assessment(assessment=row,user=self.doctor)['sections']['initial_evolution'],'Paciente orientado após avaliação.')

    def test_reception_list_shows_scheduled_patient_and_professional_without_clinical_content(self):
        from django.utils import timezone
        from datetime import timedelta
        from scheduling.models import Customer
        self.appointment.starts_at=timezone.now()+timedelta(hours=1)
        self.appointment.ends_at=self.appointment.starts_at+timedelta(minutes=30)
        self.appointment.status='confirmed';self.appointment.save()
        row=self.save()
        Customer.objects.create(tenant=self.tenant,name='Paciente sem agendamento privado')
        from accounts.models import PlatformRole,Capability,RoleCapability,UserRole
        role=PlatformRole.objects.create(slug='dental-reception-list',name='Recepção')
        cap,_=Capability.objects.get_or_create(slug='agenda.manage',defaults={'name':'Agenda'})
        RoleCapability.objects.create(role=role,capability=cap);UserRole.objects.create(user=self.reception,role=role)
        self.client.force_login(self.reception)
        response=self.client.get(reverse('dental-assessments'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,self.patient.name)
        self.assertContains(response,self.professional.name)
        self.assertContains(response,'Rascunho salvo')
        self.assertNotContains(response,'Dor dentária confidencial')
        self.assertNotContains(response,'Paciente sem agendamento privado')
        self.assertNotContains(response,reverse('dental-assessment-detail',args=[row.pk]))
        self.assertIn(self.client.get(reverse('dental-assessment-detail',args=[row.pk])).status_code,{403,404})
        self.assertEqual(self.client.post(reverse('dental-assessments'),{}).status_code,403)

    def test_scheduled_cross_cover_is_read_only_and_expires_without_reassigning_original(self):
        from django.utils import timezone
        from datetime import timedelta
        from scheduling.models import Appointment
        from .models import ClinicalRegistration
        row=self.save(final=True)
        draft=self.save()
        ClinicalRegistration.objects.create(professional=self.colleague_profile,council='CRO',number='98765',jurisdiction='PE',professional_name='Dr. B')
        with self.assertRaises(PermissionDenied):read_assessment(assessment=row,user=self.colleague)
        visit=Appointment.objects.create(tenant=self.tenant,customer=self.patient,professional=self.colleague_profile,service=self.appointment.service,
            starts_at=timezone.now()+timedelta(hours=1),ends_at=timezone.now()+timedelta(hours=2),status='confirmed')
        self.assertEqual(read_assessment(assessment=row,user=self.colleague)['sections']['chief_complaint'],'Dor dentária confidencial')
        with self.assertRaises(PermissionDenied):read_assessment(assessment=draft,user=self.colleague)
        self.client.force_login(self.colleague)
        snapshot=self.client.get(reverse('clinical-offline-snapshot'))
        self.assertEqual(snapshot.status_code,200)
        self.assertNotIn(row.final_entry_id,[entry['id'] for entry in snapshot.json()['entries']])
        self.assertEqual(self.client.post(reverse('dental-assessment-detail',args=[row.pk]),{'action':'draft'}).status_code,403)
        for status in ('completed','cancelled','no_show'):
            visit.status=status;visit.save()
            with self.assertRaises(PermissionDenied):read_assessment(assessment=row,user=self.colleague)
        visit.status='confirmed';visit.starts_at=timezone.now()-timedelta(days=2);visit.ends_at=visit.starts_at+timedelta(hours=1);visit.save()
        with self.assertRaises(PermissionDenied):read_assessment(assessment=row,user=self.colleague)
        row.refresh_from_db()
        self.assertEqual(row.professional_id,self.professional.pk)
        self.assertEqual(row.created_by_id,self.doctor.pk)
        self.assertEqual(read_assessment(assessment=row,user=self.doctor)['professional']['user_id'],self.doctor.pk)

    def test_empty_clinical_information_can_be_draft_but_not_finalized(self):
        from .dental_assessment_forms import TEXT_FIELDS
        values={key:'' for key in TEXT_FIELDS}
        with self.assertRaises(ValidationError):self.save(final=True,**values)
        row=self.save(**values)
        self.assertEqual(row.status,'draft')

    def test_dental_design_has_one_theme_control_and_preserves_other_segment(self):
        from django.templatetags.static import static
        self.client.force_login(self.doctor)
        response=self.client.get(reverse('dental-assessments'))
        self.assertContains(response,static('healthcare/dental-design.css'),count=1)
        self.assertContains(response,'data-theme-toggle',count=1)
        self.assertContains(response,'aria-controls="pa-sidebar"')
        self.tenant.category='fisioterapia';self.tenant.save()
        response=self.client.get(reverse('physio-assessments'))
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,static('healthcare/dental-design.css'))

    def enable_finance(self):
        from billing.models import Module,TenantModule
        module,_=Module.objects.get_or_create(slug='finance',defaults={'name':'Financeiro'})
        TenantModule.objects.update_or_create(tenant=self.tenant,module=module,defaults={'enabled':True})

    def test_treatment_sales_report_uses_financial_values_without_clinical_content(self):
        from .clinical import change_treatment_status
        from finance.models import FinancialTransaction
        self.enable_finance();row=self.save(final=True)
        change_treatment_status(plan=row.treatment_plan,user=self.doctor,status='accepted',attestation=True)
        FinancialTransaction.objects.create(tenant=self.other,source_type='clinical-plan',source_id=row.treatment_plan_id,type='income',amount='9999',status='paid')
        self.client.force_login(self.owner)
        response=self.client.get(reverse('clinical-treatment-sales'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['totals']['amount'],180)
        self.assertEqual(response.context['totals']['count'],1)
        self.assertEqual(response.context['totals']['pending'],180)
        self.assertNotContains(response,'Dor dentária confidencial')
        self.assertNotContains(response,'Histórico confidencial')
        self.assertFalse(row.final_entry.access_log.filter(user=self.owner).exists())
        for user in (self.reception,self.doctor,self.master):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('clinical-treatment-sales')).status_code,403)

    def test_treatment_sales_period_excludes_following_month_and_rejects_foreign_dentist(self):
        from .clinical import change_treatment_status
        from finance.models import FinancialTransaction
        from scheduling.models import Professional
        from datetime import datetime
        from zoneinfo import ZoneInfo
        self.enable_finance();row=self.save(final=True)
        change_treatment_status(plan=row.treatment_plan,user=self.doctor,status='accepted',attestation=True)
        FinancialTransaction.objects.filter(tenant=self.tenant,source_type='clinical-plan').update(created_at=datetime(2026,12,1,tzinfo=ZoneInfo('America/Recife')))
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('clinical-treatment-sales'),{'month':11,'year':2026}).context['totals']['amount'],0)
        self.assertEqual(self.client.get(reverse('clinical-treatment-sales'),{'month':12,'year':2026}).context['totals']['amount'],180)
        other=Professional.objects.create(tenant=self.other,name='Outro dentista')
        response=self.client.get(reverse('clinical-treatment-sales'),{'professional':other.pk})
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(response.context['totals']['amount'],0)

    def test_reception_legacy_treatment_receipt_requires_open_cash_and_active_method(self):
        from tenants.models import Unit
        from .clinical import change_treatment_status
        from finance.models import FinancialTransaction
        from finance.clinic_models import ClinicPaymentMethod
        from finance import clinic_services as cash
        self.enable_finance()
        self.tenant.metadata={'clinical_reception_billing':True};self.tenant.save()
        unit=Unit.objects.create(tenant=self.tenant,name='Clínica',is_primary=True)
        self.professional.unit=unit;self.professional.save()
        row=self.save(final=True)
        change_treatment_status(plan=row.treatment_plan,user=self.doctor,status='accepted',attestation=True)
        tx=FinancialTransaction.objects.get(tenant=self.tenant,source_type='clinical-plan',source_id=row.treatment_plan_id)
        self.assertEqual(tx.unit_id,unit.pk)
        self.client.force_login(self.reception)
        url=reverse('clinical-finance')
        post={'action':'paid','transaction':tx.pk,'confirm':'yes','payment_method':'cash'}
        self.assertEqual(self.client.post(url,post).status_code,302)
        tx.refresh_from_db();self.assertEqual(tx.status,'pending')
        cash.open_clinic_cash(self.reception,unit,'0')
        method=ClinicPaymentMethod.objects.create(tenant=self.tenant,name='Dinheiro',kind='cash',active=False)
        self.client.post(url,post)
        tx.refresh_from_db();self.assertEqual(tx.status,'pending')
        method.active=True;method.save()
        self.assertEqual(self.client.post(url,post).status_code,302)
        tx.refresh_from_db();self.assertEqual(tx.status,'paid')
        closing=cash.close_clinic_cash(user=self.reception,unit=unit,amount='180')
        self.assertEqual(closing.expected_amount,180)
        self.assertEqual(self.client.post(url,post).status_code,302)
        self.assertEqual(FinancialTransaction.objects.filter(tenant=self.tenant,source_type='clinical-plan',status='paid').count(),1)
