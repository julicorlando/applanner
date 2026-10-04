"""Operational console for the platform owner; never exposes provider credentials."""
import calendar
import csv
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, OuterRef, Subquery, Count
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST
from requests.exceptions import RequestException

from billing.models import Payment, Subscription, PixCharge, PaymentGateway, WebhookEvent
from communications.models import Notification
from finance.platform_dashboard import PeriodForm, platform_totals
from finance.models import PlatformFinancialTransaction
from operations.models import Backup, CronHeartbeat, OperationalIncident, PlatformOperationSettings, SupportTicket, BillingSupportRequest
from scheduling.models import Professional, Appointment, Customer, Service
from tenants.models import Tenant, TenantStatusHistory
from .audit import append_audit
from .models import AuditLog
from .master import _guard


def companies():
    return Tenant.objects.filter(deleted_at__isnull=True,archived_at__isnull=True)


def latest_subscriptions():
    latest=Subscription.objects.filter(tenant_id=OuterRef('tenant_id')).order_by('-started_at','-pk').values('pk')[:1]
    return Subscription.objects.filter(pk=Subquery(latest),tenant__deleted_at__isnull=True,tenant__archived_at__isnull=True)


def overdue_payments():
    return Payment.objects.filter(purpose='subscription',environment='production',status='pending',due_at__lt=timezone.now(),tenant__deleted_at__isnull=True,tenant__archived_at__isnull=True)


def overview():
    now=timezone.now()
    today=timezone.localdate()
    end=date(today.year,today.month,calendar.monthrange(today.year,today.month)[1])
    totals=platform_totals(today.replace(day=1),end)
    subs=latest_subscriptions()
    return {'active_companies':companies().filter(status='active').count(),
        'trial_companies':companies().filter(status='trial').count(),
        'ending_trials':subs.filter(status='trial',trial_ends_at__gte=now,trial_ends_at__lte=now+timedelta(days=2)).count(),
        'overdue_count':overdue_payments().count(),'totals':totals,'month':today,
        'alert_count':len(alert_rows())}


def alert_rows():
    now=timezone.now()
    rows=[]
    def add(level,title,count,route,args=(),detail=''):
        if count: rows.append({'level':level,'title':title,'count':count,'url':reverse(route,args=args),'detail':detail})
    add('warning','Pix pendentes há mais de uma hora',PixCharge.objects.filter(payment__status='pending',created_at__lt=now-timedelta(hours=1),payment__environment='production',tenant__deleted_at__isnull=True,tenant__archived_at__isnull=True).count(),'master-charges',detail='Inclui códigos expirados: consulte o provedor antes de orientar um novo pagamento.')
    add('danger','Notificações com falha',Notification.objects.filter(status='failed',tenant__deleted_at__isnull=True,tenant__archived_at__isnull=True).count(),'master-alerts',detail='Confira a lista de falhas abaixo e a conexão do canal utilizado.')
    add('warning','Cobranças vencidas',overdue_payments().count(),'master-charges',detail='Abra as cobranças e filtre por vencidas.')
    add('danger','Incidentes críticos em aberto',OperationalIncident.objects.filter(severity='critical',status__in=['open','acknowledged']).count(),'master-resource-list',('incidentes',))
    backup=Backup.objects.filter(type__in=['database','full'],status='completed').filter(Q(expires_at__isnull=True)|Q(expires_at__gt=now)).order_by('-completed_at').first()
    add('danger','Backup recente indisponível',int(not backup or not backup.completed_at or backup.completed_at<now-timedelta(hours=26)),'master-resource-list',('backups',),detail='É esperado um backup concluído nas últimas 26 horas. A integridade deve ser conferida na área de backups.')
    ops=PlatformOperationSettings.objects.first()
    minutes=ops.cron_stale_minutes if ops else 15
    heartbeat=CronHeartbeat.objects.filter(cron_key='platform_health').order_by('-started_at').first()
    add('danger','Sem sinal saudável do processamento automático',int(not heartbeat or heartbeat.status!='ok' or not heartbeat.finished_at or heartbeat.finished_at<now-timedelta(minutes=minutes)),'master-resource-list',('crons',),detail=f'Nenhum health check saudável nos últimos {minutes} minutos. Confira worker e beat.')
    from django_celery_beat.models import PeriodicTask
    from .management.commands.seed_periodic_tasks import TASKS
    expected={name for name,_,_,_ in TASKS}
    configured={task.name:task for task in PeriodicTask.objects.filter(name__in=expected).select_related('interval')}
    for name,_,every,period in TASKS:
        task=configured.get(name)
        seconds=every*{'minutes':60,'hours':3600}[period]
        cutoff=now-timedelta(seconds=max(seconds*2,minutes*60))
        stale=not task or not task.enabled or (task.last_run_at or task.date_changed)<cutoff
        if stale: add('warning',f'Tarefa sem disparo recente: {name}',1,'master-resource-list',('crons',),detail='Ausente, desabilitada ou atrasada. O disparo não confirma a conclusão; confira o histórico operacional.')
    return rows


@login_required
def alerts(request):
    _guard(request.user)
    return render(request,'master/alerts.html',{'alerts':alert_rows(),'checked_at':timezone.now(),'failed_notifications':Notification.objects.filter(status='failed',tenant__deleted_at__isnull=True,tenant__archived_at__isnull=True).select_related('tenant').order_by('-created_at')[:50]})


@login_required
def company_detail(request,pk):
    _guard(request.user)
    from billing.entitlements import professional_capacity
    tenant=get_object_or_404(Tenant,pk=pk)
    return render(request,'master/company_detail.html',{'company':tenant,
        'subscription':tenant.subscriptions.select_related('plan').order_by('-started_at','-pk').first(),
        'capacity':professional_capacity(tenant),
        'units':tenant.units.order_by('-active','name'),
        'professionals':Professional.objects.filter(tenant=tenant).select_related('unit').order_by('name')[:100],
        'payments':tenant.payments.filter(purpose='subscription').order_by('-created_at')[:30],
        'tickets':tenant.support_tickets.order_by('-created_at')[:30],
        'audit':AuditLog.objects.filter(Q(tenant=tenant)|Q(entity_type__iexact='tenants.Tenant',entity_id=tenant.pk)).select_related('user').order_by('-created_at','-pk')[:50],
        'deleted':tenant.deleted_at is not None})


def impact(tenant):
    return {'unidades':tenant.units.count(),'profissionais':Professional.objects.filter(tenant=tenant).count(),
        'servicos':Service.objects.filter(tenant=tenant).count(),'clientes':Customer.objects.filter(tenant=tenant).count(),
        'agendamentos':Appointment.objects.filter(tenant=tenant).count(),'usuarios':tenant.users.filter(deleted_at__isnull=True).count(),
        'pagamentos':tenant.payments.count(),'assinaturas':tenant.subscriptions.count()}


@login_required
def company_lifecycle(request,pk,action):
    _guard(request.user)
    if action not in {'archive','restore','delete'}:
        from django.http import Http404
        raise Http404
    tenant=get_object_or_404(Tenant,pk=pk,deleted_at__isnull=True)
    errors=[]
    if request.method=='POST':
        if request.POST.get('confirm_name','').strip()!=tenant.name or request.POST.get('confirm_impact')!='yes':
            errors.append('Digite o nome exato da empresa e confirme que leu os efeitos da ação.')
        elif tenant.users.filter(is_superuser=True,deleted_at__isnull=True).exists():
            errors.append('Esta empresa possui um usuário Master vinculado. Reatribua esse acesso antes de arquivar ou excluir.')
        else:
            try:
                with transaction.atomic():
                    tenant=Tenant.objects.select_for_update().get(pk=pk,deleted_at__isnull=True)
                    # Recheck after obtaining the lock: repeated submissions are harmless.
                    if action=='archive' and tenant.archived_at is None:
                        tenant.archive_snapshot={'status':tenant.status,'public_enabled':tenant.public_enabled,'public_booking_enabled':tenant.public_booking_enabled}
                        tenant.archived_at=timezone.now()
                        tenant.status='suspended'
                        tenant.public_enabled=False
                        tenant.public_booking_enabled=False
                        tenant.save(update_fields=['archive_snapshot','archived_at','status','public_enabled','public_booking_enabled','updated_at'])
                        TenantStatusHistory.objects.create(tenant=tenant,from_status=tenant.archive_snapshot['status'],to_status=tenant.status,reason='Arquivamento pelo Master',changed_by=request.user)
                        append_audit(tenant=tenant,user=request.user,action='MASTER_COMPANY_ARCHIVED',entity_type='tenants.Tenant',entity_id=tenant.pk,request=request)
                    elif action=='restore' and tenant.archived_at:
                        previous=tenant.status
                        saved=tenant.archive_snapshot
                        tenant.status=saved.get('status','suspended')
                        tenant.public_enabled=bool(saved.get('public_enabled',False))
                        tenant.public_booking_enabled=bool(saved.get('public_booking_enabled',False))
                        tenant.archived_at=None
                        tenant.archive_snapshot={}
                        tenant.save(update_fields=['archive_snapshot','archived_at','status','public_enabled','public_booking_enabled','updated_at'])
                        TenantStatusHistory.objects.create(tenant=tenant,from_status=previous,to_status=tenant.status,reason='Restauração pelo Master',changed_by=request.user)
                        append_audit(tenant=tenant,user=request.user,action='MASTER_COMPANY_RESTORED',entity_type='tenants.Tenant',entity_id=tenant.pk,request=request)
                    elif action=='delete':
                        from .master import _approve_account_deletion
                        owner=tenant.users.filter(role='owner',deleted_at__isnull=True).first() or request.user
                        ticket=SupportTicket.objects.create(tenant=tenant,user=owner,protocol='MASTER-'+uuid4().hex[:20],category='account_deletion',subject='Exclusão confirmada pelo Master',description='Limpeza administrativa com confirmação pelo nome da empresa.')
                        row=BillingSupportRequest.objects.create(tenant=tenant,user=owner,ticket=ticket,request_type='account_deletion')
                        _approve_account_deletion(row,request.user,notify=False)
                messages.success(request,'Ação concluída. O histórico financeiro e de auditoria foi preservado.')
                return redirect('master-company-detail',pk=tenant.pk)
            except (ValidationError,ValueError,RuntimeError,RequestException):
                errors.append('Não foi possível concluir. Se houver assinatura recorrente, o provedor precisa confirmar o cancelamento. Nenhum encerramento local foi confirmado.')
    return render(request,'master/company_lifecycle.html',{'company':tenant,'action':action,'impact':impact(tenant),'errors':errors})


class ChargeFilter(PeriodForm):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['start'].required=False
        self.fields['end'].required=False


def filtered_charges(request):
    qs=Payment.objects.filter(purpose='subscription').select_related('tenant','subscription')
    status=request.GET.get('status','')
    method=request.GET.get('method','')
    environment=request.GET.get('environment','production')
    q=request.GET.get('q','').strip()
    if environment in {'production','sandbox','unknown'}: qs=qs.filter(environment=environment)
    if status in dict(Payment.Status.choices): qs=qs.filter(status=status)
    elif status=='overdue': qs=qs.filter(status='pending',due_at__lt=timezone.now())
    if method=='pix': qs=qs.filter(pix_charges__isnull=False)
    elif method=='card': qs=qs.filter(pix_charges__isnull=True).filter(Q(metadata__method__in=['card_recurring','card'])|Q(subscription__payment_method='card'))
    if q: qs=qs.filter(Q(tenant__name__icontains=q)|Q(provider_reference__icontains=q)|Q(provider_payment_id__icontains=q))
    form=ChargeFilter(request.GET)
    if form.is_valid():
        if form.cleaned_data.get('start'): qs=qs.filter(due_at__date__gte=form.cleaned_data['start'])
        if form.cleaned_data.get('end'): qs=qs.filter(due_at__date__lte=form.cleaned_data['end'])
    else: qs=qs.none()
    return qs.order_by('-created_at','-pk').distinct(),form


@login_required
def charges(request):
    _guard(request.user)
    from django.core.paginator import Paginator
    qs,form=filtered_charges(request)
    return render(request,'master/charges.html',{'page':Paginator(qs,50).get_page(request.GET.get('page')),'form':form,
        'filters':request.GET,'statuses':Payment.Status.choices,'query':request.GET.urlencode()})


@login_required
def charge_detail(request,pk):
    _guard(request.user)
    payment=get_object_or_404(Payment.objects.select_related('tenant','subscription'),pk=pk,purpose='subscription')
    charge=PixCharge.objects.filter(payment=payment).first()
    ids=[value for value in [payment.provider_payment_id,charge.provider_order_id if charge else ''] if value]
    accounting=(payment.metadata or {}).get('accounting') or {}
    checked=parse_datetime(accounting.get('checked_at','')) if accounting.get('checked_at') else None
    return render(request,'master/charge_detail.html',{'payment':payment,'pix':charge,'accounting':accounting,'accounting_checked':checked,
        'consultations':AuditLog.objects.filter(entity_type='billing.Payment',entity_id=payment.pk,action__in=['MASTER_PAYMENT_CONSULTED','MASTER_FINANCIAL_RECONCILIATION']).select_related('user').order_by('-created_at','-pk')[:30],
        'events':WebhookEvent.objects.filter(provider=payment.provider,resource_id__in=ids).order_by('-received_at')[:20],
        'can_consult':payment.provider=='mercadopago' and bool(charge or payment.provider_payment_id)})


def reconcile_card(payment):
    """Consult a known charge, validate identity/amount, preserve cancelled subscriptions."""
    from billing.payment_services import platform_provider
    snapshot=(payment.provider_payment_id,payment.provider_reference,payment.environment,payment.amount)
    gateway=PaymentGateway.objects.filter(provider='mercadopago',environment=payment.environment,active=True,last_test_status='validated').first()
    if not gateway: raise ValueError('Conexão indisponível.')
    remote=platform_provider(gateway).get_payment(payment.provider_payment_id)
    try: amount=Decimal(str(remote.get('transaction_amount')))
    except (InvalidOperation,TypeError,ValueError): raise ValueError('Valor inválido.')
    if str(remote.get('id',''))!=payment.provider_payment_id or remote.get('external_reference')!=payment.provider_reference or remote.get('currency_id')!='BRL' or not amount.is_finite() or amount!=payment.amount:
        raise ValueError('Identidade, moeda ou valor divergentes.')
    if not isinstance(remote.get('live_mode'),bool) or remote['live_mode']!=(payment.environment=='production'):
        raise ValueError('Ambiente divergente.')
    new_status={'approved':'paid','authorized':'pending','pending':'pending','in_process':'pending','rejected':'failed','cancelled':'cancelled','refunded':'refunded','charged_back':'refunded','partially_refunded':'partially_refunded'}.get(remote.get('status'),'pending')
    approved_at=None
    if new_status=='paid':
        try: approved_at=parse_datetime(str(remote.get('date_approved') or ''))
        except ValueError: approved_at=None
        if not approved_at or timezone.is_naive(approved_at) or approved_at>timezone.now()+timedelta(minutes=1):
            raise ValueError('Data de aprovação inválida.')
    with transaction.atomic():
        subscription=Subscription.objects.select_for_update().get(pk=payment.subscription_id) if payment.subscription_id else None
        payment=Payment.objects.select_for_update().get(pk=payment.pk)
        if (payment.provider_payment_id,payment.provider_reference,payment.environment,payment.amount)!=snapshot:
            raise ValueError('Cobrança alterada durante a consulta.')
        if payment.status=='paid' and new_status=='pending':
            return payment.status
        if payment.status in {'cancelled','refunded','partially_refunded'} and new_status=='paid':
            raise ValueError('Cobrança encerrada não pode ser reaberta.')
        payment.provider_status=str(remote.get('status') or '')
        payment.status=new_status
        if new_status=='paid': payment.paid_at=payment.paid_at or approved_at
        from billing.platform_accounting import capture_accounting
        capture_accounting(payment,remote)
        payment.save(update_fields=['provider_status','status','paid_at','metadata','updated_at'])
        if subscription and new_status=='paid' and subscription.status in {'trial','active','past_due'}:
            subscription.status='active'
            subscription.save(update_fields=['status','updated_at'])
    return new_status


@login_required
@require_POST
def charge_consult(request,pk):
    _guard(request.user)
    payment=get_object_or_404(Payment,pk=pk,purpose='subscription',provider='mercadopago')
    before=payment.status
    result='failed'
    error_class=''
    try:
        charge=PixCharge.objects.filter(payment=payment).first()
        if charge:
            from billing.pix_reconciliation import reconcile_pix_charge
            paid=reconcile_pix_charge(charge.pk)
            result='paid' if paid else 'not_confirmed'
        elif payment.provider_payment_id and payment.provider_reference:
            result=reconcile_card(payment)
        else: raise ValueError('Referência indisponível.')
        messages.success(request,'Consulta concluída. O status exibido foi conferido no provedor.')
    except (ValueError,RuntimeError,RequestException) as exc:
        error_class=type(exc).__name__
        messages.error(request,'A consulta não confirmou esta cobrança. Confira a conexão e as referências; nenhum pagamento foi aprovado manualmente.')
    payment.refresh_from_db()
    append_audit(tenant=payment.tenant,user=request.user,action='MASTER_PAYMENT_CONSULTED',entity_type='billing.Payment',entity_id=payment.pk,before={'status':before},after={'status':payment.status,'result':result,'error_class':error_class},request=request)
    return redirect('master-charge-detail',pk=payment.pk)


@login_required
def reports(request):
    _guard(request.user)
    today=timezone.localdate()
    form=PeriodForm(request.GET if request.GET else None,initial={'start':today.replace(day=1),'end':today})
    context={'form':form,'kinds':[('revenue','Receitas recebidas'),('expenses','Despesas pagas'),('overdue','Cobranças vencidas'),('companies','Empresas cadastradas'),('growth','Evolução de empresas')]}
    if request.GET and form.is_valid():
        start,end=form.cleaned_data['start'],form.cleaned_data['end']
        context.update(totals=platform_totals(start,end),growth=list(Tenant.objects.filter(created_at__date__range=(start,end)).annotate(month=TruncMonth('created_at')).values('month').annotate(count=Count('pk')).order_by('month')))
        if request.GET.get('export')=='csv' and request.GET.get('kind') in dict(context['kinds']):
            return export_report(request,request.GET['kind'],start,end)
    return render(request,'master/reports.html',context)


def export_report(request,kind,start,end):
    response=HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition']=f'attachment; filename="applanner-{kind}-{start}-{end}.csv"'
    response.write('\ufeff')
    writer=csv.writer(response,delimiter=';')
    def write(row):
        # Prevent spreadsheet formula injection in user-supplied names and notes.
        writer.writerow([money(x) if isinstance(x,Decimal) else "'"+str(x) if isinstance(x,str) and str(x).lstrip().startswith(('=','+','-','@','\t','\r','\n')) else x for x in row])
    def money(amount): return f'{amount:.2f}'.replace('.',',')
    def day(value): return timezone.localtime(value).strftime('%d/%m/%Y %H:%M') if hasattr(value,'hour') else str(value or '')
    if kind=='companies':
        write(['Empresa','Situação','Cadastro','Arquivada','Excluída'])
        for row in Tenant.objects.filter(created_at__date__range=(start,end)).order_by('created_at').iterator(): write([row.name,row.get_status_display(),day(row.created_at),'Sim' if row.archived_at else 'Não','Sim' if row.deleted_at else 'Não'])
    elif kind=='growth':
        write(['Mês','Empresas cadastradas'])
        for row in Tenant.objects.filter(created_at__date__range=(start,end)).annotate(month=TruncMonth('created_at')).values('month').annotate(count=Count('pk')).order_by('month'): write([row['month'].strftime('%m/%Y'),row['count']])
    elif kind=='overdue':
        write(['Empresa','Vencimento','Valor','Situação'])
        for row in overdue_payments().filter(due_at__date__range=(start,end)).select_related('tenant').order_by('due_at').iterator(): write([row.tenant.name,day(row.due_at),money(row.amount),row.get_status_display()])
    else:
        write(['Origem','Empresa / descrição','Data de pagamento','Valor'])
        if kind=='revenue':
            qs=Payment.objects.filter(purpose='subscription',subscription__isnull=False,environment='production',status__in=['paid','partially_refunded','refunded']).filter(Q(paid_at__date__range=(start,end))|Q(paid_at__isnull=True,updated_at__date__range=(start,end))).select_related('tenant')
            for row in qs.order_by('paid_at','pk').iterator():
                write(['Assinatura',row.tenant.name,day(row.paid_at or row.updated_at),money(row.amount)])
                from billing.platform_accounting import accounting_totals
                adjustments=accounting_totals([row])
                if adjustments['refunds']: write(['Estorno',row.tenant.name,day(row.paid_at or row.updated_at),-adjustments['refunds']])
                if adjustments['provider_fees']: write(['Taxa do provedor',row.tenant.name,day(row.paid_at or row.updated_at),-adjustments['provider_fees']])
        qs=PlatformFinancialTransaction.objects.filter(type='income' if kind=='revenue' else 'expense',status='paid').filter(Q(paid_at__date__range=(start,end))|Q(paid_at__isnull=True,updated_at__date__range=(start,end)))
        if kind=='expenses':
            linked=Payment.objects.filter(environment='production',purpose='subscription',status__in=['paid','partially_refunded','refunded'],metadata__accounting__fee__isnull=False).exclude(metadata__accounting__fee=None).values_list('pk',flat=True)
            qs=qs.exclude(provider_fee_payment_id__in=linked)
        for row in qs.order_by('paid_at','pk').iterator(): write(['Lançamento',row.description,day(row.paid_at or row.updated_at),money(row.amount)])
    append_audit(user=request.user,action='MASTER_REPORT_EXPORTED',entity_type='finance.PlatformFinancialTransaction',after={'kind':kind,'start':str(start),'end':str(end)},request=request)
    return response
