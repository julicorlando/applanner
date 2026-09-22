from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.shortcuts import get_object_or_404,redirect,render

from accounts.permissions import require_any_capability

from finance.models import Product
from scheduling.models import Appointment,Customer,Professional,Service
from .models import BarberCommand
from .services import (
    add_product_item,add_service_item,close_command,open_command,
    recalculate_command,register_payment,
)


def _tenant(request):
    if request.user.tenant_id:
        return request.user.tenant
    if request.user.is_superuser:
        tenant_id=request.session.get("portal_tenant_id")
        if tenant_id:
            from tenants.models import Tenant
            return Tenant.objects.filter(pk=tenant_id).first()
    raise PermissionDenied("Selecione uma empresa no portal operacional.")


class OpenCommandForm(forms.Form):
    appointment=forms.ModelChoiceField(queryset=Appointment.objects.none(),required=False,label="Agendamento")
    customer=forms.ModelChoiceField(queryset=Customer.objects.none(),required=False,label="Cliente")
    professional=forms.ModelChoiceField(queryset=Professional.objects.none(),required=False,label="Profissional")
    notes=forms.CharField(required=False,label="Observações",widget=forms.Textarea(attrs={"rows":3}))

    def __init__(self,*args,tenant=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["appointment"].queryset=Appointment.objects.filter(
            tenant=tenant,status__in=[Appointment.Status.PENDING,Appointment.Status.CONFIRMED,Appointment.Status.IN_PROGRESS]
        ).select_related("customer","service").order_by("-starts_at")[:500]
        self.fields["customer"].queryset=Customer.objects.filter(tenant=tenant,active=True).order_by("name")
        self.fields["professional"].queryset=Professional.objects.filter(tenant=tenant,active=True).order_by("name")

    def clean(self):
        cleaned=super().clean()
        if not cleaned.get("appointment") and not cleaned.get("customer"):
            raise forms.ValidationError("Informe um agendamento ou cliente.")
        return cleaned


class ServiceItemForm(forms.Form):
    service=forms.ModelChoiceField(queryset=Service.objects.none(),label="Serviço")
    professional=forms.ModelChoiceField(queryset=Professional.objects.none(),required=False,label="Profissional")
    quantity=forms.DecimalField(min_value=Decimal("0.001"),initial=1,decimal_places=3,max_digits=10)
    unit_price=forms.DecimalField(required=False,min_value=0,decimal_places=2,max_digits=12,label="Preço unitário")
    discount=forms.DecimalField(required=False,min_value=0,initial=0,decimal_places=2,max_digits=12,label="Desconto")

    def __init__(self,*args,tenant=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["service"].queryset=Service.objects.filter(tenant=tenant,active=True).order_by("name")
        self.fields["professional"].queryset=Professional.objects.filter(tenant=tenant,active=True).order_by("name")


class ProductItemForm(forms.Form):
    product=forms.ModelChoiceField(queryset=Product.objects.none(),label="Produto")
    professional=forms.ModelChoiceField(queryset=Professional.objects.none(),required=False,label="Profissional")
    quantity=forms.DecimalField(min_value=Decimal("0.001"),initial=1,decimal_places=3,max_digits=10)
    unit_price=forms.DecimalField(required=False,min_value=0,decimal_places=2,max_digits=12,label="Preço unitário")
    discount=forms.DecimalField(required=False,min_value=0,initial=0,decimal_places=2,max_digits=12,label="Desconto")

    def __init__(self,*args,tenant=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["product"].queryset=Product.objects.filter(tenant=tenant,active=True).order_by("name")
        self.fields["professional"].queryset=Professional.objects.filter(tenant=tenant,active=True).order_by("name")


class PaymentForm(forms.Form):
    method=forms.CharField(max_length=40,label="Forma de pagamento")
    amount=forms.DecimalField(min_value=Decimal("0.01"),decimal_places=2,max_digits=12,label="Valor")


@login_required
def command_create(request):
    require_any_capability(request.user,"barber.manage")
    tenant=_tenant(request)
    form=OpenCommandForm(request.POST or None,tenant=tenant)
    if request.method=="POST" and form.is_valid():
        try:
            command=open_command(tenant=tenant,user=request.user,**form.cleaned_data)
            messages.success(request,f"Comanda #{command.pk} aberta.")
            return redirect("barber-command-detail",pk=command.pk)
        except ValidationError as exc:
            form.add_error(None,exc)
    return render(request,"barber/command_open.html",{"tenant":tenant,"form":form})


@login_required
def command_detail(request,pk):
    require_any_capability(request.user,"barber.manage")
    tenant=_tenant(request)
    command=get_object_or_404(
        BarberCommand.objects.select_related("customer","professional","appointment").prefetch_related("items","payments"),
        pk=pk,tenant=tenant,
    )
    paid=sum((row.amount for row in command.payments.all()),Decimal("0"))
    balance=max(Decimal("0"),command.total_amount-paid)
    return render(request,"barber/command_detail.html",{
        "tenant":tenant,"command":command,"paid":paid,"balance":balance,
        "service_form":ServiceItemForm(tenant=tenant),
        "product_form":ProductItemForm(tenant=tenant),
        "payment_form":PaymentForm(),
    })


@login_required
def command_action(request,pk):
    require_any_capability(request.user,"barber.manage")
    if request.method!="POST":
        raise PermissionDenied
    tenant=_tenant(request)
    command=get_object_or_404(BarberCommand,pk=pk,tenant=tenant)
    action=request.POST.get("action")
    try:
        if action=="service":
            form=ServiceItemForm(request.POST,tenant=tenant)
            if not form.is_valid():
                raise ValidationError("; ".join(sum(form.errors.values(),[])))
            add_service_item(command=command,**form.cleaned_data)
            messages.success(request,"Serviço adicionado.")
        elif action=="product":
            form=ProductItemForm(request.POST,tenant=tenant)
            if not form.is_valid():
                raise ValidationError("; ".join(sum(form.errors.values(),[])))
            add_product_item(command=command,**form.cleaned_data)
            messages.success(request,"Produto adicionado.")
        elif action=="payment":
            form=PaymentForm(request.POST)
            if not form.is_valid():
                raise ValidationError("; ".join(sum(form.errors.values(),[])))
            register_payment(command=command,user=request.user,**form.cleaned_data)
            messages.success(request,"Pagamento registrado.")
        elif action=="adjust":
            command.discount_amount=Decimal(request.POST.get("discount_amount") or "0")
            command.surcharge_amount=Decimal(request.POST.get("surcharge_amount") or "0")
            command.tip_amount=Decimal(request.POST.get("tip_amount") or "0")
            professional_id=request.POST.get("tip_professional")
            command.tip_professional_id=int(professional_id) if professional_id else None
            command.save(update_fields=["discount_amount","surcharge_amount","tip_amount","tip_professional","updated_at"])
            recalculate_command(command)
            messages.success(request,"Valores da comanda atualizados.")
        elif action=="close":
            close_command(command=command,user=request.user)
            messages.success(request,"Comanda fechada e financeiro atualizado.")
        else:
            raise ValidationError("Ação inválida.")
    except (ValidationError,ValueError) as exc:
        messages.error(request,str(exc))
    return redirect("barber-command-detail",pk=command.pk)
