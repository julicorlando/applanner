"""Owner-facing connection for the tenant's own checkout provider."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from requests.exceptions import RequestException

from core.crypto import encrypt_text
from finance.models import TenantBankAccount
from .models import PaymentGateway, TenantPaymentConnection
from .payment_services import configure_tenant_mercadopago
from scheduling.models import TenantScheduleSettings


class TenantBankAccountForm(forms.Form):
    bank_name=forms.CharField(max_length=120,label="Banco / instituição")
    bank_code=forms.CharField(max_length=10,required=False,label="Código do banco (opcional)")
    account_type=forms.ChoiceField(choices=TenantBankAccount.AccountType.choices,label="Tipo de conta")
    agency=forms.CharField(max_length=30,required=False,label="Agência")
    account=forms.CharField(max_length=40,required=False,label="Conta")
    holder_name=forms.CharField(max_length=150,label="Titular")
    pix_key_type=forms.ChoiceField(required=False,label="Tipo de chave Pix",choices=[
        ("","Sem chave Pix"),("cpf","CPF"),("cnpj","CNPJ"),("email","E-mail"),
        ("phone","Telefone"),("random","Aleatória"),
    ])
    pix_key=forms.CharField(max_length=190,required=False,label="Chave Pix")
    is_primary=forms.BooleanField(required=False,label="Conta principal")

    def clean(self):
        data=super().clean()
        if data.get("pix_key_type") and not data.get("pix_key"):
            self.add_error("pix_key","Informe a chave Pix.")
        return data


class TenantGatewayForm(forms.Form):
    environment=forms.ChoiceField(choices=PaymentGateway.Environment.choices,label="Ambiente")
    public_key=forms.CharField(max_length=190,required=False,label="Chave pública")
    access_token=forms.CharField(label="Token de acesso",widget=forms.PasswordInput(attrs={"autocomplete":"new-password"}))
    webhook_secret=forms.CharField(min_length=16,label="Chave secreta do webhook",widget=forms.PasswordInput(attrs={"autocomplete":"new-password"}))


@login_required
def tenant_gateway(request):
    if not request.user.is_superuser and request.user.role!="owner":
        raise PermissionDenied("Somente o responsável pode conectar a conta de pagamentos.")
    tenant=request.user.tenant
    if request.user.is_superuser:
        from core.portal import _tenant
        tenant=_tenant(request)
    if not tenant or tenant.deleted_at:
        raise PermissionDenied("Selecione uma empresa ativa.")
    webhook_url=request.build_absolute_uri(f"/webhooks/tenant/mercadopago/{tenant.slug}/")
    connections=TenantPaymentConnection.objects.filter(tenant=tenant,provider="mercadopago").order_by("environment")
    connected=connections.filter(status=TenantPaymentConnection.Status.CONNECTED).exists()
    bank_accounts=TenantBankAccount.objects.filter(tenant=tenant,active=True).order_by("-is_primary","bank_name","id")
    schedule_settings,_=TenantScheduleSettings.objects.get_or_create(tenant=tenant)
    action=request.POST.get("action") if request.method=="POST" else ""
    if request.method=="POST" and action=="bank_add":
        bank_form=TenantBankAccountForm(request.POST)
        if bank_form.is_valid():
            data=bank_form.cleaned_data
            with transaction.atomic():
                if data["is_primary"]:
                    TenantBankAccount.objects.filter(tenant=tenant,is_primary=True).update(is_primary=False)
                TenantBankAccount.objects.create(
                    tenant=tenant,bank_name=data["bank_name"],bank_code=data["bank_code"],
                    account_type=data["account_type"],
                    agency_encrypted=encrypt_text(data["agency"]) if data["agency"] else "",
                    account_encrypted=encrypt_text(data["account"]) if data["account"] else "",
                    holder_name=data["holder_name"],pix_key_type=data["pix_key_type"],
                    pix_key_encrypted=encrypt_text(data["pix_key"]) if data["pix_key"] else "",
                    is_primary=data["is_primary"] or not bank_accounts.exists(),
                    active=True,created_by=request.user,
                )
            messages.success(request,"Conta bancária cadastrada.")
            return redirect("tenant-payment-gateway")
    else:
        bank_form=TenantBankAccountForm()
    if request.method=="POST" and action=="bank_deactivate":
        row=get_object_or_404(TenantBankAccount,pk=request.POST.get("bank_id"),tenant=tenant,active=True)
        row.active=False
        row.is_primary=False
        row.save(update_fields=["active","is_primary","updated_at"])
        messages.success(request,"Conta bancária removida do cadastro.")
        return redirect("tenant-payment-gateway")
    if request.method=="POST" and action=="booking_payments":
        if not connected and request.POST.get("enabled")=="on":
            messages.error(request,"Conecte um provedor de cobrança online antes de ativar o pagamento no agendamento.")
        else:
            schedule_settings.online_booking_payments_enabled=request.POST.get("enabled")=="on"
            schedule_settings.save(update_fields=["online_booking_payments_enabled","updated_at"])
            messages.success(request,"Pagamento no agendamento atualizado.")
        return redirect("tenant-payment-gateway")
    form=TenantGatewayForm(request.POST if action=="provider_connect" else None)
    if request.method=="POST" and action=="provider_connect" and form.is_valid():
        try:
            configure_tenant_mercadopago(tenant=tenant,created_by=request.user,**form.cleaned_data)
        except (ValueError,RuntimeError,RequestException):
            form.add_error(None,"Não foi possível validar a conta. Confira ambiente, credenciais e chave do webhook.")
        else:
            messages.success(request,"Provedor de cobrança online validado e conectado.")
            return redirect("tenant-payment-gateway")
    return render(request,"billing/tenant_gateway.html",{
        "tenant":tenant,"form":form,"bank_form":bank_form,"bank_accounts":bank_accounts,
        "connections":connections,"webhook_url":webhook_url,
        "schedule_settings":schedule_settings,
        "connected":connected,"show_form":not connected or request.GET.get("alterar")=="1" or bool(form.errors),
    })
