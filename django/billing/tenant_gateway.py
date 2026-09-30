"""Owner-facing connection for the tenant's own checkout provider."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from requests.exceptions import RequestException

from .models import PaymentGateway, TenantPaymentConnection
from .payment_services import configure_tenant_mercadopago
from scheduling.models import TenantScheduleSettings


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
    schedule_settings,_=TenantScheduleSettings.objects.get_or_create(tenant=tenant)
    if request.method=="POST" and request.POST.get("action")=="booking_payments":
        if not connected and request.POST.get("enabled")=="on":
            messages.error(request,"Conecte o Mercado Pago antes de ativar o pagamento no agendamento.")
        else:
            schedule_settings.online_booking_payments_enabled=request.POST.get("enabled")=="on"
            schedule_settings.save(update_fields=["online_booking_payments_enabled","updated_at"])
            messages.success(request,"Pagamento no agendamento atualizado.")
        return redirect("tenant-payment-gateway")
    form=TenantGatewayForm(request.POST or None)
    if request.method=="POST" and form.is_valid():
        try:
            configure_tenant_mercadopago(tenant=tenant,created_by=request.user,**form.cleaned_data)
        except (ValueError,RuntimeError,RequestException):
            form.add_error(None,"Não foi possível validar a conta. Confira ambiente, credenciais e chave do webhook.")
        else:
            messages.success(request,"Mercado Pago da empresa validado e conectado.")
            return redirect("tenant-payment-gateway")
    return render(request,"billing/tenant_gateway.html",{
        "tenant":tenant,"form":form,"connections":connections,"webhook_url":webhook_url,
        "schedule_settings":schedule_settings,
        "connected":connected,"show_form":not connected or request.GET.get("alterar")=="1" or bool(form.errors),
    })
