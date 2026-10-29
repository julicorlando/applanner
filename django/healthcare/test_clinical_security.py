import json
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, RequestFactory
from accounts.models import User
from billing.models import Module, TenantModule
from scheduling.models import Customer, Professional
from tenants.models import Tenant
from .models import MedicalRecordEntry
from .services import create_record, read_record, clinical_records_for
from .dentistry import save_dental_encounter, dental_history
from .forms import DentalEncounterForm
from .views import dental_encounter, dental_patient


class ClinicalSecurityTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Clínica A",slug="clinical-security-a")
        self.other=Tenant.objects.create(name="Clínica B",slug="clinical-security-b")
        for slug in ("medical_records",):
            module,_=Module.objects.get_or_create(slug=slug,defaults={"name":slug})
            TenantModule.objects.create(tenant=self.tenant,module=module,enabled=True)
        self.doctor=User.objects.create_user(email="doctor-security@example.test",tenant=self.tenant,role="professional")
        self.colleague=User.objects.create_user(email="colleague-security@example.test",tenant=self.tenant,role="healthcare")
        self.professional=Professional.objects.create(tenant=self.tenant,user=self.doctor,name="Dra. A")
        self.colleague_profile=Professional.objects.create(tenant=self.tenant,user=self.colleague,name="Dr. B")
        module,_=Module.objects.get_or_create(slug="dentistry",defaults={"name":"Odontologia"})
        TenantModule.objects.create(tenant=self.tenant,module=module,enabled=True)
        self.patient=Customer.objects.create(tenant=self.tenant,name="Paciente fictício")
        self.reception=User.objects.create_user(email="reception-security@example.test",tenant=self.tenant,role="reception")
        self.master=User.objects.create_superuser(email="master-security@example.test",password="StrongTestPassword123!")
        self.owner=User.objects.create_user(email="admin-security@example.test",tenant=self.tenant,role="owner")
        self.entry=self.create()

    def create(self,**overrides):
        args=dict(tenant=self.tenant,customer=self.patient,professional=self.professional,
                  title="Avaliação",content="Informação clínica de teste",user=self.doctor)
        args.update(overrides)
        return create_record(**args)

    def test_reception_master_administrative_owner_cannot_read(self):
        for user in (self.reception,self.master,self.owner):
            with self.subTest(role=user.role),self.assertRaises(PermissionDenied):
                read_record(entry=self.entry,user=user)
        self.assertEqual(self.entry.access_log.count(),1)

    def test_other_clinician_has_no_automatic_care_link(self):
        with self.assertRaises(PermissionDenied):
            read_record(entry=self.entry,user=self.colleague)
        self.assertFalse(clinical_records_for(user=self.colleague,tenant=self.tenant).exists())

    def test_inactive_professional_is_denied(self):
        self.professional.active=False
        self.professional.save()
        with self.assertRaises(PermissionDenied):
            read_record(entry=self.entry,user=self.doctor)

    def test_cross_tenant_actor_cannot_create(self):
        outsider=User.objects.create_user(email="outsider-security@example.test",tenant=self.other,role="professional")
        Professional.objects.create(tenant=self.other,user=outsider,name="Outro profissional")
        with self.assertRaises(PermissionDenied):
            self.create(user=outsider)

    def test_cross_tenant_customer_cannot_be_injected(self):
        customer=Customer.objects.create(tenant=self.other,name="Paciente de outra clínica")
        with self.assertRaises(PermissionDenied):
            self.create(customer=customer)

    def test_cannot_impersonate_colleague(self):
        with self.assertRaises(PermissionDenied):
            self.create(professional=self.colleague_profile)

    def test_read_is_encrypted_and_audited(self):
        self.assertNotIn("Informação clínica",self.entry.content_encrypted)
        self.assertEqual(read_record(entry=self.entry,user=self.doctor),"Informação clínica de teste")
        self.assertEqual(self.entry.access_log.count(),2)

    def test_no_silent_overwrite_in_model_or_bulk_operations(self):
        self.entry.content_encrypted="tampered"
        with self.assertRaises(ValidationError):
            self.entry.save()
        with self.assertRaises(ValidationError):
            MedicalRecordEntry.objects.filter(pk=self.entry.pk).update(title="Alterado")
        with self.assertRaises(ValidationError):
            MedicalRecordEntry.objects.bulk_update([self.entry],["content_encrypted"])

    def test_rectification_preserves_original_and_encrypts_reason(self):
        revised=self.create(content="Informação corrigida",supersedes=self.entry,correction_reason="Correção do exame")
        self.assertEqual(revised.supersedes_id,self.entry.pk)
        self.assertNotIn("Correção",revised.correction_reason_encrypted)
        self.assertEqual(read_record(entry=self.entry,user=self.doctor),"Informação clínica de teste")
        self.assertEqual(read_record(entry=revised,user=self.doctor),"Informação corrigida")

    def test_rectification_requires_reason(self):
        with self.assertRaises(ValidationError):
            self.create(supersedes=self.entry)

    def test_rectification_cannot_move_patient(self):
        patient=Customer.objects.create(tenant=self.tenant,name="Outro paciente")
        with self.assertRaises(PermissionDenied):
            self.create(customer=patient,supersedes=self.entry,correction_reason="Inválida")

    def test_empty_content_and_invalid_type_rejected(self):
        for args in ({"content":""},{"record_type":"invalid"}):
            with self.subTest(args=args),self.assertRaises(ValidationError):
                self.create(**args)

    def test_dental_form_scopes_clinician_and_renders_chart(self):
        form=DentalEncounterForm(tenant=self.tenant,user=self.doctor)
        self.assertEqual(list(form.fields["professional"].queryset),[self.professional])
        request=RequestFactory().get('/app/odontologia/evolucao/nova/')
        request.user=self.doctor
        request.session={}
        response=dental_encounter(request)
        self.assertContains(response,'data-odontogram')
        self.assertContains(response,'healthcare/odontogram.')
        self.assertContains(response,'data-surface')

    def test_dental_history_is_scoped_to_clinician(self):
        save_dental_encounter(tenant=self.tenant,customer=self.patient,professional=self.professional,
            user=self.doctor,anamnesis="Anamnese",findings="Exame",procedures="Sessão",plan="Retorno",
            odontogram={"11":[{"condition":"carie","surfaces":["mesial"],"note":"Teste"}]})
        history=dental_history(tenant=self.tenant,customer=self.patient,user=self.doctor)
        self.assertEqual(len(history),1)
        self.assertEqual(json.loads(history[0]['chart_json'])['11'][0]['condition'],'carie')
        self.assertEqual(dental_history(tenant=self.tenant,customer=self.patient,user=self.colleague),[])

    def test_patient_route_rejects_idor(self):
        foreign=Customer.objects.create(tenant=self.other,name="Paciente externo")
        request=RequestFactory().get(f'/app/odontologia/paciente/{foreign.pk}/')
        request.user=self.doctor
        from django.http import Http404
        with self.assertRaises(Http404):
            dental_patient(request,foreign.pk)
