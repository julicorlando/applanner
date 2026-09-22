from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.shortcuts import get_object_or_404,redirect,render

from finance.models import Product
from scheduling.models import Professional,Service
from tenants.models import Tenant
from .models import InspectionItem,Job,JobPhoto
from .services import (
    add_product_item,add_service_item,close_command,consume_material,
    open_command,register_payment,transition_job,
)


def _tenant(request):
    if request.user.tenant_id:
        return request.user.tenant
    if request.user.is_superuser:
        tenant_id=request.session.get("portal_tenant_id")
        if tenant_id:
            return Tenant.objects.filter(pk=tenant_id).first()
    raise PermissionDenied("Selecione uma empresa no portal.")


class InspectionForm(forms.ModelForm):
    class Meta:
        model=InspectionItem
        fields=["phase","area","item_label","condition_status","notes"]


class PhotoForm(forms.ModelForm):
    class Meta:
        model=JobPhoto
        fields=["phase","file","caption"]


class MaterialForm(forms.Form):
    product=forms.ModelChoiceField(queryset=Product.objects.none(),label="Material/produto")
    quantity=forms.DecimalField(min_value=Decimal("0.001"),decimal_places=3,max_digits=10)
    dilution=forms.CharField(required=False,max_length=60,label="Diluição")
    batch_lot=forms.CharField(required=False,max_length=100,label="Lote")
    notes=forms.CharField(required=False,max_length=500,label="Observações")
    def __init__(self,*args,tenant=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["product"].queryset=Product.objects.filter(tenant=tenant,active=True).order_by("name")


class CommandItemForm(forms.Form):
    service=forms.ModelChoiceField(queryset=Service.objects.none(),required=False,label="Serviço")
    product=forms.ModelChoiceField(queryset=Product.objects.none(),required=False,label="Produto")
    professional=forms.ModelChoiceField(queryset=Professional.objects.none(),required=False,label="Profissional")
    quantity=forms.DecimalField(min_value=Decimal("0.001"),initial=1,decimal_places=3,max_digits=10)
    unit_price=forms.DecimalField(required=False,min_value=0,decimal_places=2,max_digits=12,label="Preço unitário")
    discount=forms.DecimalField(required=False,min_value=0,initial=0,decimal_places=2,max_digits=12,label="Desconto")
    def __init__(self,*args,tenant=None,kind="service",**kwargs):
        super().__init__(*args,**kwargs)
        self.kind=kind
        self.fields["service"].queryset=Service.objects.filter(tenant=tenant,active=True).order_by("name")
        self.fields["product"].queryset=Product.objects.filter(tenant=tenant,active=True).order_by("name")
        self.fields["professional"].queryset=Professional.objects.filter(tenant=tenant,active=True).order_by("name")
        if kind=="service":
            self.fields.pop("product")
        else:
            self.fields.pop("service")


class PaymentForm(forms.Form):
    payment_method=forms.CharField(max_length=20,label="Forma de pagamento")
    amount=forms.DecimalField(min_value=Decimal("0.01"),decimal_places=2,max_digits=12,label="Valor")
    provider=forms.CharField(required=False,max_length=50)
    provider_reference=forms.CharField(required=False,max_length=190,label="Referência")


@login_required
def job_detail(request,pk):
    tenant=_tenant(request)
    job=get_object_or_404(
        Job.objects.select_related("appointment__customer","appointment__service","vehicle","bay","assigned_professional"),
        pk=pk,tenant=tenant,
    )
    command=getattr(job,"command",None)
    paid=sum((p.amount for p in command.payments.all()),Decimal("0")) if command else Decimal("0")
    return render(request,"auto/job_detail.html",{
        "tenant":tenant,"job":job,"command":command,"paid":paid,
        "balance":max(Decimal("0"),command.total_amount-paid) if command else Decimal("0"),
        "status_choices":Job.Status.choices,
        "inspection_form":InspectionForm(),"photo_form":PhotoForm(),
        "material_form":MaterialForm(tenant=tenant),
        "service_form":CommandItemForm(tenant=tenant,kind="service"),
        "product_form":CommandItemForm(tenant=tenant,kind="product"),
        "payment_form":PaymentForm(),
    })


@login_required
def job_action(request,pk):
    if request.method!="POST":
        raise PermissionDenied
    tenant=_tenant(request)
    job=get_object_or_404(Job,pk=pk,tenant=tenant)
    action=request.POST.get("action")
    try:
        if action=="status":
            transition_job(job=job,new_status=request.POST.get("status",""),user=request.user,notes=request.POST.get("notes",""))
            messages.success(request,"Status da OS atualizado.")
        elif action=="inspection":
            form=InspectionForm(request.POST)
            if not form.is_valid(): raise ValidationError("; ".join(sum(form.errors.values(),[])))
            row=form.save(commit=False); row.tenant=tenant; row.job=job; row.created_by=request.user; row.save()
            messages.success(request,"Inspeção registrada.")
        elif action=="photo":
            form=PhotoForm(request.POST,request.FILES)
            if not form.is_valid(): raise ValidationError("; ".join(sum(form.errors.values(),[])))
            row=form.save(commit=False); row.tenant=tenant; row.job=job; row.created_by=request.user; row.save()
            messages.success(request,"Foto adicionada.")
        elif action=="material":
            form=MaterialForm(request.POST,tenant=tenant)
            if not form.is_valid(): raise ValidationError("; ".join(sum(form.errors.values(),[])))
            consume_material(job=job,user=request.user,**form.cleaned_data)
            messages.success(request,"Material consumido e estoque atualizado.")
        elif action=="open_command":
            open_command(job=job,user=request.user)
            messages.success(request,"Comanda automotiva aberta.")
        else:
            raise ValidationError("Ação inválida.")
    except (ValidationError,ValueError) as exc:
        messages.error(request,str(exc))
    return redirect("auto-job-detail",pk=job.pk)


@login_required
def command_action(request,pk):
    if request.method!="POST":
        raise PermissionDenied
    tenant=_tenant(request)
    from .models import AutoCommand
    command=get_object_or_404(AutoCommand.objects.select_related("job"),pk=pk,tenant=tenant)
    action=request.POST.get("action")
    try:
        if action=="service":
            form=CommandItemForm(request.POST,tenant=tenant,kind="service")
            if not form.is_valid(): raise ValidationError("; ".join(sum(form.errors.values(),[])))
            add_service_item(command=command,**form.cleaned_data)
            messages.success(request,"Serviço adicionado à comanda.")
        elif action=="product":
            form=CommandItemForm(request.POST,tenant=tenant,kind="product")
            if not form.is_valid(): raise ValidationError("; ".join(sum(form.errors.values(),[])))
            add_product_item(command=command,**form.cleaned_data)
            messages.success(request,"Produto adicionado à comanda.")
        elif action=="payment":
            form=PaymentForm(request.POST)
            if not form.is_valid(): raise ValidationError("; ".join(sum(form.errors.values(),[])))
            register_payment(command=command,user=request.user,**form.cleaned_data)
            messages.success(request,"Pagamento registrado.")
        elif action=="close":
            close_command(command=command,user=request.user)
            messages.success(request,"Comanda encerrada, OS entregue e financeiro lançado.")
        else:
            raise ValidationError("Ação inválida.")
    except (ValidationError,ValueError) as exc:
        messages.error(request,str(exc))
    return redirect("auto-job-detail",pk=command.job_id)
