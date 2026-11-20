import uuid
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.http import HttpResponse
from django.db.models import Sum,F,Value,DecimalField
from django.db.models.functions import Coalesce
from decimal import Decimal
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from cryptography.fernet import Fernet
from core.audit import append_audit
from core.unit_scope import selected_unit
from .models import CashSession,FinancialTransaction
from scheduling.models import Appointment
from .clinic_models import ClinicPaymentMethod,ClinicInstallment,ClinicCharge,ClinicExpense,ClinicCashClosing
from .clinic_forms import ChargeForm,ReceiptForm,ExpenseForm
from . import clinic_services as services
from .advanced_services import cash_balance


class PaymentForm(forms.ModelForm):
    class Meta:
        model=ClinicPaymentMethod
        fields=['name','kind']
        labels={'name':'Nome da modalidade','kind':'Tipo de pagamento'}


class CashForm(forms.Form):
    amount=forms.DecimalField(label='Valor em dinheiro (R$)',max_digits=12,decimal_places=2,min_value=0,initial=0)
    notes=forms.CharField(label='Observações',max_length=500,required=False,widget=forms.Textarea(attrs={'rows':2}))


@login_required
@never_cache
def desk(request):
    tenant=services.access(request.user);unit=selected_unit(request,tenant)
    for kind,name in [('cash','Dinheiro'),('pix','Pix'),('card','Cartão')]:
        # Initial catalog only. Never re-enable methods disabled by the clinic.
        if not ClinicPaymentMethod.objects.filter(tenant=tenant,kind=kind).exists():
            ClinicPaymentMethod.objects.get_or_create(tenant=tenant,name=name,defaults={'kind':kind})
    if request.method=='POST' and request.POST.get('action') in {'method','toggle-method'} and request.user.role not in {'owner','tenant-admin','manager'}:
        raise PermissionDenied('Somente a gestão pode configurar modalidades de pagamento.')
    action=request.POST.get('action') if request.method=='POST' else ''
    initial={'request_id':uuid.uuid4()}
    charge_form=ChargeForm(request.POST if action=='charge' else None,tenant=tenant,initial=initial,auto_id='charge_%s')
    expense_form=ExpenseForm(request.POST if action=='expense' else None,request.FILES if action=='expense' else None,tenant=tenant,initial={'request_id':uuid.uuid4()},auto_id='expense_%s')
    payment_form=PaymentForm(request.POST if action=='method' else None,auto_id='method_%s')
    cash_form=CashForm(request.POST if action in {'open','close'} else None,auto_id='cash_%s')
    if request.method=='POST':
        try:
            if action=='review-expense':
                pk=request.POST.get('expense','')
                if not pk.isdigit():raise ValidationError('Despesa inválida.')
                get_object_or_404(ClinicExpense,pk=pk,session__tenant=tenant,session__unit=unit)
                services.review_expense(user=request.user,unit=unit,pk=pk,status=request.POST.get('decision'),note=request.POST.get('note',''))
            elif action=='arrived':
                from django.db import transaction
                pk=request.POST.get('appointment','')
                if not pk.isdigit():raise ValidationError('Atendimento inválido.')
                with transaction.atomic():
                    appointment=get_object_or_404(Appointment.objects.select_for_update(),pk=pk,tenant=tenant,unit=unit)
                    start,end=services.day_bounds(tenant,timezone.localdate())
                    if not start<=appointment.starts_at<=end:raise ValidationError('Registre chegada somente nos atendimentos de hoje.')
                    if appointment.status in {'pending','confirmed'}:
                        appointment.status='waiting';appointment.save(update_fields=['status','updated_at'])
                        append_audit(tenant=tenant,user=request.user,request=request,action='clinic.patient.arrived',entity_type='Appointment',entity_id=appointment.pk)
                    elif appointment.status not in {'waiting','in_progress','completed'}:raise ValidationError('Este atendimento não permite registrar chegada.')
            elif action=='charge' and charge_form.is_valid():
                services.create_charge(user=request.user,unit=unit,**charge_form.cleaned_data)
            elif action=='expense' and expense_form.is_valid():
                data=expense_form.cleaned_data;data.pop('confirmed');data['image']=data.pop('photo')
                services.expense(user=request.user,unit=unit,**data)
            elif action in {'open','close'} and cash_form.is_valid():
                data=cash_form.cleaned_data
                if action=='open':services.open_clinic_cash(request.user,unit,data['amount'],data['notes'])
                else:services.close_clinic_cash(user=request.user,unit=unit,**data)
            elif action=='method' and payment_form.is_valid():
                if ClinicPaymentMethod.objects.filter(tenant=tenant,name=payment_form.cleaned_data['name']).exists():
                    raise ValidationError('Esta modalidade já existe.')
                row=payment_form.save(commit=False);row.tenant=tenant;row.save()
                append_audit(tenant=tenant,user=request.user,request=request,action='clinic.payment_method.created',entity_type='ClinicPaymentMethod',entity_id=row.pk)
            elif action=='toggle-method':
                pk=request.POST.get('method','')
                if not pk.isdigit():raise ValidationError('Modalidade inválida.')
                row=get_object_or_404(ClinicPaymentMethod,tenant=tenant,pk=pk)
                row.active=not row.active;row.save(update_fields=['active','updated_at'])
                append_audit(tenant=tenant,user=request.user,request=request,action='clinic.payment_method.toggled',entity_type='ClinicPaymentMethod',entity_id=row.pk,after={'active':row.active})
            elif action not in {'charge','expense','open','close','method'}:
                raise PermissionDenied
            else:raise ValidationError('Revise os campos indicados antes de salvar.')
            messages.success(request,'Operação registrada com sucesso.')
            return redirect('clinic-finance-desk')
        except ValidationError as exc:messages.error(request,' '.join(exc.messages))
    day_field=forms.DateField(required=False)
    try:day=day_field.clean(request.GET.get('day')) or timezone.localdate(timezone=services.day_bounds(tenant,timezone.localdate())[0].tzinfo)
    except ValidationError:day=timezone.localdate()
    start,end=services.day_bounds(tenant,day)
    visits=Appointment.objects.filter(tenant=tenant,unit=unit,starts_at__gte=start,starts_at__lte=end)
    charges=ClinicCharge.objects.filter(tenant=tenant,unit=unit).select_related('customer').annotate(
        received_total=Coalesce(Sum('installments__receipts__amount'),Value(Decimal('0')),output_field=DecimalField(max_digits=12,decimal_places=2)))
    patient_id=request.GET.get('patient','')
    if patient_id.isdigit():charges=charges.filter(customer_id=patient_id)
    charges=charges.order_by('-created_at')[:100]
    session=CashSession.objects.filter(tenant=tenant,unit=unit,status='open').first()
    installments=ClinicInstallment.objects.filter(charge__tenant=tenant,charge__unit=unit).select_related('charge__customer','pending_transaction').order_by('due_at','pk')
    pending=installments.annotate(received_sum=Coalesce(Sum('receipts__amount'),Value(Decimal('0')),output_field=DecimalField(max_digits=12,decimal_places=2))).filter(amount__gt=F('received_sum'))[:200]
    from healthcare.finance_views import allowed as legacy_receivables_allowed
    return render(request,'finance/clinic_desk.html',{'unit':unit,'day':day,'charges':charges,'legacy_receivables_allowed':legacy_receivables_allowed(request.user),'visits':visits.select_related('customer','professional').order_by('starts_at')[:200],'waiting_count':visits.filter(status='waiting').count(),'attending_count':visits.filter(status='in_progress').count(),'completed_count':visits.filter(status='completed').count(),'summary':services.period_summary(tenant,unit,start,end),
        'birthday_admin':request.user.role in {'owner','tenant-admin','manager'},'session':session,'cash_balance':cash_balance(session) if session else None,'cash_form':cash_form,
        'charge_form':charge_form,'expense_form':expense_form,'payment_form':payment_form,'pending':pending,
        'methods':ClinicPaymentMethod.objects.filter(tenant=tenant).order_by('kind','name'),
        'transactions':FinancialTransaction.objects.filter(tenant=tenant,unit=unit,status='paid',paid_at__gte=start,paid_at__lte=end).order_by('paid_at')[:300],
        'expenses':ClinicExpense.objects.filter(session__tenant=tenant,session__unit=unit,created_at__gte=start,created_at__lte=end).select_related('transaction')[:200],
        'closings':ClinicCashClosing.objects.filter(session__tenant=tenant,session__unit=unit).select_related('session').order_by('-session__closed_at')[:30]})


@login_required
@never_cache
def receive(request,pk):
    tenant=services.access(request.user);unit=selected_unit(request,tenant)
    row=get_object_or_404(ClinicInstallment.objects.select_related('charge__customer'),pk=pk,charge__tenant=tenant,charge__unit=unit)
    form=ReceiptForm(request.POST or None,tenant=tenant,initial={'request_id':uuid.uuid4(),'amount':row.remaining})
    if request.method=='POST' and form.is_valid():
        data=form.cleaned_data;data.pop('confirmed')
        try:
            services.receive(user=request.user,unit=unit,installment=row,**data)
            messages.success(request,'Recebimento registrado. O saldo da parcela foi atualizado.')
            return redirect('clinic-finance-desk')
        except ValidationError as exc:form.add_error(None,exc)
    return render(request,'finance/clinic_receipt.html',{'row':row,'form':form})


@login_required
@never_cache
def photo(request,pk):
    tenant=services.access(request.user);unit=selected_unit(request,tenant)
    row=get_object_or_404(ClinicExpense,pk=pk,session__tenant=tenant,session__unit=unit)
    if not row.receipt_encrypted:return HttpResponse(status=404)
    raw=Fernet(settings.FIELD_ENCRYPTION_KEY.encode()).decrypt(bytes(row.receipt_encrypted))
    append_audit(tenant=tenant,user=request.user,request=request,action='clinic.expense.photo.read',entity_type='ClinicExpense',entity_id=row.pk)
    response=HttpResponse(raw,content_type=row.receipt_mime)
    response['X-Content-Type-Options']='nosniff';response['Content-Disposition']='inline; filename="comprovante.jpg"'
    return response


@login_required
@never_cache
def professional_report(request):
    from scheduling.models import Professional
    from billing.entitlements import require_module,is_healthcare_tenant
    user=request.user
    if (not user.is_active or user.is_superuser or user.role not in {'professional','healthcare'} or not user.tenant_id
        or not is_healthcare_tenant(user.tenant) or user.tenant.archived_at or user.tenant.deleted_at):raise PermissionDenied
    require_module(user.tenant,'finance')
    profile=get_object_or_404(Professional,user=user,tenant=user.tenant,active=True)
    if request.method!='GET':raise PermissionDenied
    rows=ClinicCharge.objects.filter(tenant=user.tenant,professional=profile).select_related('customer').annotate(
        received_total=Coalesce(Sum('installments__receipts__amount'),Value(Decimal('0')),output_field=DecimalField(max_digits=12,decimal_places=2)))
    patient=request.GET.get('patient','')
    if patient.isdigit():rows=rows.filter(customer_id=patient)
    totals=rows.aggregate(charged=Sum('amount'),received=Sum('received_total'))
    return render(request,'finance/professional_clinical_report.html',{'charges':rows.order_by('-created_at')[:200],
        'charged':totals['charged'] or Decimal(0),'received':totals['received'] or Decimal(0),
        'pending':(totals['charged'] or Decimal(0))-(totals['received'] or Decimal(0))})
