from datetime import date
from decimal import Decimal
from io import BytesIO
import uuid
from django.test import TestCase,Client
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import connection,IntegrityError,transaction
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from accounts.models import User
from billing.models import Module,TenantModule
from tenants.models import Tenant,Unit
from scheduling.models import Customer
from .models import CashSession,FinancialTransaction
from .clinic_models import ClinicPaymentMethod,ClinicCharge,ClinicReceipt,ClinicCashClosing
from .clinic_forms import ExpenseForm
from . import clinic_services as s


class ClinicDeskTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name='Clínica teste',slug='clinic-cash-test',category='odontologia')
        self.unit=Unit.objects.create(tenant=self.tenant,name='Unidade',is_primary=True)
        self.owner=User.objects.create_user(email='cash-owner@test.invalid',tenant=self.tenant,role='owner')
        self.reception=User.objects.create_user(email='cash-reception@test.invalid',tenant=self.tenant,role='reception')
        self.patient=Customer.objects.create(tenant=self.tenant,name='Paciente Teste',phone='5581999999999')
        module,_=Module.objects.get_or_create(slug='finance',defaults={'name':'Financeiro','active':True})
        TenantModule.objects.create(tenant=self.tenant,module=module,enabled=True)
        self.cash=ClinicPaymentMethod.objects.create(tenant=self.tenant,name='Dinheiro',kind='cash')
        self.pix=ClinicPaymentMethod.objects.create(tenant=self.tenant,name='Pix',kind='pix')
        self.card=ClinicPaymentMethod.objects.create(tenant=self.tenant,name='Cartão',kind='card')
        self.client.force_login(self.reception)

    def charge(self,**kw):
        return s.create_charge(user=self.reception,unit=self.unit,customer=self.patient,description='Cobrança administrativa',
            amount=kw.pop('amount','100.00'),count=kw.pop('count',1),first_due=kw.pop('first_due',date(2026,1,31)),request_id=kw.pop('request_id',uuid.uuid4()),**kw)

    def receive(self,row,amount,method=None,key=None):
        return s.receive(user=self.reception,unit=self.unit,installment=row,amount=amount,method=method or self.cash,request_id=key or uuid.uuid4())

    def test_installment_cents_and_month_end_are_exact_and_idempotent(self):
        key=uuid.uuid4();charge=self.charge(amount='100',count=3,request_id=key)
        values=list(charge.installments.order_by('number').values_list('amount',flat=True))
        self.assertEqual(values,[Decimal('33.34'),Decimal('33.33'),Decimal('33.33')])
        self.assertEqual(list(charge.installments.order_by('number').values_list('due_at',flat=True)),[date(2026,1,31),date(2026,2,28),date(2026,3,31)])
        self.assertEqual(self.charge(amount='100',count=3,request_id=key).pk,charge.pk)
        with self.assertRaises(ValidationError):self.charge(amount='101',count=3,request_id=key)
        self.assertEqual(FinancialTransaction.objects.filter(tenant=self.tenant).count(),3)

    def test_partial_and_mixed_receipts_close_cash_without_double_revenue(self):
        session=s.open_clinic_cash(self.reception,self.unit,'50')
        row=self.charge().installments.get();key=uuid.uuid4()
        receipt=self.receive(row,'30',key=key)
        self.assertEqual(self.receive(row,'30',key=key).pk,receipt.pk)
        self.assertEqual(row.remaining,Decimal('70'))
        with self.assertRaises(ValidationError):self.receive(row,'71')
        self.receive(row,'70',self.pix)
        self.assertEqual(row.remaining,0)
        self.assertEqual(FinancialTransaction.objects.filter(status='paid',type='income').count(),2)
        expense=s.expense(user=self.reception,unit=self.unit,description='Material',amount='10',method=self.cash,invoice='NF 123',items='1 pacote',image=None,request_id=uuid.uuid4())
        self.assertEqual(expense.transaction.type,'expense')
        closed=s.close_clinic_cash(user=self.reception,unit=self.unit,amount='70',notes='Conferido')
        self.assertEqual(closed.expected_amount,Decimal('70'))
        self.assertEqual(closed.difference_amount,0)
        report=ClinicCashClosing.objects.get(session=session).summary
        self.assertEqual(report['charged'],'100.00');self.assertEqual(report['received'],'100.00')
        self.assertEqual(report['expenses'],'10.00');self.assertEqual(report['net'],'90.00')
        # Closed report stays frozen when a later session receives another charge.
        s.open_clinic_cash(self.reception,self.unit,'0')
        self.receive(self.charge(amount='20').installments.get(),'20',self.card)
        self.assertEqual(ClinicCashClosing.objects.get(session=session).summary,report)

    def test_receiving_old_charge_is_not_new_charge_today(self):
        charge=self.charge(amount='150')
        ClinicCharge.objects.filter(pk=charge.pk).update(created_at=timezone.now()-timezone.timedelta(days=2))
        s.open_clinic_cash(self.reception,self.unit,'0');self.receive(charge.installments.get(),'50',self.pix)
        start,end=s.day_bounds(self.tenant,timezone.localdate());summary=s.period_summary(self.tenant,self.unit,start,end)
        self.assertEqual(Decimal(summary['charged']),0);self.assertEqual(Decimal(summary['received']),50)
        self.assertEqual(Decimal(summary['pending']),100)

    def test_receipts_and_expenses_require_open_cash_and_do_not_accept_invalid_values(self):
        row=self.charge().installments.get()
        with self.assertRaises(ValidationError):self.receive(row,'10')
        s.open_clinic_cash(self.reception,self.unit,0)
        for value in ['NaN','Infinity','-1','1.001','0','99999999999']:
            with self.assertRaises(ValidationError):self.receive(row,value)
        with self.assertRaises(ValidationError):s.expense(user=self.reception,unit=self.unit,description='Despesa',amount='1',method=self.cash,invoice='',items='',image=None,request_id=uuid.uuid4())
        self.assertEqual(ClinicReceipt.objects.count(),0)

    def test_reception_can_operate_but_cannot_read_clinical_records_or_other_finances(self):
        response=self.client.get(reverse('clinic-finance-desk'));self.assertEqual(response.status_code,200)
        self.assertContains(response,'Valor cobrado no dia');self.assertContains(response,'Valor recebido no dia')
        self.assertEqual(self.client.get(reverse('clinical-dashboard')).status_code,403)
        self.assertEqual(self.client.get(reverse('finance-commissions')).status_code,403)
        self.assertEqual(self.client.get(reverse('clinic-birthday-settings')).status_code,403)
        response=self.client.post(reverse('clinic-finance-desk'),{'action':'open','amount':'20'})
        self.assertEqual(response.status_code,302);self.assertTrue(CashSession.objects.filter(status='open').exists())
        self.tenant.metadata={'clinical_reception_billing':False};self.tenant.save()
        self.assertEqual(self.client.get(reverse('clinic-finance-desk')).status_code,403)

    def test_direct_url_cross_tenant_unit_and_disabled_method_are_rejected(self):
        other=Tenant.objects.create(name='Outra',slug='clinic-other',category='odontologia')
        other_unit=Unit.objects.create(tenant=other,name='Outra unidade')
        with self.assertRaises(PermissionDenied):s.open_clinic_cash(self.reception,other_unit,0)
        s.open_clinic_cash(self.reception,self.unit,0);row=self.charge().installments.get()
        self.pix.active=False;self.pix.save()
        with self.assertRaises(PermissionDenied):self.receive(row,'10',self.pix)
        self.assertEqual(self.client.get(reverse('clinic-finance-desk')+'?unit='+str(other_unit.pk)).status_code,404)
        clinician=User.objects.create_user(email='cash-doctor@test.invalid',tenant=self.tenant,role='professional')
        self.client.force_login(clinician)
        self.assertEqual(self.client.get(reverse('clinic-finance-desk')).status_code,403)

    def test_expense_photo_validated_encrypted_and_protected(self):
        image=BytesIO();Image.new('RGB',(40,40),'blue').save(image,'PNG')
        data={'request_id':str(uuid.uuid4()),'amount':'10','method':self.pix.pk,'confirmed':'on','description':'Compra','invoice':'123','items':'Luva'}
        form=ExpenseForm(data,{'photo':SimpleUploadedFile('nota.png',image.getvalue())},tenant=self.tenant)
        self.assertTrue(form.is_valid(),form.errors)
        encrypted,mime=form.cleaned_data['photo'];self.assertNotIn(image.getvalue(),encrypted)
        s.open_clinic_cash(self.reception,self.unit,0)
        row=s.expense(user=self.reception,unit=self.unit,description='Compra',amount='10',method=self.pix,invoice='123',items='Luva',image=(encrypted,mime),request_id=uuid.uuid4())
        response=self.client.get(reverse('clinic-finance-photo',args=[row.pk]))
        self.assertEqual(response.status_code,200);self.assertEqual(response['Content-Type'],'image/jpeg')
        self.assertIn('no-store',response['Cache-Control'])
        bad=ExpenseForm(data,{'photo':SimpleUploadedFile('nota.png',b'<svg onload=alert(1)>')},tenant=self.tenant)
        self.assertFalse(bad.is_valid())
        self.client.logout();self.assertEqual(self.client.get(reverse('clinic-finance-photo',args=[row.pk])).status_code,302)

    def test_patient_cpf_and_address_are_encrypted_and_duplicate_cpf_rejected(self):
        self.patient.cpf='529.982.247-25';self.patient.street='Rua Particular';self.patient.city='Carpina';self.patient.save()
        self.patient.refresh_from_db();self.assertEqual(self.patient.cpf,'52998224725')
        self.assertEqual(self.patient.street,'Rua Particular')
        with connection.cursor() as cursor:
            cursor.execute('SELECT cpf,street FROM scheduling_customer WHERE id=%s',[self.patient.pk]);raw=cursor.fetchone()
        self.assertNotIn('52998224725',raw[0]);self.assertNotIn('Rua Particular',raw[1])
        with self.assertRaises(ValidationError):Customer.objects.create(tenant=self.tenant,name='Inválido',cpf='11111111111')
        with self.assertRaises(IntegrityError),transaction.atomic():Customer.objects.create(tenant=self.tenant,name='Duplicado',cpf='52998224725')
        other=Tenant.objects.create(name='Outra CPF',slug='other-cpf',category='odontologia')
        self.assertTrue(Customer.objects.create(tenant=other,name='Outro cadastro',cpf='52998224725').pk)

    def test_csrf_protects_money_writes(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.reception)
        self.assertEqual(client.post(reverse('clinic-finance-desk'),{'action':'open','amount':'100'}).status_code,403)

    def test_patient_form_reception_can_create_and_edit_cpf_address(self):
        url=reverse('portal-resource-create',args=['agenda','clientes'])
        data={'name':'Paciente Administrativo','phone':'5581888888888','email':'patient@example.invalid','birth_date':'1990-02-15',
            'cpf':'529.982.247-25','postal_code':'55815-000','street':'Rua Particular','address_number':'20','district':'Centro','city':'Carpina','state':'PE','active':'on','consent_marketing':'on'}
        response=self.client.post(url,data);self.assertEqual(response.status_code,302,response.content[:200])
        patient=Customer.objects.get(tenant=self.tenant,name='Paciente Administrativo')
        self.assertEqual(patient.cpf,'52998224725');self.assertEqual(patient.street,'Rua Particular');self.assertTrue(patient.consent_marketing)
        data['street']='Rua Atualizada'
        response=self.client.post(reverse('portal-resource-edit',args=['agenda','clientes',patient.pk]),data)
        self.assertEqual(response.status_code,302,response.content[:200]);patient.refresh_from_db();self.assertEqual(patient.street,'Rua Atualizada')
        from core.audit import model_snapshot
        snapshot=model_snapshot(patient);self.assertNotIn('cpf',snapshot);self.assertNotIn('street',snapshot)

    def test_explicit_reception_role_links_and_repeated_expense_are_safe(self):
        from accounts.models import PlatformRole,UserRole
        role=PlatformRole.objects.create(name='Recepção clínica caixa',slug='clinic-cash-reception')
        UserRole.objects.create(user=self.reception,role=role)
        self.assertEqual(self.client.get(reverse('clinic-finance-desk')).status_code,200)
        self.assertEqual(self.client.post(reverse('clinic-finance-desk'),{'action':'open','amount':'10','notes':'Fundo conferido'}).status_code,302)
        session=CashSession.objects.get(tenant=self.tenant);self.assertEqual(session.notes,'Fundo conferido')
        key=uuid.uuid4();data=dict(user=self.reception,unit=self.unit,description='Compra',amount='5',method=self.cash,invoice='1',items='2 itens',image=None,request_id=key)
        first=s.expense(**data);self.assertEqual(s.expense(**data).pk,first.pk)
        with self.assertRaises(ValidationError):s.expense(**{**data,'amount':'6'})
        self.assertEqual(FinancialTransaction.objects.filter(source_type='clinic-expense').count(),1)

    def test_arrival_is_idempotent_and_daily_counts_are_visible(self):
        from scheduling.models import Appointment,Professional,Service
        professional=Professional.objects.create(tenant=self.tenant,name='Dentista teste',unit=self.unit)
        service=Service.objects.create(tenant=self.tenant,name='Consulta',price=100,duration_minutes=30)
        now=timezone.now()
        appointment=Appointment.objects.create(tenant=self.tenant,unit=self.unit,customer=self.patient,professional=professional,service=service,
            starts_at=now,ends_at=now+timezone.timedelta(minutes=30),status='confirmed')
        url=reverse('clinic-finance-desk')
        self.assertEqual(self.client.post(url,{'action':'arrived','appointment':appointment.pk}).status_code,302)
        self.assertEqual(self.client.post(url,{'action':'arrived','appointment':appointment.pk}).status_code,302)
        appointment.refresh_from_db();self.assertEqual(appointment.status,'waiting')
        response=self.client.get(url);self.assertEqual(response.context['waiting_count'],1)
        self.assertEqual(response.context['completed_count'],0)
        appointment.status='completed';appointment.save()
        response=self.client.get(url);self.assertEqual(response.context['completed_count'],1)

    def test_patient_payment_plan_report_shows_charged_received_balance(self):
        charge=self.charge(amount='200',count=2)
        s.open_clinic_cash(self.reception,self.unit,0)
        self.receive(charge.installments.get(number=1),'40',self.pix)
        response=self.client.get(reverse('clinic-finance-desk'))
        self.assertEqual(response.status_code,200)
        item=list(response.context['charges'])[0]
        self.assertEqual(item.amount,Decimal('200'));self.assertEqual(item.received_total,Decimal('40'))
        self.assertEqual(item.balance,Decimal('160'))
        self.assertContains(response,'Valores por paciente e plano de pagamento')
