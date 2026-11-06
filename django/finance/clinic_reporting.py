"""Administrative metadata for the clinic's existing ledger. Never decrypt records."""
from django.core.paginator import Paginator
from .models import FinancialTransaction
from .clinic_models import ClinicReceipt, ClinicExpense


def daily_ledger(*,tenant,unit,start,end,page=None):
    rows=FinancialTransaction.objects.filter(tenant=tenant,unit=unit,status='paid',paid_at__gte=start,paid_at__lte=end).order_by('-paid_at','-pk')
    result=Paginator(rows,50).get_page(page)
    ids=[row.pk for row in result.object_list]
    receipts={row.transaction_id:row for row in ClinicReceipt.objects.filter(transaction_id__in=ids,session__tenant=tenant,installment__charge__tenant=tenant,installment__charge__customer__tenant=tenant).select_related('recorded_by','installment__charge__customer','installment__charge__professional__clinical_registration')}
    expenses={row.transaction_id:row for row in ClinicExpense.objects.filter(transaction_id__in=ids,session__tenant=tenant).select_related('recorded_by')}
    from healthcare.models import ClinicalTreatmentPlan
    plans={row.pk:row for row in ClinicalTreatmentPlan.objects.filter(pk__in=[tx.source_id for tx in result.object_list if tx.source_type=='clinical-plan'],entry__tenant=tenant,entry__customer__tenant=tenant,entry__professional__tenant=tenant).select_related('entry__customer','entry__professional__clinical_registration').only('id','entry_id','entry__customer__name','entry__professional__name','entry__professional__tenant_id','entry__professional__clinical_registration__professional_name')}
    for row in result.object_list:
        row.patient_name='—';row.professional_name='—';row.operator_name='Não informado no lançamento'
        receipt=receipts.get(row.pk)
        profile=None
        if receipt:
            charge=receipt.installment.charge
            row.patient_name=charge.customer.name;profile=charge.professional
            row.operator_name=receipt.recorded_by.get_full_name() or receipt.recorded_by.email
        elif row.pk in expenses:
            operator=expenses[row.pk].recorded_by
            row.operator_name=operator.get_full_name() or operator.email
        elif row.source_type=='clinical-plan' and row.source_id in plans:
            plan=plans[row.source_id];row.patient_name=plan.entry.customer.name;profile=plan.entry.professional
        if profile and profile.tenant_id==tenant.pk:
            registration=getattr(profile,'clinical_registration',None)
            row.professional_name=(registration.professional_name if registration else '') or profile.name
    return result
