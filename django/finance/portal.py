from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.shortcuts import get_object_or_404,redirect,render

from accounts.permissions import require_any_capability

from scheduling.models import Customer,Professional
from tenants.models import Tenant,Unit
from .models import CashSession,Product,ProfessionalCommission,Sale
from .services import cancel_sale,close_cash_session,create_sale,open_cash_session,pay_commission


def _tenant(request):
    if request.user.tenant_id:
        return request.user.tenant
    if request.user.is_superuser:
        tid=request.session.get("portal_tenant_id")
        if tid:
            return Tenant.objects.filter(pk=tid).first()
    raise PermissionDenied("Selecione uma empresa.")


class SaleForm(forms.Form):
    product=forms.ModelChoiceField(queryset=Product.objects.none(),label="Produto")
    quantity=forms.DecimalField(min_value=Decimal("0.001"),decimal_places=3,max_digits=12,initial=1)
    unit_price=forms.DecimalField(required=False,min_value=0,decimal_places=2,max_digits=12,label="Preço unitário")
    item_discount=forms.DecimalField(required=False,min_value=0,decimal_places=2,max_digits=12,initial=0,label="Desconto do item")
    sale_discount=forms.DecimalField(required=False,min_value=0,decimal_places=2,max_digits=12,initial=0,label="Desconto da venda")
    payment_method=forms.CharField(max_length=40,label="Pagamento")
    customer=forms.ModelChoiceField(queryset=Customer.objects.none(),required=False,label="Cliente")
    professional=forms.ModelChoiceField(queryset=Professional.objects.none(),required=False,label="Profissional")
    unit=forms.ModelChoiceField(queryset=Unit.objects.none(),required=False,label="Unidade")
    def __init__(self,*args,tenant=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["product"].queryset=Product.objects.filter(tenant=tenant,active=True).order_by("name")
        self.fields["customer"].queryset=Customer.objects.filter(tenant=tenant,active=True).order_by("name")
        self.fields["professional"].queryset=Professional.objects.filter(tenant=tenant,active=True).order_by("name")
        self.fields["unit"].queryset=Unit.objects.filter(tenant=tenant,active=True).order_by("name")


class CashOpenForm(forms.Form):
    unit=forms.ModelChoiceField(queryset=Unit.objects.none(),required=False)
    opening_amount=forms.DecimalField(min_value=0,decimal_places=2,max_digits=12,initial=0,label="Valor inicial")
    notes=forms.CharField(required=False,widget=forms.Textarea(attrs={"rows":2}))
    def __init__(self,*args,tenant=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["unit"].queryset=Unit.objects.filter(tenant=tenant,active=True)


@login_required
def pos(request):
    require_any_capability(request.user,"finance.manage")
    tenant=_tenant(request)
    form=SaleForm(request.POST or None,tenant=tenant)
    if request.method=="POST" and form.is_valid():
        d=form.cleaned_data
        try:
            sale=create_sale(
                tenant=tenant,user=request.user,
                items=[{"product_id":d["product"].pk,"quantity":d["quantity"],
                        "unit_price":d["unit_price"] if d["unit_price"] is not None else d["product"].sale_price,
                        "discount":d["item_discount"] or 0}],
                payment_method=d["payment_method"],unit=d["unit"],
                customer=d["customer"],professional=d["professional"],
                discount=d["sale_discount"] or 0,
            )
            messages.success(request,f"Venda #{sale.pk} concluída.")
            return redirect("finance-pos")
        except ValidationError as exc: form.add_error(None,exc)
    return render(request,"finance/pos.html",{
        "form":form,"sales":Sale.objects.filter(tenant=tenant).select_related("customer","professional").order_by("-created_at")[:80],
    })


@login_required
def sale_cancel(request,pk):
    require_any_capability(request.user,"finance.manage")
    if request.method!="POST": raise PermissionDenied
    tenant=_tenant(request)
    sale=get_object_or_404(Sale,pk=pk,tenant=tenant)
    try:
        cancel_sale(sale=sale,user=request.user,reason=request.POST.get("reason","Cancelamento operacional"))
        messages.success(request,"Venda cancelada e estoque estornado.")
    except ValidationError as exc: messages.error(request,str(exc))
    return redirect("finance-pos")


@login_required
def cash(request):
    require_any_capability(request.user,"finance.manage")
    tenant=_tenant(request)
    open_session=CashSession.objects.filter(tenant=tenant,status=CashSession.Status.OPEN).select_related("unit","opened_by").first()
    form=CashOpenForm(request.POST or None,tenant=tenant)
    if request.method=="POST":
        action=request.POST.get("action")
        try:
            if action=="open" and form.is_valid():
                open_cash_session(tenant=tenant,user=request.user,**form.cleaned_data)
                messages.success(request,"Caixa aberto.")
            elif action=="close" and open_session:
                close_cash_session(session=open_session,user=request.user,closing_amount=request.POST.get("closing_amount"),notes=request.POST.get("notes",""))
                messages.success(request,"Caixa fechado e conferido.")
        except (ValidationError,ValueError) as exc: messages.error(request,str(exc))
        return redirect("finance-cash")
    return render(request,"finance/cash.html",{
        "session":open_session,"form":form,
        "history":CashSession.objects.filter(tenant=tenant).select_related("unit").order_by("-opened_at")[:50],
    })


@login_required
def commissions(request):
    require_any_capability(request.user,"finance.manage")
    tenant=_tenant(request)
    if request.method=="POST":
        row=get_object_or_404(ProfessionalCommission,pk=request.POST.get("commission"),tenant=tenant)
        try:
            pay_commission(commission=row,user=request.user)
            messages.success(request,"Comissão marcada como paga e despesa registrada.")
        except ValidationError as exc: messages.error(request,str(exc))
        return redirect("finance-commissions")
    return render(request,"finance/commissions.html",{
        "rows":ProfessionalCommission.objects.filter(tenant=tenant).select_related("professional").order_by("-created_at")[:200]
    })
