from datetime import date
from decimal import Decimal
from django import forms
from django.db.models import Q, Sum
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from billing.models import Payment
from core.master import _guard
from .models import PlatformFinancialTransaction


class PeriodForm(forms.Form):
    start = forms.DateField(label='De', widget=forms.DateInput(attrs={'type': 'date'}))
    end = forms.DateField(label='Até', widget=forms.DateInput(attrs={'type': 'date'}))

    def clean(self):
        data = super().clean()
        if data.get('start') and data.get('end') and data['end'] < data['start']:
            raise forms.ValidationError('A data final deve ser igual ou posterior à inicial.')
        return data


def platform_totals(start, end):
    def total(qs):
        return qs.aggregate(value=Sum('amount'))['value'] or Decimal('0.00')
    def paid_period(qs):
        return qs.filter(Q(paid_at__date__range=(start,end)) |
            Q(paid_at__isnull=True,updated_at__date__range=(start,end)))
    def due_period(qs):
        return qs.filter(Q(due_at__range=(start,end)) |
            Q(due_at__isnull=True,created_at__date__range=(start,end)))
    payments = Payment.objects.filter(purpose='subscription', subscription__isnull=False, environment='production')
    approved = paid_period(payments.filter(status__in=['paid','partially_refunded','refunded']))
    from billing.platform_accounting import accounting_totals
    accounting=accounting_totals(approved)
    pending = payments.filter(status='pending').filter(Q(due_at__date__range=(start,end)) |
        Q(due_at__isnull=True,created_at__date__range=(start,end)))
    # An expired Pix code is no longer a receivable payable through that charge.
    pending = pending.exclude(pix_charges__expires_at__lte=timezone.now())
    ledger = PlatformFinancialTransaction.objects.all()
    manual = total(paid_period(ledger.filter(type='income',status='paid')))
    gross = total(approved)+manual
    fee_ids=payments.filter(status__in=['paid','partially_refunded','refunded'],metadata__accounting__fee__isnull=False).exclude(metadata__accounting__fee=None).values_list('pk',flat=True)
    expense_rows=paid_period(ledger.filter(type='expense',status='paid')).exclude(provider_fee_payment_id__in=fee_ids)
    expenses = total(expense_rows)
    receivable = total(pending)+total(due_period(ledger.filter(type='income',status='pending')))
    payable = total(due_period(ledger.filter(type='expense',status='pending').exclude(provider_fee_payment_id__in=fee_ids)))
    net=gross-expenses-accounting['provider_fees']-accounting['refunds']
    return {**accounting,'gross':gross,'approved_income':total(approved),'manual_income':manual,'expenses':expenses,
        'net':net,'receivable':receivable,'payable':payable,
        'forecast':net+receivable-payable,
        'payments':approved.select_related('tenant').order_by('-paid_at','-pk')[:50],
        'expenses_list':expense_rows.order_by('-paid_at','-pk')[:50]}


@login_required
def dashboard(request):
    _guard(request.user)
    today = timezone.localdate()
    first = today.replace(day=1)
    import calendar
    last = date(today.year,today.month,calendar.monthrange(today.year,today.month)[1])
    form = PeriodForm(request.GET if request.GET else None, initial={'start':first,'end':last})
    start,end = first,last
    valid = not form.is_bound or form.is_valid()
    if form.is_bound and valid:
        start,end = form.cleaned_data['start'],form.cleaned_data['end']
    return render(request,'master/finance_dashboard.html',{'form':form,'start':start,'end':end,
        'totals':platform_totals(start,end) if valid else None})
