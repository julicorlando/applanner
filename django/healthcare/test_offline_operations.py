import json
import uuid
from datetime import timedelta, time
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from tenants.models import Tenant
from billing.models import Module, TenantModule
from scheduling.models import Customer, Professional, Appointment, Service, ProfessionalAvailability
from finance.models import FinancialTransaction
from core.crypto import decrypt_text
from core.models import AuditLog
from .models import ClinicalRegistration, MedicalRecordEntry, OfflineOperation
from .services import create_record
from .offline import scope


class OfflineOperationsTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Clínica Teste Offline', slug='offline-test', category='fisioterapia')
        self.other = Tenant.objects.create(name='Outra Clínica', slug='offline-other', category='fisioterapia')
        self.user = User.objects.create_user(email='offline@test.invalid', tenant=self.tenant, role='professional')
        self.profile = Professional.objects.create(tenant=self.tenant, user=self.user, name='Profissional Teste')
        ClinicalRegistration.objects.create(professional=self.profile, council='CREFITO', number='999999', jurisdiction='1')
        self.reception = User.objects.create_user(email='reception-offline@test.invalid', tenant=self.tenant, role='reception')
        self.patient = Customer.objects.create(tenant=self.tenant, name='Paciente Exemplo', phone='5581999999999')
        self.foreign = Customer.objects.create(tenant=self.other, name='Paciente Outra Clínica')
        self.service = Service.objects.create(tenant=self.tenant, name='Sessão Teste', duration_minutes=30, price=100)
        self.appointment = Appointment.objects.create(tenant=self.tenant, customer=self.patient, professional=self.profile, service=self.service,
            starts_at=timezone.now()-timedelta(hours=2), ends_at=timezone.now()-timedelta(hours=1), status='pending', service_price_snapshot=100)
        for slug in ['medical_records', 'finance']:
            module, _ = Module.objects.get_or_create(slug=slug, defaults={'name':slug, 'active':True})
            TenantModule.objects.create(tenant=self.tenant, module=module, enabled=True)
        self.client.force_login(self.user)

    def op(self, kind='evolution', **data):
        if kind=='evolution':
            data={'customer':self.patient.pk, 'content':'Melhora funcional. Dor 3/10.', 'occurred_at':timezone.now().isoformat(), 'attestation':True, **data}
        return {'id':str(uuid.uuid4()), 'scope':scope(self.user), 'kind':kind, 'data':data}

    def post(self, operation):
        return self.client.post(reverse('clinical-offline-sync'), json.dumps(operation), content_type='application/json')

    def test_shell_is_public_and_contains_no_patient_or_account_identity(self):
        self.client.logout()
        response=self.client.get(reverse('clinical-offline-shell'))
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response, self.patient.name)
        self.assertNotContains(response,self.user.email)
        self.assertNotContains(response,'csrfmiddlewaretoken')
        self.assertIn('public',response['Cache-Control'])
        self.assertEqual(self.client.get(reverse('clinical-offline-snapshot')).status_code,302)

    def test_reception_snapshot_has_no_clinical_history_and_cannot_evolve(self):
        entry=create_record(tenant=self.tenant, customer=self.patient, professional=self.profile, user=self.user, title='Privado',content='Segredo clínico')
        self.client.force_login(self.reception)
        response=self.client.get(reverse('clinical-offline-snapshot'))
        self.assertEqual(response.status_code,200)
        data=response.json()
        self.assertEqual(data['entries'],[])
        self.assertFalse(data['permissions']['clinical'])
        self.assertFalse(data['permissions']['cash'])
        self.assertNotIn(self.foreign.pk,[x['id'] for x in data['patients']])
        self.assertNotContains(response,'Segredo clínico')
        self.assertEqual(self.post({**self.op(), 'scope':scope(self.reception)}).status_code,403)
        self.assertEqual(MedicalRecordEntry.objects.count(),1)
        self.assertTrue(entry.content_encrypted)

    def test_only_authorized_history_is_downloaded_and_access_audited(self):
        own=create_record(tenant=self.tenant, customer=self.patient,professional=self.profile,user=self.user,title='Avaliação',content='Registro autorizado')
        colleague=User.objects.create_user(email='colleague-offline@test.invalid',tenant=self.tenant,role='professional')
        other_profile=Professional.objects.create(tenant=self.tenant,user=colleague,name='Colega')
        create_record(tenant=self.tenant,customer=self.patient,professional=other_profile,user=colleague,title='Outro',content='Restrito ao colega')
        response=self.client.get(reverse('clinical-offline-snapshot'))
        self.assertEqual([x['id'] for x in response.json()['entries']],[own.pk])
        self.assertContains(response,'Registro autorizado')
        self.assertNotContains(response,'Restrito ao colega')
        self.assertIn('no-store',response['Cache-Control'])
        self.assertTrue(AuditLog.objects.filter(action='clinical.offline.snapshot',user=self.user).exists())

    def test_evolution_is_encrypted_append_only_and_idempotent(self):
        operation=self.op(appointment=self.appointment.pk)
        one=self.post(operation);self.assertEqual(one.status_code,200,one.content)
        two=self.post(operation);self.assertEqual(two.json(),one.json())
        entry=MedicalRecordEntry.objects.get(pk=one.json()['result']['entry'])
        self.assertNotIn(operation['data']['content'],entry.content_encrypted)
        self.assertIn(operation['data']['content'],decrypt_text(entry.content_encrypted))
        self.assertEqual(entry.appointment_id,self.appointment.pk)
        self.assertEqual(OfflineOperation.objects.count(),1)
        changed={**operation,'data':{**operation['data'],'content':'Mudou'}}
        self.assertEqual(self.post(changed).status_code,409)
        self.assertEqual(MedicalRecordEntry.objects.count(),1)
        self.assertEqual(self.post(self.op()).status_code,200)
        self.assertEqual(MedicalRecordEntry.objects.count(),2)

    def test_cross_tenant_wrong_account_and_missing_attestation_are_denied(self):
        self.assertEqual(self.post(self.op(customer=self.foreign.pk)).status_code,404)
        self.assertEqual(self.post({**self.op(),'scope':f'{self.other.pk}:{self.user.pk}'}).status_code,403)
        self.assertEqual(self.post(self.op(attestation=False)).status_code,409)
        self.assertEqual(MedicalRecordEntry.objects.count(),0)

    def test_registration_must_match_the_clinical_segment(self):
        registration=self.profile.clinical_registration
        registration.council='CRO';registration.jurisdiction='PE';registration.save()
        self.assertEqual(self.post(self.op()).status_code,409)
        self.assertFalse(MedicalRecordEntry.objects.exists())

    def test_revocation_is_rechecked_before_replay(self):
        operation=self.op();self.assertEqual(self.post(operation).status_code,200)
        TenantModule.objects.filter(tenant=self.tenant,module__slug='medical_records').update(enabled=False)
        self.assertEqual(self.post(operation).status_code,403)
        self.assertEqual(self.client.get(reverse('clinical-offline-snapshot')).json()['entries'],[])

    def test_avulso_supports_missing_contacts_and_duplicate_contacts_require_review(self):
        operation=self.op('customer',name='Novo Paciente Avulso',phone='',email='',birth_date='2000-01-01')
        response=self.post(operation);self.assertEqual(response.status_code,200,response.content)
        patient=Customer.objects.get(pk=response.json()['result']['customer'])
        self.assertEqual(patient.phone,'')
        patient.full_clean()
        patient.name='Paciente avulso editado'
        patient.full_clean()
        patient.save()
        self.assertEqual(self.post(operation).json(),response.json())
        self.assertEqual(self.post(self.op('customer',name='Outro Nome',phone=self.patient.phone,email='')).status_code,409)
        self.assertEqual(self.post(self.op('customer',name='Inválido',phone='12',email='')).status_code,409)
        self.assertEqual(self.post(self.op('customer',name='Inválido',birth_date='2999-01-01')).status_code,409)

    def test_local_patient_reference_links_evolution_after_creation(self):
        operation=self.op('customer',name='Paciente Local',phone='',email='')
        response=self.post(operation)
        evolution=self.post(self.op(customer='local:'+operation['id']))
        self.assertEqual(evolution.status_code,200,evolution.content)
        self.assertEqual(MedicalRecordEntry.objects.get().customer_id,response.json()['result']['customer'])

    def test_checkin_conflict_keeps_existing_state_and_retry_does_not_duplicate(self):
        operation=self.op('checkin',appointment=self.appointment.pk,version=self.appointment.updated_at.isoformat(),occurred_at=timezone.now().isoformat())
        response=self.post(operation);self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(self.post(operation).status_code,200)
        self.appointment.refresh_from_db();self.assertEqual(self.appointment.status,'waiting')
        self.assertEqual(self.post({**operation,'id':str(uuid.uuid4())}).status_code,409)

    def test_cash_reuses_existing_settlement_and_never_approves_pix_offline(self):
        data=dict(appointment=self.appointment.pk,version=self.appointment.updated_at.isoformat(),amount='100.00',method='pix',occurred_at=timezone.now().isoformat())
        self.assertEqual(self.post(self.op('cash',**data)).status_code,409)
        operation=self.op('cash',**{**data,'method':'cash'})
        response=self.post(operation);self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(self.post(operation).status_code,200)
        self.assertEqual(FinancialTransaction.objects.filter(appointment=self.appointment).count(),1)
        self.assertEqual(FinancialTransaction.objects.get(appointment=self.appointment).payment_method,'cash')
        self.assertEqual(FinancialTransaction.objects.get(appointment=self.appointment).paid_at.isoformat(),operation['data']['occurred_at'])

    def test_cash_rejects_changed_price_and_unauthorized_reception(self):
        data=dict(appointment=self.appointment.pk,version=self.appointment.updated_at.isoformat(),amount='99.00',method='cash',occurred_at=timezone.now().isoformat())
        self.assertEqual(self.post(self.op('cash',**data)).status_code,409)
        self.client.force_login(self.reception)
        self.assertEqual(self.post({**self.op('cash',**data),'scope':scope(self.reception)}).status_code,403)
        self.assertFalse(FinancialTransaction.objects.exists())

    def test_booking_obeys_existing_availability_and_overlap_rules(self):
        start=(timezone.now()+timedelta(days=1)).replace(hour=12,minute=0,second=0,microsecond=0)
        ProfessionalAvailability.objects.create(tenant=self.tenant,professional=self.profile,weekday=start.isoweekday(),start_time=time(0),end_time=time(23,59))
        data=dict(customer=self.patient.pk,professional=self.profile.pk,service=self.service.pk,starts_at=start.isoformat())
        operation=self.op('appointment',**data)
        response=self.post(operation);self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(self.post(operation).status_code,200)
        self.assertEqual(self.post(self.op('appointment',**data)).status_code,409)
        self.assertEqual(Appointment.objects.filter(starts_at=start).count(),1)

    def test_invalid_payload_and_csrf_cannot_write(self):
        self.assertEqual(self.client.post(reverse('clinical-offline-sync'),'[]',content_type='application/json').status_code,403)
        self.assertEqual(self.client.post(reverse('clinical-offline-sync'),'{',content_type='application/json').status_code,400)
        client=Client(enforce_csrf_checks=True);client.force_login(self.user)
        self.assertEqual(client.post(reverse('clinical-offline-sync'),json.dumps(self.op()),content_type='application/json').status_code,403)
        response=client.get(reverse('clinical-offline-snapshot'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(client.post(reverse('clinical-offline-sync'),json.dumps(self.op()),content_type='application/json',HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value).status_code,200)

    def test_master_and_inactive_professional_cannot_download_clinical_copy(self):
        master=User.objects.create_user(email='offline-master@test.invalid',tenant=self.tenant,role='master',is_superuser=True)
        self.client.force_login(master)
        self.assertEqual(self.client.get(reverse('clinical-offline-snapshot')).status_code,403)
        self.client.force_login(self.user);self.profile.active=False;self.profile.save()
        self.assertEqual(self.client.get(reverse('clinical-offline-snapshot')).status_code,403)

    def test_reception_can_sync_patient_and_arrival_without_clinical_write(self):
        self.client.force_login(self.reception)
        operation={**self.op('customer',name='Paciente Recepção',phone='',email=''),'scope':scope(self.reception)}
        response=self.post(operation);self.assertEqual(response.status_code,200,response.content)
        operation={**self.op('checkin',appointment=self.appointment.pk,version=self.appointment.updated_at.isoformat(),occurred_at=timezone.now().isoformat()),'scope':scope(self.reception)}
        response=self.post(operation);self.assertEqual(response.status_code,200,response.content)
        self.assertFalse(MedicalRecordEntry.objects.exists())


from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from django.db import connection, connections
from django.test import TransactionTestCase
from django.core.exceptions import ValidationError
from .offline import replay


@skipUnless(connection.vendor=='postgresql','PostgreSQL row lock concurrency')
class OfflineReplayConcurrencyTests(TransactionTestCase):
    def test_concurrent_retries_create_one_patient_and_one_receipt(self):
        tenant=Tenant.objects.create(name='Concorrência offline',slug='offline-concurrency',category='fisioterapia')
        user=User.objects.create_user(email='concurrent-offline@test.invalid',tenant=tenant,role='owner')
        operation={'id':str(uuid.uuid4()),'scope':scope(user),'kind':'customer','data':{'name':'Paciente Concorrente','phone':'','email':''}}
        barrier=Barrier(2)
        def run(index):
            try:
                actor=User.objects.get(pk=user.pk)
                barrier.wait(timeout=10)
                return replay(actor,operation)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(run,[1,2]))
        self.assertEqual(results[0],results[1])
        self.assertEqual(Customer.objects.filter(tenant=tenant).count(),1)
        self.assertEqual(OfflineOperation.objects.filter(tenant=tenant).count(),1)

    def test_concurrent_contact_creation_cannot_merge_two_patients(self):
        tenant=Tenant.objects.create(name='Contatos offline',slug='offline-contact-race',category='fisioterapia')
        user=User.objects.create_user(email='contact-race@test.invalid',tenant=tenant,role='owner')
        barrier=Barrier(2)
        def run(index):
            try:
                actor=User.objects.get(pk=user.pk)
                operation={'id':str(uuid.uuid4()),'scope':scope(actor),'kind':'customer','data':{'name':f'Paciente {index}','phone':'81999999999','email':''}}
                barrier.wait(timeout=10)
                replay(actor,operation)
                return 'created'
            except ValidationError:
                return 'conflict'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(run,[1,2]))
        self.assertCountEqual(results,['created','conflict'])
        self.assertEqual(Customer.objects.filter(tenant=tenant).count(),1)
