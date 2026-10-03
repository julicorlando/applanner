"""Cadastro bancário e conexão do provedor de cobrança da empresa."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render
from requests.exceptions import RequestException

from core.crypto import encrypt_json
from scheduling.models import TenantScheduleSettings
from .models import PaymentGateway, TenantBankAccount, TenantPaymentConnection
from .payment_services import configure_tenant_mercadopago


COMMON_BANKS=[
    ("001","Banco do Brasil"),("033","Santander"),("104","Caixa Econômica Federal"),
    ("237","Bradesco"),("341","Itaú Unibanco"),("077","Banco Inter"),
    ("260","Nubank"),("290","PagBank"),("336","C6 Bank"),("380","PicPay"),
]


class BankAccountForm(forms.Form):
    bank_code=forms.CharField(max_length=12,required=False,label="Código do banco")
    bank_name=forms.CharField(max_length=120,label="Banco / instituição")
    holder_name=forms.CharField(max_length=160,label="Titular da conta")
    holder_document=forms.CharField(max_length=32,label="CPF/CNPJ do titular")
    branch=forms.CharField(max_length=20,required=False,label="Agência")
    account_number=forms.CharField(max_length=40,label="Conta")
    account_type=forms.ChoiceField(
        choices=[("checking","Conta corrente"),("savings","Poupança"),("payment","Conta de pagamento")],
        label="Tipo de conta",
    )
    pix_key_type=forms.ChoiceField(
        required=False,choices=[("","Sem chave Pix"),("cpf_cnpj","CPF/CNPJ"),("email","E-mail"),
                                ("phone","Telefone"),("random","Chave aleatória")],
        label="Tipo da chave Pix",
    )
    pix_key=forms.CharField(max_length=190,required=False,label="Chave Pix")
    is_primary=forms.BooleanField(required=False,label="Usar como conta principal")

    def clean(self):
        data=super().clean()
        if data.get("pix_key_type") and not (data.get("pix_key") or "").strip():
            self.add_error("pix_key","Informe a chave Pix.")
        return data


class TenantGatewayForm(forms.Form):
    environment=forms.ChoiceField(choices=PaymentGateway.Environment.choices,label="Ambiente")
    public_key=forms.CharField(max_length=190,required=False,label="Chave pública")
    access_token=forms.CharField(label="Token de acesso",widget=forms.PasswordInput(attrs={"autocomplete":"new-password"}))
    webhook_secret=forms.CharField(min_length=16,label="Chave secreta do webhook",widget=forms.PasswordInput(attrs={"autocomplete":"new-password"}))


def _mask_last4(value):
    cleaned=(value or "").strip()
    return cleaned[-4:] if cleaned else ""


@login_required
def tenant_gateway(request):
    if not request.user.is_superuser and request.user.role!="owner":
        raise PermissionDenied("Somente o responsável pode gerenciar o cadastro bancário.")
    tenant=request.user.tenant
    if request.user.is_superuser:
        from core.portal import _tenant
        tenant=_tenant(request)
    if not tenant or tenant.deleted_at:
        raise PermissionDenied("Selecione uma empresa ativa.")

    webhook_url=request.build_absolute_uri(f"/webhooks/tenant/mercadopago/{tenant.slug}/")
    connections=TenantPaymentConnection.objects.filter(
        tenant=tenant,provider="mercadopago"
    ).order_by("environment")
    connected=connections.filter(status=TenantPaymentConnection.Status.CONNECTED).exists()
    banks=TenantBankAccount.objects.filter(tenant=tenant,active=True).order_by("-is_primary","bank_name","id")
    schedule_settings,_=TenantScheduleSettings.objects.get_or_create(tenant=tenant)
    action=request.POST.get("action") if request.method=="POST" else ""

    bank_form=BankAccountForm(request.POST or None,prefix="bank")
    provider_form=TenantGatewayForm(
        request.POST or None if action=="provider_connect" else None,prefix="provider"
    )

    if request.method=="POST" and action=="bank_add" and bank_form.is_valid():
        data=bank_form.cleaned_data
        with transaction.atomic():
            make_primary=bool(data.get("is_primary") or not banks.exists())
            if make_primary:
                TenantBankAccount.objects.filter(tenant=tenant,active=True).update(is_primary=False)
            TenantBankAccount.objects.create(
                tenant=tenant,bank_code=(data.get("bank_code") or "").strip(),
                bank_name=data["bank_name"].strip(),holder_name=data["holder_name"].strip(),
                details_encrypted=encrypt_json({
                    "holder_document":data["holder_document"].strip(),
                    "branch":(data.get("branch") or "").strip(),
                    "account_number":data["account_number"].strip(),
                    "account_type":data["account_type"],
                    "pix_key_type":data.get("pix_key_type") or "",
                    "pix_key":(data.get("pix_key") or "").strip(),
                }),
                account_last4=_mask_last4(data["account_number"]),
                pix_key_last4=_mask_last4(data.get("pix_key")),
                is_primary=make_primary,created_by=request.user,
            )
        messages.success(request,"Conta bancária cadastrada.")
        return redirect("tenant-payment-gateway")

    if request.method=="POST" and action=="bank_remove":
        account=TenantBankAccount.objects.filter(
            tenant=tenant,pk=request.POST.get("bank_account"),active=True
        ).first()
        if account:
            was_primary=account.is_primary
            account.active=False
            account.is_primary=False
            account.save(update_fields=["active","is_primary","updated_at"])
            if was_primary:
                replacement=TenantBankAccount.objects.filter(tenant=tenant,active=True).order_by("id").first()
                if replacement:
                    replacement.is_primary=True
                    replacement.save(update_fields=["is_primary","updated_at"])
            messages.success(request,"Conta bancária removida.")
        return redirect("tenant-payment-gateway")

    if request.method=="POST" and action=="bank_primary":
        account=TenantBankAccount.objects.filter(
            tenant=tenant,pk=request.POST.get("bank_account"),active=True
        ).first()
        if account:
            with transaction.atomic():
                TenantBankAccount.objects.filter(tenant=tenant,active=True).update(is_primary=False)
                account.is_primary=True
                account.save(update_fields=["is_primary","updated_at"])
            messages.success(request,"Conta principal atualizada.")
        return redirect("tenant-payment-gateway")

    if request.method=="POST" and action=="booking_payments":
        if not connected and request.POST.get("enabled")=="on":
            messages.error(request,"Conecte um provedor de cobrança online antes de ativar o pagamento no agendamento.")
        else:
            schedule_settings.online_booking_payments_enabled=request.POST.get("enabled")=="on"
            schedule_settings.save(update_fields=["online_booking_payments_enabled","updated_at"])
            messages.success(request,"Pagamento no agendamento atualizado.")
        return redirect("tenant-payment-gateway")

    if request.method=="POST" and action=="provider_connect" and provider_form.is_valid():
        try:
            configure_tenant_mercadopago(
                tenant=tenant,created_by=request.user,**provider_form.cleaned_data
            )
        except (ValueError,RuntimeError,RequestException):
            provider_form.add_error(
                None,"Não foi possível validar o provedor. Confira ambiente, credenciais e chave do webhook."
            )
        else:
            messages.success(request,"Provedor de cobrança online validado e conectado.")
            return redirect("tenant-payment-gateway")

    return render(request,"billing/tenant_gateway.html",{
        "tenant":tenant,"form":provider_form,"bank_form":bank_form,"banks":banks,
        "connections":connections,"webhook_url":webhook_url,
        "schedule_settings":schedule_settings,"connected":connected,
        "show_form":not connected or request.GET.get("alterar")=="1" or bool(provider_form.errors),
        "common_banks":COMMON_BANKS,
    })
