from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied,SuspiciousOperation,ValidationError
from django.db import transaction
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from core.audit import append_audit
from accounts.permissions import has_capability
from finance.models import FinancialTransaction,CashSession
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
            try:
                with transaction.atomic():
                    if user.role=='reception':
                        from finance.clinic_services import lock_company
                        tenant=lock_company(user)
                    row=get_object_or_404(FinancialTransaction.objects.select_for_update(),pk=numeric_id(request.POST.get("transaction")),tenant_id=user.tenant_id,source_type="clinical-plan",type="income")
                    if row.status=="pending":
                        method=request.POST.get("payment_method","")
                        if method not in {'pix','card','cash','transfer'}:raise SuspiciousOperation("Modalidade inválida.")
                        if user.role=='reception':
                            from finance.clinic_services import active_cash
                            from finance.clinic_models import ClinicPaymentMethod
                            from core.unit_scope import selected_unit
                            plan=get_object_or_404(ClinicalTreatmentPlan,pk=row.source_id,entry__tenant_id=user.tenant_id,entry__professional__tenant_id=user.tenant_id)
                            unit=row.unit or plan.entry.professional.unit or selected_unit(request,tenant)
                            if unit and (unit.tenant_id!=tenant.pk or not unit.active):raise PermissionDenied
                            active_cash(tenant,unit)
                            if method=='transfer' or not ClinicPaymentMethod.objects.filter(tenant=tenant,kind=method,active=True).exists():
                                raise ValidationError('Esta modalidade não está ativa no caixa da clínica.')
                            row.unit=unit
                        row.status="paid";row.paid_at=timezone.now();row.payment_method=method;row.save(update_fields=["unit","status","paid_at","payment_method","updated_at"])
                        append_audit(tenant=user.tenant,user=user,request=request,action="clinical.receivable.manual.paid",entity_type="FinancialTransaction",entity_id=row.pk,after={"amount":str(row.amount),"manual":True})
            except ValidationError as exc:
                messages.error(request,' '.join(exc.messages))
        else:raise PermissionDenied
        return redirect("clinical-finance")
    rows=[]
    from core.unit_scope import selected_unit
    from finance.clinic_models import ClinicPaymentMethod
    reception=user.role=='reception'
    default_unit=selected_unit(request,user.tenant) if reception else None
    open_units=set(CashSession.objects.filter(tenant_id=user.tenant_id,status='open').values_list('unit_id',flat=True)) if reception else set()
    reception_methods=list(ClinicPaymentMethod.objects.filter(tenant_id=user.tenant_id,active=True).values_list('kind',flat=True).distinct()) if reception else []
    for tx in FinancialTransaction.objects.filter(tenant_id=user.tenant_id,source_type="clinical-plan").order_by("-created_at")[:200]:
        plan=ClinicalTreatmentPlan.objects.filter(pk=tx.source_id,entry__tenant_id=user.tenant_id).select_related("entry__customer","entry__professional__unit").first()
        if plan:
            unit_id=tx.unit_id or plan.entry.professional.unit_id or (default_unit.pk if default_unit else None)
            rows.append({"transaction":tx,"patient":plan.entry.customer.name,"plan_id":plan.pk,"can_receive":not reception or unit_id in open_units})
    return render(request,"healthcare/clinical_finance.html",{"rows":rows,"responsible":responsible,"reception_methods":reception_methods,"reception_enabled":(user.tenant.metadata or {}).get("clinical_reception_billing",False)})
