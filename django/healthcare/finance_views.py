from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied,SuspiciousOperation,ValidationError
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


def receive_plan(request,transaction_id,method_id,paid_on=""):
    """Pays a treatment-plan receivable as a line on the clinic's cash sheet of that day, linked to the plan's dentist.
    The receivable's own transaction becomes the line's transaction, so nothing is counted twice."""
    from datetime import date
    from core.unit_scope import selected_unit
    from finance.clinic_cash import add_entry
    from finance.clinic_models import ClinicPaymentMethod
    from finance.clinic_services import business_today,day_sheet,lock_company
    import uuid
    user=request.user
    with transaction.atomic():
        tenant=lock_company(user)
        row=get_object_or_404(FinancialTransaction.objects.select_for_update(),pk=transaction_id,tenant_id=tenant.pk,
                              source_type="clinical-plan",type="income")
        if row.status!="pending":raise ValidationError("Este recebível já foi baixado.")
        plan=get_object_or_404(ClinicalTreatmentPlan.objects.select_related("entry__customer","entry__professional__unit"),
                               pk=row.source_id,entry__tenant_id=tenant.pk)
        professional=plan.entry.professional
        unit=row.unit or professional.unit or selected_unit(request,tenant)
        if unit and (unit.tenant_id!=tenant.pk or not unit.active):raise PermissionDenied
        method=ClinicPaymentMethod.objects.filter(pk=method_id if str(method_id).isdigit() else 0,tenant=tenant,active=True).first()
        if method is None:raise ValidationError("Escolha uma forma de pagamento ativa no caixa da clínica.")
        today=business_today(tenant)
        try:day=date.fromisoformat(paid_on) if paid_on else today
        except ValueError:raise ValidationError("Data do recebimento inválida.")
        if day>today:raise ValidationError("A data do recebimento não pode ser no futuro.")
        session=day_sheet(tenant,unit,professional,user,day=day)
        entry=add_entry(user=user,session_id=session.pk,customer=plan.entry.customer,professional=professional,professional_name="",
                        dentist_amount="0",clinic_amount=row.amount,other_amount="0",method=method,
                        notes=f"Plano de tratamento #{plan.pk}",request_id=uuid.uuid5(uuid.NAMESPACE_URL,f"clinical-plan-pay:{row.pk}"),
                        receivable=row)
        append_audit(tenant=tenant,user=user,request=request,action="clinical.receivable.manual.paid",entity_type="FinancialTransaction",
                     entity_id=row.pk,after={"amount":str(row.amount),"manual":True,"cash_entry":entry.pk,"sheet":session.pk})
        return entry


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
                receive_plan(request,numeric_id(request.POST.get("transaction")),request.POST.get("method",""),request.POST.get("paid_on",""))
                messages.success(request,"Recebimento lançado na folha do caixa do dentista do plano.")
            except ValidationError as exc:
                messages.error(request,' '.join(exc.messages))
        else:raise PermissionDenied
        return redirect("clinical-finance")
    rows=[]
    from finance.clinic_models import ClinicPaymentMethod
    methods=list(ClinicPaymentMethod.objects.filter(tenant_id=user.tenant_id,active=True).order_by("kind","name"))
    for tx in FinancialTransaction.objects.filter(tenant_id=user.tenant_id,source_type="clinical-plan").exclude(status="cancelled").order_by("-created_at")[:200]:
        plan=ClinicalTreatmentPlan.objects.filter(pk=tx.source_id,entry__tenant_id=user.tenant_id).select_related("entry__customer","entry__professional").first()
        if plan:
            entry=getattr(tx,"clinic_cash_entry",None) if tx.status=="paid" else None
            rows.append({"transaction":tx,"patient":plan.entry.customer.name,"plan_id":plan.pk,"professional":plan.entry.professional.name,
                         "entry":entry,"can_receive":bool(methods)})
    return render(request,"healthcare/clinical_finance.html",{"rows":rows,"responsible":responsible,"methods":methods,"today":timezone.localdate(),"reception_enabled":(user.tenant.metadata or {}).get("clinical_reception_billing",False)})
