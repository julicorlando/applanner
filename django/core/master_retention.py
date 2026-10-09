"""Production payment conversion and explicit cancellation reasons."""
from collections import defaultdict
from decimal import Decimal
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import OuterRef,Subquery
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from billing.models import Subscription,Payment
from tenants.models import Tenant
from finance.platform_dashboard import PeriodForm
from .master import _guard
from .audit import append_audit

REASONS=[('','Não informado'),('price','Preço'),('features','Funcionalidades'),('usability','Dificuldade de uso'),
         ('closed','Encerramento da empresa'),('competitor','Outro sistema'),('other','Outro motivo')]
class RetentionForm(forms.Form):
    reason=forms.ChoiceField(label='Motivo da saída',choices=REASONS,required=False)
    notes=forms.CharField(label='Observação',max_length=500,required=False,widget=forms.Textarea(attrs={'rows':2}))


def retention_metrics(start,end):
    first=Subscription.objects.filter(tenant_id=OuterRef('tenant_id'),trial_started_at__isnull=False).order_by('trial_started_at','pk').values('pk')[:1]
    trials=Subscription.objects.filter(pk=Subquery(first),trial_started_at__date__range=(start,end)).select_related('tenant')
    paid=set(Payment.objects.filter(environment='production',purpose='subscription',subscription__isnull=False,
        status__in=['paid','partially_refunded','refunded']).values_list('tenant_id',flat=True))
    latest=Subscription.objects.filter(tenant_id=OuterRef('tenant_id')).order_by('-started_at','-pk').values('pk')[:1]
    current=list(Subscription.objects.filter(pk=Subquery(latest)).select_related('tenant','plan'))
    active={s.tenant_id for s in current if s.status=='active' and s.provider_environment!='sandbox' and not s.tenant.deleted_at and not s.tenant.archived_at}
    cohorts=defaultdict(lambda:{'trials':0,'converted':0,'active':0})
    for row in trials:
        cohort=cohorts[timezone.localtime(row.trial_started_at).strftime('%Y-%m')]
        cohort['trials']+=1
        cohort['converted']+=int(row.tenant_id in paid)
        cohort['active']+=int(row.tenant_id in paid and row.tenant_id in active)
    rows=[{'month':month,**data,'conversion':round(data['converted']*100/data['trials'],1)} for month,data in sorted(cohorts.items())]
    cancelled=Subscription.objects.filter(cancelled_at__date__range=(start,end)).select_related('tenant').order_by('-cancelled_at')
    cancellations=[]
    reasons=defaultdict(int)
    seen=set()
    for row in cancelled:
        if row.tenant_id in seen: continue
        seen.add(row.tenant_id)
        note=(row.tenant.metadata or {}).get('retention') or {}
        reason=dict(REASONS).get(note.get('reason',''),'Não informado')
        reasons[reason]+=1
        cancellations.append({'subscription':row,'reason':reason,'reason_code':note.get('reason',''),'notes':note.get('notes','')})
    mrr=sum(((s.contracted_price / Decimal({'monthly':1,'quarterly':3,'semiannual':6,'annual':12}[s.billing_cycle])
             if s.contracted_price is not None else s.plan.monthly_price)
             for s in current if s.tenant_id in active),Decimal('0'))
    from billing.models import TenantModuleAddon
    active_tenants=list(active)
    overdue=Payment.objects.filter(environment='production',purpose='subscription',status='pending',due_at__lt=timezone.now(),tenant__deleted_at__isnull=True,tenant__archived_at__isnull=True)
    overdue_total=sum(overdue.values_list('amount',flat=True),Decimal('0'))
    addons=list(TenantModuleAddon.objects.filter(tenant_id__in=active_tenants,status='active').select_related('module','tenant'))
    addon_usage=defaultdict(lambda:{'companies':set(),'quantity':0,'monthly':Decimal('0')})
    for addon in addons:
        data=addon_usage[addon.module.name];data['companies'].add(addon.tenant_id)
        data['quantity']+=(addon.tenant.units.filter(active=True).count() if addon.module.per_unit_billing else addon.quantity);data['monthly']+=addon.monthly_price
    addon_rows=[{'name':name,'companies':len(data['companies']),'quantity':data['quantity'],'monthly':data['monthly']} for name,data in sorted(addon_usage.items())]
    trial_count=sum(r['trials'] for r in rows);converted_count=sum(r['converted'] for r in rows)
    return {'conversion':round(converted_count*100/trial_count,1) if trial_count else 0,
        'overdue_total':overdue_total,'overdue_count':overdue.count(),'addon_usage':addon_rows,
        'addon_mrr':sum((r['monthly'] for r in addon_rows),Decimal('0')),'cohorts':rows,'trials':sum(r['trials'] for r in rows),'converted':sum(r['converted'] for r in rows),
        'cancellations':cancellations[:100],'cancellation_count':len(seen),'reasons':dict(reasons),'mrr':mrr,'active_count':len(active)}

@login_required
def dashboard(request):
    _guard(request.user)
    today=timezone.localdate()
    form=PeriodForm(request.GET if request.GET else None,initial={'start':today.replace(day=1),'end':today})
    start,end=today.replace(day=1),today
    valid=not form.is_bound or form.is_valid()
    if form.is_bound and valid: start,end=form.cleaned_data['start'],form.cleaned_data['end']
    return render(request,'master/retention.html',{'form':form,'start':start,'end':end,
        'metrics':retention_metrics(start,end) if valid else None,'reason_options':REASONS})

@login_required
@require_POST
def save_note(request,pk):
    _guard(request.user)
    form=RetentionForm(request.POST)
    tenant=get_object_or_404(Tenant,pk=pk)
    if form.is_valid():
        with transaction.atomic():
            tenant=Tenant.objects.select_for_update().get(pk=tenant.pk)
            before=(tenant.metadata or {}).get('retention',{})
            note={**form.cleaned_data,'updated_at':timezone.now().isoformat()}
            tenant.metadata={**(tenant.metadata or {}),'retention':note}
            tenant.save(update_fields=['metadata','updated_at'])
            append_audit(request=request,user=request.user,action='MASTER_RETENTION_UPDATED',entity_type='Tenant',entity_id=tenant.pk,tenant=tenant,before=before,after=note)
        messages.success(request,'Motivo da saída atualizado.')
    else: messages.error(request,'Confira o motivo e a observação (até 500 caracteres).')
    return redirect('master-retention')

@login_required
@require_POST
def consult_accounting(request,pk):
    _guard(request.user)
    payment=get_object_or_404(Payment,pk=pk,purpose='subscription',status__in=['paid','partially_refunded','refunded'])
    from billing.platform_accounting import reconcile_financial_payment
    try:
        result=reconcile_financial_payment(payment.pk)
    except Exception:
        result=False
        messages.error(request,'Não foi possível confirmar taxas e estornos agora. A conciliação automática tentará novamente.')
    else:
        messages.success(request,'Consulta financeira concluída. Campos não informados pelo provedor continuam pendentes.')
    payment.refresh_from_db()
    append_audit(request=request,user=request.user,tenant=payment.tenant,action='MASTER_FINANCIAL_RECONCILIATION',
        entity_type='billing.Payment',entity_id=payment.pk,after={'result':'confirmed' if result else 'failed','status':payment.status})
    return redirect('master-charge-detail',pk=payment.pk)
