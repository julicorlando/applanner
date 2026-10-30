from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,SuspiciousOperation
from django.db import transaction
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from core.audit import append_audit
from accounts.permissions import has_capability
from finance.models import FinancialTransaction
from .models import ClinicalTreatmentPlan
from .clinic_views import numeric_id


def allowed(user):
    return bool(user.tenant_id and user.is_active and (
        user.role in {"owner","tenant-admin"} or has_capability(user,"finance.manage") or
        (user.role=="reception" and (user.tenant.metadata or {}).get("clinical_reception_billing") is True)))


@login_required
@never_cache
def clinical_finance(request):
    user=request.user
    if not user.tenant_id:raise PermissionDenied
    responsible=user.role in {"owner","tenant-admin"}
    if not allowed(user):raise PermissionDenied("Cobrança clínica não autorizada para este usuário.")
    if request.method=="POST":
        action=request.POST.get("action")
        if action=="reception-permission":
            if not responsible:raise PermissionDenied
            tenant=user.tenant;tenant.metadata={**(tenant.metadata or {}),"clinical_reception_billing":request.POST.get("enabled")=="yes"};tenant.save(update_fields=["metadata"])
            append_audit(tenant=tenant,user=user,request=request,action="clinical.reception.billing.permission",entity_type="Tenant",entity_id=tenant.pk,after={"enabled":tenant.metadata["clinical_reception_billing"]})
        elif action=="paid":
            if request.POST.get("confirm")!="yes":raise SuspiciousOperation("Confirme a baixa manual do recebimento.")
            with transaction.atomic():
                row=get_object_or_404(FinancialTransaction.objects.select_for_update(),pk=numeric_id(request.POST.get("transaction")),tenant_id=user.tenant_id,source_type="clinical-plan",type="income")
                if row.status=="pending":
                    row.status="paid";row.paid_at=timezone.now();row.payment_method=request.POST.get("payment_method","")[:40];row.save(update_fields=["status","paid_at","payment_method","updated_at"])
                    append_audit(tenant=user.tenant,user=user,request=request,action="clinical.receivable.manual.paid",entity_type="FinancialTransaction",entity_id=row.pk,after={"amount":str(row.amount),"manual":True})
        else:raise PermissionDenied
        return redirect("clinical-finance")
    rows=[]
    for tx in FinancialTransaction.objects.filter(tenant_id=user.tenant_id,source_type="clinical-plan").order_by("-created_at")[:200]:
        plan=ClinicalTreatmentPlan.objects.filter(pk=tx.source_id,entry__tenant_id=user.tenant_id).select_related("entry__customer").first()
        if plan:rows.append({"transaction":tx,"patient":plan.entry.customer.name,"plan_id":plan.pk})
    return render(request,"healthcare/clinical_finance.html",{"rows":rows,"responsible":responsible,"reception_enabled":(user.tenant.metadata or {}).get("clinical_reception_billing",False)})
