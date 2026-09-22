from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.shortcuts import get_object_or_404,redirect,render
from django.urls import reverse

from finance.models import Product
from scheduling.models import Professional,Service
from tenants.models import Tenant
from .models import Estimate,InspectionItem,Job,JobPhoto,JobStep
from .services import (
    add_estimate_item,add_product_item,add_service_item,close_command,consume_material,
    create_delivery_term,create_estimate,delivery_token,estimate_token,open_command,
    register_payment,send_estimate,transition_job,update_job_step,
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


class EstimateCreateForm(forms.Form):
    expires_at=forms.DateTimeField(
        required=False,label="Validade",
        widget=forms.DateTimeInput(attrs={"type":"datetime-local"},format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M"],
    )
    discount_amount=forms.DecimalField(
        required=False,min_value=0,decimal_places=2,max_digits=12,initial=0,label="Desconto"
    )


class EstimateItemForm(forms.Form):
    service=forms.ModelChoiceField(queryset=Service.objects.none(),required=False,label="Serviço")
    product=forms.ModelChoiceField(queryset=Product.objects.none(),required=False,label="Produto")
    description=forms.CharField(required=False,max_length=190,label="Descrição")
    quantity=forms.DecimalField(min_value=Decimal("0.001"),initial=1,decimal_places=3,max_digits=10)
    unit_price=forms.DecimalField(required=False,min_value=0,decimal_places=2,max_digits=12,label="Preço unitário")
    def __init__(self,*args,tenant=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["service"].queryset=Service.objects.filter(tenant=tenant,active=True).order_by("name")
        self.fields["product"].queryset=Product.objects.filter(tenant=tenant,active=True).order_by("name")
    def clean(self):
        data=super().clean()
        if data.get("service") and data.get("product"):
            raise forms.ValidationError("Escolha serviço ou produto, não ambos.")
        if not data.get("service") and not data.get("product") and not data.get("description"):
            raise forms.ValidationError("Informe serviço, produto ou descrição.")
        return data


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
    paid=sum((payment.amount for payment in command.payments.all()),Decimal("0")) if command else Decimal("0")
    estimates=[]
    for estimate in job.estimates.prefetch_related("items").order_by("-created_at"):
        try:
            public_url=request.build_absolute_uri(
                reverse("auto-public-estimate",args=[estimate_token(estimate)])
            )
        except Exception:
            public_url=""
        estimates.append({"obj":estimate,"public_url":public_url})
    delivery=getattr(job,"delivery_term",None)
    delivery_url=""
    if delivery:
        try:
            delivery_url=request.build_absolute_uri(
                reverse("auto-public-delivery",args=[delivery_token(delivery)])
            )
        except Exception:
            delivery_url=""
    return render(request,"auto/job_detail.html",{
        "tenant":tenant,"job":job,"command":command,"paid":paid,
        "balance":max(Decimal("0"),command.total_amount-paid) if command else Decimal("0"),
        "status_choices":Job.Status.choices,
        "inspection_form":InspectionForm(),"photo_form":PhotoForm(),
        "material_form":MaterialForm(tenant=tenant),
        "service_form":CommandItemForm(tenant=tenant,kind="service"),
        "product_form":CommandItemForm(tenant=tenant,kind="product"),
        "payment_form":PaymentForm(),
        "estimate_create_form":EstimateCreateForm(),
        "estimate_item_form":EstimateItemForm(tenant=tenant),
        "estimates":estimates,"delivery":delivery,"delivery_url":delivery_url,
        "step_status_choices":JobStep.Status.choices,
        "professionals":Professional.objects.filter(tenant=tenant,active=True).order_by("name"),
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
        elif action=="estimate_create":
            form=EstimateCreateForm(request.POST)
            if not form.is_valid(): raise ValidationError("; ".join(sum(form.errors.values(),[])))
            estimate,_token=create_estimate(job=job,user=request.user,**form.cleaned_data)
            messages.success(request,f"Orçamento #{estimate.pk} criado.")
        elif action=="estimate_item":
            estimate=get_object_or_404(Estimate,pk=request.POST.get("estimate_id"),job=job,tenant=tenant)
            form=EstimateItemForm(request.POST,tenant=tenant)
            if not form.is_valid(): raise ValidationError("; ".join(sum(form.errors.values(),[])))
            add_estimate_item(estimate=estimate,**form.cleaned_data)
            messages.success(request,"Item adicionado ao orçamento.")
        elif action=="estimate_send":
            estimate=get_object_or_404(Estimate,pk=request.POST.get("estimate_id"),job=job,tenant=tenant)
            send_estimate(estimate=estimate)
            messages.success(request,"Orçamento liberado para o cliente.")
        elif action=="step":
            step=get_object_or_404(JobStep,pk=request.POST.get("step_id"),job=job,tenant=tenant)
            professional=None
            if request.POST.get("professional"):
                professional=get_object_or_404(Professional,pk=request.POST.get("professional"),tenant=tenant)
            update_job_step(
                step=step,status=request.POST.get("step_status",""),
                professional=professional,notes=request.POST.get("step_notes",""),
            )
            messages.success(request,"Etapa atualizada.")
        elif action=="delivery_term":
            create_delivery_term(job=job)
            messages.success(request,"Termo público de entrega gerado.")
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
