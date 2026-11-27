"""Administrative sales reporting; never decrypt clinical procedures or diagnoses."""
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from django import forms
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Sum,Count
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from accounts.permissions import has_capability
from billing.entitlements import require_module
from core.audit import append_audit
from finance.models import FinancialTransaction
from scheduling.models import Professional
from .models import ClinicalTreatmentPlan


class DentistChoice(forms.ModelChoiceField):
    def label_from_instance(self,obj):
        registration=getattr(obj,'clinical_registration',None)
        return (registration.professional_name if registration else '') or obj.name


class SalesPeriodForm(forms.Form):
    month=forms.TypedChoiceField(label='Mês',coerce=int,choices=list(enumerate(['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'],1)))
    year=forms.IntegerField(label='Ano',min_value=1900,max_value=2100)
    professional=DentistChoice(label='Dentista',queryset=Professional.objects.none(),required=False,empty_label='Todos os dentistas')
    def __init__(self,*args,tenant,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['professional'].queryset=Professional.objects.filter(tenant=tenant).select_related('clinical_registration').order_by('name','pk')


@login_required
@never_cache
def treatment_sales(request):
    user=request.user
    if (request.method not in {'GET','HEAD'} or not user.is_active or user.is_superuser or not user.tenant_id
        or user.role not in {'owner','tenant-admin','manager','finance'} or not has_capability(user,'finance.manage')
        or user.tenant.archived_at or user.tenant.deleted_at):raise PermissionDenied
    tenant=user.tenant
    require_module(tenant,'dentistry');require_module(tenant,'finance')
    try:zone=ZoneInfo(tenant.timezone or 'America/Recife')
    except (ZoneInfoNotFoundError,ValueError):zone=timezone.get_default_timezone()
    today=timezone.now().astimezone(zone).date()
    data={'month':request.GET.get('month',today.month),'year':request.GET.get('year',today.year),'professional':request.GET.get('professional','')}
    form=SalesPeriodForm(data,tenant=tenant)
    rows=[];top=[];receivables_page=None;totals={'amount':Decimal(0),'received':Decimal(0),'pending':Decimal(0),'count':0,'ticket':Decimal(0)}
    if form.is_valid():
        month,year=form.cleaned_data['month'],form.cleaned_data['year']
        start=datetime(year,month,1,tzinfo=zone)
        end=datetime(year+int(month==12),month%12+1,1,tzinfo=zone)
        plans=ClinicalTreatmentPlan.objects.filter(entry__tenant=tenant,entry__customer__tenant=tenant,entry__professional__tenant=tenant)
        if form.cleaned_data['professional']:plans=plans.filter(entry__professional=form.cleaned_data['professional'])
        transactions=FinancialTransaction.objects.filter(tenant=tenant,source_type='clinical-plan',source_id__in=plans.values('pk'),type='income',
            status__in=['pending','paid'],created_at__gte=start,created_at__lt=end)
        totals.update(transactions.aggregate(amount=Sum('amount'),count=Count('source_id',distinct=True)))
        totals['amount']=totals['amount'] or Decimal(0)
        totals['received']=transactions.filter(status='paid').aggregate(v=Sum('amount'))['v'] or Decimal(0)
        totals['pending']=totals['amount']-totals['received']
        totals['ticket']=totals['amount']/totals['count'] if totals['count'] else Decimal(0)
        receivables_page=Paginator(transactions.order_by('-created_at','-pk'),50).get_page(request.GET.get('page'))
        page=list(receivables_page)
        largest=list(transactions.values('source_id').annotate(total=Sum('amount')).order_by('-total','source_id')[:5])
        ids={tx.source_id for tx in page}|{row['source_id'] for row in largest}
        metadata={p.pk:p for p in plans.filter(pk__in=ids).select_related('entry__customer','entry__professional__clinical_registration').only('id','entry_id','entry__id','entry__customer_id','entry__customer__id','entry__customer__name','entry__professional_id','entry__professional__id','entry__professional__name','entry__professional__clinical_registration__id','entry__professional__clinical_registration__professional_name')}
        for tx in page:
            plan=metadata[tx.source_id]
            rows.append({'transaction':tx,'patient':plan.entry.customer.name,'professional':plan.entry.professional,'plan_id':plan.pk})
        top=[{'id':r['source_id'],'amount':r['total'],'professional':metadata[r['source_id']].entry.professional} for r in largest]
    append_audit(tenant=tenant,user=user,request=request,action='clinical.treatment.sales.report',entity_type='FinancialTransaction')
    return render(request,'healthcare/treatment_sales.html',{'form':form,'rows':rows,'totals':totals,'top_plans':top,'top_max':max(top[0]['amount'],Decimal(1)) if top else Decimal(1),'receivables_page':receivables_page})
