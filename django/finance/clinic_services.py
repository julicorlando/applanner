from calendar import monthrange
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from billing.entitlements import is_healthcare_tenant, require_module
from accounts.permissions import has_capability
from core.audit import append_audit
from tenants.models import Tenant
from .models import FinancialTransaction, CashSession
from .clinic_models import ClinicCharge, ClinicInstallment, ClinicReceipt, ClinicExpense, ClinicCashClosing, ClinicPaymentMethod
from .services import open_cash_session, close_cash_session
from .advanced_services import cash_balance


def access(user):
    if (not user.is_authenticated or not user.is_active or user.is_superuser or not user.tenant_id
        or user.role not in {'owner','tenant-admin','manager','reception','finance'}
        or not is_healthcare_tenant(user.tenant) or user.tenant.archived_at or user.tenant.deleted_at):
        raise PermissionDenied
    if user.role=='reception':
        if not has_capability(user,'agenda.manage') or (user.tenant.metadata or {}).get('clinical_reception_billing') is False:
            raise PermissionDenied('A gestão desativou a operação financeira da recepção.')
    elif not has_capability(user,'finance.manage'):
        raise PermissionDenied
    require_module(user.tenant,'finance')
    return user.tenant


def money(value, allow_zero=False):
    try:
        value=Decimal(str(value))
        if not value.is_finite() or value<0 or (not allow_zero and value==0) or value>Decimal('9999999999.99') or value!=value.quantize(Decimal('.01')):
            raise ValueError
        return value.quantize(Decimal('.01'))
    except (InvalidOperation,ValueError,TypeError):
        raise ValidationError('Informe um valor em reais, com até duas casas decimais.') from None


def lock_company(user):
    tenant=access(user)
    return Tenant.objects.select_for_update().get(pk=tenant.pk)


def active_cash(tenant,unit):
    row=CashSession.objects.select_for_update().filter(tenant=tenant,unit=unit,status='open').first()
    if not row: raise ValidationError('Abra o caixa desta unidade antes de registrar recebimentos ou despesas.')
    return row


@transaction.atomic
def open_clinic_cash(user,unit,amount,notes=""):
    tenant=lock_company(user)
    if unit and (unit.tenant_id!=tenant.pk or not unit.active): raise PermissionDenied
    row=open_cash_session(tenant=tenant,user=user,unit=unit,opening_amount=money(amount,True),notes=notes)
    append_audit(tenant=tenant,user=user,action='clinic.cash.opened',entity_type='CashSession',entity_id=row.pk)
    return row


@transaction.atomic
def create_charge(*,user,unit,customer,description,amount,count,first_due,request_id,professional=None):
    tenant=lock_company(user)
    if customer.tenant_id!=tenant.pk or not customer.active or (unit and (unit.tenant_id!=tenant.pk or not unit.active)): raise PermissionDenied
    if professional and (professional.tenant_id!=tenant.pk or not professional.active):raise PermissionDenied
    amount=money(amount);count=int(count)
    if not 1<=count<=60 or amount*100<count or not 1<=len(description.strip())<=190:
        raise ValidationError('Informe descrição e de 1 a 60 parcelas, com valor mínimo de R$ 0,01 por parcela.')
    existing=ClinicCharge.objects.filter(tenant=tenant,request_id=request_id).first()
    if existing:
        if (existing.customer_id!=customer.pk or existing.unit_id!=(unit.pk if unit else None) or existing.amount!=amount
            or existing.description!=description.strip() or existing.professional_id!=(professional.pk if professional else None) or existing.installments.count()!=count or existing.installments.get(number=1).due_at!=first_due):
            raise ValidationError('Esta operação já foi registrada com outros dados. Atualize a página.')
        return existing
    row=ClinicCharge.objects.create(tenant=tenant,unit=unit,customer=customer,professional=professional,created_by=user,description=description.strip(),amount=amount,request_id=request_id)
    cents=int(amount*100);base,remainder=divmod(cents,count)
    for number in range(1,count+1):
        month=first_due.month-1+number-1;year=first_due.year+month//12;month=month%12+1
        due=first_due.replace(year=year,month=month,day=min(first_due.day,monthrange(year,month)[1]))
        value=Decimal(base+(number<=remainder))/100
        tx=FinancialTransaction.objects.create(tenant=tenant,unit=unit,source_type='clinic-receivable',source_id=row.pk,
            type='income',description=f'{row.description} · parcela {number}/{count}'[:190],amount=value,due_at=due,competence_at=first_due,
            idempotency_key=f'clinic-charge:{row.pk}:{number}')
        ClinicInstallment.objects.create(charge=row,number=number,amount=value,due_at=due,pending_transaction=tx)
    append_audit(tenant=tenant,user=user,action='clinic.charge.created',entity_type='ClinicCharge',entity_id=row.pk,after={'amount':str(amount),'installments':count})
    return row


@transaction.atomic
def receive(*,user,unit,installment,amount,method,request_id):
    tenant=lock_company(user);amount=money(amount)
    row=ClinicInstallment.objects.select_for_update().select_related('charge').get(pk=installment.pk,charge__tenant=tenant,charge__unit=unit)
    existing=ClinicReceipt.objects.filter(request_id=request_id).first()
    if existing:
        if existing.installment_id!=row.pk or existing.recorded_by_id!=user.pk or existing.amount!=amount or existing.method_id!=method.pk:
            raise ValidationError('Identificador de recebimento já utilizado com outros dados.')
        return existing
    session=active_cash(tenant,unit)
    method=ClinicPaymentMethod.objects.select_for_update().filter(pk=method.pk,tenant=tenant,active=True).first()
    if method is None:raise PermissionDenied
    remaining=row.remaining
    if amount>remaining: raise ValidationError('O valor recebido não pode ultrapassar o saldo da parcela.')
    pending=FinancialTransaction.objects.select_for_update().get(pk=row.pending_transaction_id,tenant=tenant)
    if pending.status!='pending' or pending.amount!=remaining:
        raise ValidationError('A parcela foi alterada por outra operação financeira. Confira antes de receber.')
    now=timezone.now()
    if amount==remaining:
        tx=pending;tx.status='paid';tx.paid_at=now;tx.payment_method=method.kind
        tx.save(update_fields=['status','paid_at','payment_method','updated_at'])
    else:
        pending.amount=remaining-amount;pending.save(update_fields=['amount','updated_at'])
        tx=FinancialTransaction.objects.create(tenant=tenant,unit=unit,type='income',status='paid',paid_at=now,
            source_type='clinic-receipt',source_id=row.charge_id,description=pending.description,amount=amount,
            payment_method=method.kind,competence_at=pending.competence_at,idempotency_key=f'clinic-receipt:{request_id}')
    receipt=ClinicReceipt.objects.create(installment=row,session=session,method=method,method_name=method.name,amount=amount,
        transaction=tx,recorded_by=user,request_id=request_id)
    append_audit(tenant=tenant,user=user,action='clinic.receipt.recorded',entity_type='ClinicReceipt',entity_id=receipt.pk,
        after={'transaction_id':tx.pk,'amount':str(amount),'method':method.kind,'manual':True})
    return receipt


@transaction.atomic
def expense(*,user,unit,description,amount,method,invoice,items,image,request_id):
    tenant=lock_company(user);amount=money(amount)
    existing=ClinicExpense.objects.filter(request_id=request_id).select_related('transaction','session').first()
    if existing:
        tx=existing.transaction
        if (existing.session.tenant_id!=tenant.pk or existing.recorded_by_id!=user.pk or existing.session.unit_id!=(unit.pk if unit else None)
            or tx.amount!=amount or tx.description!=description.strip() or existing.method_id!=method.pk
            or existing.invoice_number!=invoice or existing.items!=items):
            raise ValidationError('Esta despesa já foi registrada com outros dados.')
        from cryptography.fernet import Fernet
        from django.conf import settings
        cipher=Fernet(settings.FIELD_ENCRYPTION_KEY.encode())
        previous=cipher.decrypt(bytes(existing.receipt_encrypted)) if existing.receipt_encrypted else b''
        supplied=cipher.decrypt(image[0]) if image else b''
        if previous!=supplied:raise ValidationError('O comprovante desta operação é diferente do original.')
        return existing
    session=active_cash(tenant,unit)
    method=ClinicPaymentMethod.objects.select_for_update().filter(pk=method.pk,tenant=tenant,active=True).first()
    if method is None:raise PermissionDenied
    if method.kind=='cash' and amount>cash_balance(session): raise ValidationError('Dinheiro insuficiente no caixa para esta despesa.')
    tx=FinancialTransaction.objects.create(tenant=tenant,unit=unit,type='expense',status='paid',paid_at=timezone.now(),
        source_type='clinic-expense',description=description.strip(),amount=amount,payment_method=method.kind,
        competence_at=timezone.localdate(),idempotency_key=f'clinic-expense:{request_id}')
    encrypted,mime=image or (b'','')
    row=ClinicExpense.objects.create(session=session,transaction=tx,recorded_by=user,invoice_number=invoice,items=items,method=method,method_name=method.name,
        receipt_encrypted=encrypted,receipt_mime=mime,request_id=request_id)
    append_audit(tenant=tenant,user=user,action='clinic.expense.recorded',entity_type='ClinicExpense',entity_id=row.pk,after={'transaction_id':tx.pk,'amount':str(amount)})
    return row


def period_summary(tenant,unit,start,end,*,all_units=False):
    scope={'tenant':tenant} if all_units else {'tenant':tenant,'unit':unit}
    rows=FinancialTransaction.objects.filter(**scope,status='paid',paid_at__gte=start,paid_at__lte=end)
    total=lambda qs: qs.aggregate(v=Sum('amount'))['v'] or Decimal(0)
    received=total(rows.filter(type='income'));expenses=total(rows.filter(type='expense'))
    charged=total(ClinicCharge.objects.filter(**scope,created_at__gte=start,created_at__lte=end))
    charged+=total(FinancialTransaction.objects.filter(**scope,type='income',created_at__gte=start,created_at__lte=end)
        .exclude(status='cancelled').exclude(source_type__in=['clinic-receivable','clinic-receipt']))
    pending=total(FinancialTransaction.objects.filter(**scope,type='income',status='pending'))
    methods=[{'method':{'cash':'Dinheiro','pix':'Pix','card':'Cartão','dinheiro':'Dinheiro'}.get(v['payment_method'],v['payment_method'] or 'Não informado'),'type':v['type'],'amount':format(v['v'],'.2f')}
        for v in rows.values('payment_method','type').annotate(v=Sum('amount')).order_by('type','payment_method')]
    return {'charged':format(charged,'.2f'),'received':format(received,'.2f'),'expenses':format(expenses,'.2f'),'net':format(received-expenses,'.2f'),'pending':format(pending,'.2f'),'methods':methods}


def day_bounds(tenant,day):
    from zoneinfo import ZoneInfoNotFoundError
    try: zone=ZoneInfo(tenant.timezone)
    except (ZoneInfoNotFoundError,ValueError): zone=timezone.get_default_timezone()
    start=timezone.make_aware(datetime.combine(day,time.min),zone)
    return start,start+timedelta(days=1)-timedelta(microseconds=1)


@transaction.atomic
def close_clinic_cash(*,user,unit,amount,notes=''):
    tenant=lock_company(user);session=active_cash(tenant,unit)
    closing=money(amount,True)
    summary=period_summary(tenant,unit,session.opened_at,timezone.now())
    session=close_cash_session(session=session,user=user,closing_amount=closing,notes=notes)
    summary.update({'opening':str(session.opening_amount),'cash_expected':str(session.expected_amount),
        'cash_counted':str(session.closing_amount),'difference':str(session.difference_amount),
        'from':session.opened_at.isoformat(),'to':session.closed_at.isoformat()})
    ClinicCashClosing.objects.create(session=session,summary=summary)
    append_audit(tenant=tenant,user=user,action='clinic.cash.closed',entity_type='CashSession',entity_id=session.pk,after=summary)
    return session


@transaction.atomic
def review_expense(*,user,unit,pk,status,note=''):
    tenant=lock_company(user)
    if user.role not in {'owner','tenant-admin','manager'}:raise PermissionDenied
    if status not in {'approved','questioned'} or len(note)>500:
        raise ValidationError('Informe uma decisão válida e observação de até 500 caracteres.')
    if status=='questioned' and not note.strip():
        raise ValidationError('Explique o que precisa ser esclarecido.')
    row=ClinicExpense.objects.select_for_update().get(pk=pk,session__tenant=tenant,session__unit=unit)
    before={'status':row.review_status}
    row.review_status=status;row.review_note=note.strip();row.reviewed_by=user;row.reviewed_at=timezone.now()
    row.save(update_fields=['review_status','review_note','reviewed_by','reviewed_at','updated_at'])
    append_audit(tenant=tenant,user=user,action='clinic.expense.reviewed',entity_type='ClinicExpense',entity_id=row.pk,before=before,after={'status':status,'note':row.review_note})
    return row
