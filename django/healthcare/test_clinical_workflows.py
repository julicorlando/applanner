import json
from io import BytesIO
from decimal import Decimal
from unittest import skipUnless
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import TestCase,RequestFactory
from django.db import connection,transaction,IntegrityError
from PIL import Image
from pypdf import PdfWriter
from . import test_clinical_security as fixtures
from .models import ClinicalRegistration,ClinicalTreatmentPlan,MedicalRecordEntry,ClinicalAttachment
from .services import read_record
from .clinical import (periodontal_chart,treatment_lines,save_structured_record,attach_document,read_document,
                       grant_care,revoke_care,change_treatment_status)
from . import clinic_views


class ClinicalWorkflowTests(TestCase):
    def setUp(self):
        fixtures.ClinicalSecurityTests.setUp(self)
        ClinicalRegistration.objects.create(professional=self.professional,council="CRO",number="12345",jurisdiction="PE")

    def create(self,**kwargs):return fixtures.ClinicalSecurityTests.create(self,**kwargs)

    def request(self,path='/',data=None,user=None):
        req=RequestFactory().post(path,data=data) if data is not None else RequestFactory().get(path)
        req.user=user or self.doctor;req.session={};req._messages=FallbackStorage(req)
        return req

    def test_registration_validates_council_and_snapshots_professional(self):
        row=self.professional.clinical_registration;row.full_clean()
        entry=self.create()
        self.assertEqual(entry.professional_snapshot["number"],"12345")
        row.number="54321";row.save()
        entry.refresh_from_db();self.assertEqual(entry.professional_snapshot["number"],"12345")
        row.jurisdiction="XX"
        with self.assertRaises(ValidationError):row.full_clean()

    def test_care_can_be_granted_and_revoked_by_responsible_clinician(self):
        grant=grant_care(entry=self.entry,grantee=self.colleague_profile,user=self.doctor,reason="Atendimento compartilhado autorizado")
        self.assertEqual(read_record(entry=self.entry,user=self.colleague),"Informação clínica de teste")
        with self.assertRaises(PermissionDenied):revoke_care(grant=grant,user=self.colleague)
        revoke_care(grant=grant,user=self.doctor)
        with self.assertRaises(PermissionDenied):read_record(entry=self.entry,user=self.colleague)

    def test_platform_master_cannot_grant_access(self):
        with self.assertRaises(PermissionDenied):grant_care(entry=self.entry,grantee=self.colleague_profile,user=self.master,reason="Admin")

    def test_periodontogram_accepts_measurements_and_rejects_invalid_data(self):
        chart={"11":{"mobility":1,"sites":{"MV":{"probing":3.5,"recession":1,"bleeding":True}}}}
        self.assertEqual(periodontal_chart(chart)["11"]["sites"]["MV"]["probing"],3.5)
        for invalid in ({},{"99":{}},{"11":{"mobility":True}},{"11":{"sites":{"MV":{"probing":99}}}}):
            with self.subTest(invalid=invalid),self.assertRaises(ValidationError):periodontal_chart(invalid)

    def test_treatment_totals_use_decimal_and_validate_fdi(self):
        lines,total=treatment_lines([{"tooth":"11","procedure":"Procedimento fictício","quantity":3,"price":"0.10"}])
        self.assertEqual(total,Decimal("0.30"));self.assertEqual(lines[0]["tooth"],"11")
        for price in ("NaN","Infinity","-1"):
            with self.assertRaises(ValidationError):treatment_lines([{"procedure":"Teste","price":price}])

    def plan(self):
        entry=save_structured_record(tenant=self.tenant,customer=self.patient,professional=self.professional,user=self.doctor,
            kind="treatment_plan",title="Plano fictício",data={"lines":[{"tooth":"11","procedure":"Restaurar","quantity":2,"price":"35.50"}]})
        return ClinicalTreatmentPlan.objects.get(entry=entry)

    def test_budget_acceptance_creates_one_finance_charge_and_clinical_history(self):
        from finance.models import FinancialTransaction
        plan=self.plan()
        with self.assertRaises(ValidationError):change_treatment_status(plan=plan,user=self.doctor,status="accepted")
        change_treatment_status(plan=plan,user=self.doctor,status="accepted",attestation=True)
        change_treatment_status(plan=plan,user=self.doctor,status="accepted",attestation=True)
        charge=FinancialTransaction.objects.get(source_type="clinical-plan",source_id=plan.pk)
        self.assertEqual(charge.amount,Decimal("71.00"));self.assertNotIn("Restaurar",charge.description)
        self.assertTrue(MedicalRecordEntry.objects.filter(title="Andamento do plano de tratamento").exists())
        change_treatment_status(plan=plan,user=self.doctor,status="in_progress")
        change_treatment_status(plan=plan,user=self.doctor,status="completed")
        self.assertEqual(FinancialTransaction.objects.filter(source_type="clinical-plan").count(),1)

    def test_image_is_private_encrypted_and_preserves_diagnostic_source(self):
        output=BytesIO();Image.new('RGB',(60,40),(255,0,0)).save(output,'PNG')
        doc=attach_document(entry=self.entry,user=self.doctor,upload=SimpleUploadedFile("foto.png",output.getvalue()),kind="image")
        self.assertNotIn(output.getvalue(),bytes(doc.content_encrypted))
        raw,name=read_document(document=doc,user=self.doctor)
        self.assertEqual(raw,output.getvalue());self.assertTrue(name.endswith('.png'))
        with self.assertRaises(PermissionDenied):read_document(document=doc,user=self.reception)
        with self.assertRaises(ValidationError):doc.save()

    def test_pdf_validation_rejects_active_content_and_requires_consent_attestation(self):
        writer=PdfWriter();writer.add_blank_page(width=100,height=100);stream=BytesIO();writer.write(stream)
        with self.assertRaises(ValidationError):attach_document(entry=self.entry,user=self.doctor,upload=SimpleUploadedFile('termo.pdf',stream.getvalue()),kind='consent')
        doc=attach_document(entry=self.entry,user=self.doctor,upload=SimpleUploadedFile('termo.pdf',stream.getvalue()),kind='consent',attestation=True)
        self.assertEqual(doc.mime_type,'application/pdf')
        writer.add_js("app.alert('blocked')");active=BytesIO();writer.write(active)
        with self.assertRaises(ValidationError):attach_document(entry=self.entry,user=self.doctor,upload=SimpleUploadedFile('ativo.pdf',active.getvalue()),kind='document')
        with self.assertRaises(ValidationError):attach_document(entry=self.entry,user=self.doctor,upload=SimpleUploadedFile('x.html',b'<script>1</script>'),kind='document')

    def test_clinical_pages_render_and_reception_is_denied(self):
        for view,args in ((clinic_views.dashboard,()),(clinic_views.patient,(self.patient.pk,)),(clinic_views.record_detail,(self.entry.pk,)),(clinic_views.structured_record,("periodontal",))):
            with self.subTest(view=view.__name__):
                self.assertEqual(view(self.request(),*args).status_code,200)
                with self.assertRaises(PermissionDenied):view(self.request(user=self.reception),*args)

    def test_rectification_ui_preserves_original(self):
        response=clinic_views.record_detail(self.request(data={"action":"correct","reason":"Correção do exame","correction":"Complemento fictício"}),self.entry.pk)
        self.assertEqual(response.status_code,302)
        revised=MedicalRecordEntry.objects.get(supersedes=self.entry)
        self.assertEqual(json.loads(read_record(entry=revised,user=self.doctor))["correction"],"Complemento fictício")
        self.assertEqual(read_record(entry=self.entry,user=self.doctor),"Informação clínica de teste")

    def test_patient_json_and_pdf_exports_are_scoped_and_audited(self):
        response=clinic_views.export_patient(self.request(),self.patient.pk,"json")
        payload=json.loads(response.content);self.assertEqual(len(payload["records"]),1)
        response=clinic_views.export_patient(self.request(),self.patient.pk,"pdf")
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))
        self.assertEqual(self.entry.access_log.filter(action="export").count(),2)
        with self.assertRaises(PermissionDenied):clinic_views.export_patient(self.request(user=self.master),self.patient.pk,"pdf")

    @skipUnless(connection.vendor=="postgresql","PostgreSQL immutability guard")
    def test_database_protects_clinical_content(self):
        with self.assertRaises(IntegrityError),transaction.atomic():
            MedicalRecordEntry._base_manager.filter(pk=self.entry.pk).update(title="Tampered")

    def test_dental_chart_endpoint_does_not_leak_other_clinics(self):
        from .views import dental_chart
        from scheduling.models import Customer
        from django.http import Http404
        foreign=Customer.objects.create(tenant=self.other,name="Outro paciente")
        with self.assertRaises(Http404):dental_chart(self.request(),foreign.pk)

    def test_attachment_endpoint_requires_clinical_authorization(self):
        doc=ClinicalAttachment.objects.create(entry=self.entry,kind="document",filename_encrypted="cipher",content_encrypted=b"cipher",mime_type="application/pdf",sha256="a"*64,size=10,uploaded_by=self.doctor)
        with self.assertRaises(PermissionDenied):clinic_views.attachment_download(self.request(user=self.reception),doc.pk)

    def test_reassigning_professional_login_does_not_transfer_prior_records(self):
        from accounts.models import User
        newcomer=User.objects.create_user(email="new-clinician@example.test",tenant=self.tenant,role="professional")
        self.professional.user=newcomer;self.professional.save()
        with self.assertRaises(PermissionDenied):read_record(entry=self.entry,user=newcomer)

    def test_session_credit_is_consumed_once_and_patient_must_match(self):
        from datetime import timedelta
        from django.utils import timezone
        from engagement.models import ServicePackage,PackageItem,CustomerPackage
        from scheduling.models import Service,Appointment
        from .clinical import consume_clinical_session
        service=Service.objects.create(tenant=self.tenant,name="Sessão fictícia",duration_minutes=30,price=30)
        package=ServicePackage.objects.create(tenant=self.tenant,name="Pacote fictício",price=60)
        PackageItem.objects.create(package=package,service=service,credits=2)
        bought=CustomerPackage.objects.create(tenant=self.tenant,customer=self.patient,package=package,purchased_at=timezone.now(),purchase_amount=60)
        start=timezone.now()+timedelta(days=1)
        appointment=Appointment.objects.create(tenant=self.tenant,customer=self.patient,professional=self.professional,service=service,starts_at=start,ends_at=start+timedelta(minutes=30),status="completed")
        entry=self.create(appointment=appointment,record_type="physio_evolution")
        first=consume_clinical_session(entry=entry,customer_package=bought,user=self.doctor)
        second=consume_clinical_session(entry=entry,customer_package=bought,user=self.doctor)
        self.assertEqual(first.pk,second.pk);self.assertEqual(bought.usages.count(),1)

    def test_reception_financial_access_does_not_grant_clinical_access(self):
        from .finance_views import clinical_finance
        with self.assertRaises(PermissionDenied):clinical_finance(self.request(user=self.reception))
        self.tenant.metadata={"clinical_reception_billing":True};self.tenant.save()
        self.reception.refresh_from_db()
        self.assertEqual(clinical_finance(self.request(user=self.reception)).status_code,200)
        with self.assertRaises(PermissionDenied):read_record(entry=self.entry,user=self.reception)


class HomologationSmokeTests(TestCase):
    def test_refuses_production_and_seeds_idempotent_non_login_fixtures(self):
        from django.core.management import call_command,CommandError
        from django.test import override_settings
        from accounts.models import User
        with override_settings(DEPLOYMENT_ENVIRONMENT="production"),self.assertRaises(CommandError):
            call_command("clinical_homologation_smoke",stdout=BytesIO())
        from io import StringIO
        with override_settings(DEPLOYMENT_ENVIRONMENT="homologacao",SUBSCRIPTION_ACCESS_ENFORCED=True):
            from billing.models import Module
            call_command("seed_modules",preserve_existing=True,stdout=StringIO())
            Module.objects.filter(slug="medical_records").update(active=False)
            output=StringIO();call_command("clinical_homologation_smoke",stdout=output)
            self.assertTrue(Module.objects.get(slug="medical_records").active)
            self.assertEqual(json.loads(output.getvalue())["status"],"passed")
            for slug in ("homolog-odontologia","homolog-fisioterapia"):
                response=self.client.get("/p/"+slug+"/")
                self.assertEqual(response.status_code,200)
                self.assertContains(response,"Atendimento fictício")
                self.assertContains(response,"Profissional fictício")
                from tenants.models import Tenant
                from scheduling.models import Service,Appointment
                from django.utils import timezone
                from datetime import timedelta
                tenant=Tenant.objects.get(public_slug=slug)
                service=Service.objects.get(tenant=tenant)
                self.client.defaults["REMOTE_ADDR"]="192.0.2.234"
                availability=self.client.get("/api/public/"+slug+"/availability/",{"service_id":service.pk,"date":(timezone.localdate()+timedelta(days=1)).isoformat()})
                self.assertEqual(availability.status_code,200)
                self.assertTrue(availability.json()["slots"])
                result=self.client.post("/api/public/"+slug+"/book/",{"service_id":service.pk,"starts_at":availability.json()["slots"][0]["value"],"name":"Paciente fictício de agendamento","phone":"81900000000"},content_type="application/json")
                self.assertEqual(result.status_code,201)
                self.assertEqual(Appointment.objects.get(pk=result.json()["id"]).professional.user.tenant_id,tenant.pk)
            count=MedicalRecordEntry.objects.count()
            call_command("clinical_homologation_smoke",stdout=StringIO())
            self.assertEqual(MedicalRecordEntry.objects.count(),count)
            self.assertTrue(all(not user.has_usable_password() for user in User.objects.filter(email__endswith="@homolog.invalid")))


class ClinicalRollbackSchemaTests(TestCase):
    setUp=ClinicalWorkflowTests.setUp
    create=ClinicalWorkflowTests.create
    def test_previous_release_can_insert_without_new_columns(self):
        columns='tenant_id,customer_id,professional_id,record_type,title,content_encrypted,created_by_id,created_at'
        with connection.cursor() as cursor:
            cursor.execute(f'INSERT INTO healthcare_medicalrecordentry ({columns}) SELECT {columns} FROM healthcare_medicalrecordentry WHERE id=%s RETURNING id',[self.entry.pk])
            pk=cursor.fetchone()[0]
        row=MedicalRecordEntry.objects.get(pk=pk)
        self.assertEqual(row.professional_snapshot,{})
        self.assertEqual(row.correction_reason_encrypted,'')
        self.assertEqual(read_record(entry=row,user=self.doctor),read_record(entry=self.entry,user=self.doctor))
        with self.assertRaises(PermissionDenied):read_record(entry=row,user=self.colleague)
