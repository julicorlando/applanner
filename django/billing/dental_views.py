from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.shortcuts import get_object_or_404,render,redirect
from django.views.decorators.cache import never_cache
from .models import ModuleRequest,PixCharge,Subscription
from .dental_seats import owner_access,checkout_seats
from .pix_reconciliation import reconcile_pix_charge
from .module_services import _cycle_months


@login_required
@never_cache
def dental_request(request,pk):
    row=get_object_or_404(ModuleRequest,pk=pk,tenant_id=request.user.tenant_id,module__slug="dental-professional-extra")
    owner_access(row,request.user)
    charge=PixCharge.objects.filter(payment__purpose="dental-seat",payment__reference_id=row.pk,payment__tenant=row.tenant).select_related("payment").order_by("-created_at").first()
    if request.method=="POST":
        try:
            if request.POST.get("action")=="checkout":
                if request.POST.get("accept")!="yes":raise ValidationError("Confirme o valor inicial e o adicional recorrente antes de gerar o Pix.")
                charge=checkout_seats(row=row,user=request.user)
            elif request.POST.get("action")=="refresh":
                if not charge:raise ValidationError("Não há cobrança para consultar.")
                if reconcile_pix_charge(charge.pk):messages.success(request,"Pagamento confirmado. A vaga é liberada após a atualização financeira da assinatura.")
                else:messages.info(request,"Pagamento ainda não confirmado pelo provedor.")
            else:raise PermissionDenied
        except (ValidationError,ValueError,RuntimeError) as exc:messages.error(request,str(exc))
        return redirect("billing-dental-request",pk=row.pk)
    subscription=Subscription.objects.filter(tenant=row.tenant).order_by("-started_at").first()
    recurring=row.quoted_monthly_price*row.quantity*(_cycle_months(subscription.billing_cycle) if subscription else 1)
    return render(request,"billing/dental_request.html",{"row":row,"charge":charge,"recurring":recurring,"subscription":subscription})
