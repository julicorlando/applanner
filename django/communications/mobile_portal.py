import hashlib, json, re, time
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from core.crypto import encrypt_json, encrypt_text
from accounts.permissions import require_any_capability
from accounts.login_limits import attempt_budget, limited_response
from scheduling.customer_portal import tenant_for, identity_digest
from scheduling.models import Customer
from tenants.models import Tenant
from .mobile_models import (
    DeliveryProviderSettings,
    TenantDeliverySettings,
    CustomerDeliveryConsent,
    PushSubscription,
)
from .mobile_delivery import validate_subscription, initialize_vapid, phone_digest


def identity(request, slug=None):
    if getattr(request, "support_actor", None):
        raise PermissionDenied
    if slug:
        tenant = tenant_for(slug)
        access = request.session.get(f"customer-portal:{tenant.pk}", {})
        if access.get("expires", 0) <= time.time():
            raise PermissionDenied
        customer = Customer.objects.filter(
            pk=access.get("customer"), tenant=tenant, active=True
        ).first()
        if not customer or not constant_time_compare(
            access.get("identity", ""), identity_digest(customer)
        ):
            raise PermissionDenied
        return tenant, None, customer
    if not request.user.is_authenticated:
        raise PermissionDenied
    if not request.user.tenant_id and not request.user.is_superuser:
        raise PermissionDenied
    return request.user.tenant if request.user.tenant_id else None, request.user, None


@never_cache
def subscription(request, slug=None):
    tenant, user, customer = identity(request, slug)
    config = DeliveryProviderSettings.objects.filter(pk=1, push_enabled=True).first()
    if request.method == "GET":
        return JsonResponse(
            {
                "enabled": bool(config and config.vapid_public_key),
                "publicKey": config.vapid_public_key if config else "",
            }
        )
    if request.method != "POST":
        return JsonResponse({"detail": "Método inválido."}, status=405)
    _, wait = attempt_budget(
        request,
        "push-enroll",
        f"{getattr(user, 'pk', None)}:{getattr(customer, 'pk', None)}",
    )
    if wait:
        return limited_response(wait)
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError
        owned = PushSubscription.objects.filter(
            tenant=tenant, user=user, customer=customer
        )
        if data.get("action") == "remove":
            owned.filter(
                endpoint_hash=hashlib.sha256(
                    str(data.get("endpoint", "")).encode()
                ).hexdigest()
            ).update(active=False)
            return JsonResponse(
                {"detail": "Notificações desativadas neste dispositivo."}
            )
        if not config or not config.vapid_private_encrypted:
            raise ValidationError("Push ainda não habilitado pela plataforma.")
        info = validate_subscription(data.get("subscription"))
        if (
            owned.filter(active=True).count() >= 10
            and not owned.filter(
                endpoint_hash=hashlib.sha256(info["endpoint"].encode()).hexdigest()
            ).exists()
        ):
            raise ValidationError(
                "Limite de dispositivos atingido. Desative um dispositivo antes de cadastrar outro."
            )
        row, _ = PushSubscription.objects.update_or_create(
            tenant=tenant,
            user=user,
            customer=customer,
            endpoint_hash=hashlib.sha256(info["endpoint"].encode()).hexdigest(),
            defaults={
                "payload_encrypted": encrypt_json(info),
                "active": True,
                "consent_at": timezone.now(),
            },
        )
        return JsonResponse(
            {"detail": "Notificações ativadas neste dispositivo.", "id": row.pk}
        )
    except (ValidationError, ValueError, TypeError):
        return JsonResponse(
            {"detail": "Inscrição inválida ou Push ainda indisponível."}, status=400
        )


class SMSConsentForm(forms.Form):
    consent = forms.BooleanField(
        required=False,
        label="Autorizo SMS de confirmação e lembrete no telefone cadastrado",
    )


@never_cache
def customer_preferences(request, slug):
    tenant, _, customer = identity(request, slug)
    preference, _ = CustomerDeliveryConsent.objects.get_or_create(
        tenant=tenant, customer=customer
    )
    form = SMSConsentForm(
        request.POST or None,
        initial={
            "consent": bool(
                preference.sms_consent_at
                and preference.phone_digest == phone_digest(customer)
            )
        },
    )
    if request.method == "POST" and form.is_valid():
        preference.sms_consent_at = (
            timezone.now() if form.cleaned_data["consent"] else None
        )
        preference.phone_digest = (
            phone_digest(customer) if preference.sms_consent_at else ""
        )
        preference.save(update_fields=["sms_consent_at", "phone_digest", "updated_at"])
        return redirect("customer-notification-preferences", slug=slug)
    from django.urls import reverse

    return render(
        request,
        "communications/notification_preferences.html",
        {
            "form": form,
            "push_url": reverse("customer-push-subscription", args=[slug]),
            "customer": customer,
            "tenant": tenant,
        },
    )


@login_required
@never_cache
def user_preferences(request):
    identity(request)
    from django.urls import reverse

    return render(
        request,
        "communications/notification_preferences.html",
        {
            "push_url": reverse("professional-push-subscription")
            if request.user.role == "professional"
            else reverse("user-push-subscription")
        },
    )


class ProviderForm(forms.ModelForm):
    token = forms.CharField(
        required=False,
        label="Token Twilio (deixe vazio para manter)",
        widget=forms.PasswordInput(render_value=False),
    )

    class Meta:
        model = DeliveryProviderSettings
        fields = [
            "push_enabled",
            "contact_email",
            "sms_enabled",
            "twilio_account_sid",
            "sms_from",
        ]
        labels = {
            "push_enabled": "Ativar Web Push",
            "contact_email": "E-mail de contato VAPID",
            "sms_enabled": "Ativar SMS pago via Twilio",
            "twilio_account_sid": "Account SID Twilio",
            "sms_from": "Número Twilio habilitado para SMS A2P (formato internacional)",
        }

    def clean(self):
        data = super().clean()
        if data.get("push_enabled") and not data.get("contact_email"):
            raise forms.ValidationError("Informe e-mail de contato para Push.")
        if data.get("sms_enabled") and (
            not re.fullmatch(r"AC[a-fA-F0-9]{32}", data.get("twilio_account_sid", ""))
            or not re.fullmatch(r"\+[1-9]\d{9,14}", data.get("sms_from", ""))
            or not (data.get("token") or self.instance.twilio_token_encrypted)
        ):
            raise forms.ValidationError(
                "SMS exige conta, token e remetente válido. Há custos no provedor; limite cada empresa antes de ativar."
            )
        return data


class QuotaForm(forms.Form):
    tenant = forms.ModelChoiceField(queryset=Tenant.objects.none(), label="Empresa")
    limit = forms.IntegerField(
        min_value=0,
        max_value=10000,
        label="Máximo de tentativas SMS por mês (0 bloqueia)",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tenant"].queryset = Tenant.objects.filter(
            deleted_at__isnull=True, archived_at__isnull=True
        )


@login_required
def providers(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    config, _ = DeliveryProviderSettings.objects.get_or_create(pk=1)
    action = request.POST.get("action")
    form = ProviderForm(request.POST if action == "provider" else None, instance=config)
    quota = QuotaForm(request.POST if action == "quota" else None)
    if request.method == "POST":
        with transaction.atomic():
            if action == "provider" and form.is_valid():
                config = form.save(commit=False)
                if form.cleaned_data["token"]:
                    config.twilio_token_encrypted = encrypt_text(
                        form.cleaned_data["token"]
                    )
                if config.push_enabled:
                    initialize_vapid(config)
                config.save()
                from core.audit import append_audit

                transaction.on_commit(
                    lambda: append_audit(
                        tenant=None,
                        user=request.user,
                        action="DELIVERY_PROVIDER_CONFIGURED",
                        entity_type="DeliveryProviderSettings",
                        entity_id=1,
                        after={
                            "push_enabled": config.push_enabled,
                            "sms_enabled": config.sms_enabled,
                        },
                    )
                )
                return redirect("master-delivery-providers")
            if action == "quota" and quota.is_valid():
                TenantDeliverySettings.objects.update_or_create(
                    tenant=quota.cleaned_data["tenant"],
                    defaults={"sms_monthly_limit": quota.cleaned_data["limit"]},
                )
                from core.audit import append_audit

                tenant = quota.cleaned_data["tenant"]
                transaction.on_commit(
                    lambda: append_audit(
                        tenant=tenant,
                        user=request.user,
                        action="SMS_QUOTA_APPROVED",
                        entity_type="TenantDeliverySettings",
                        entity_id=tenant.pk,
                        after={"limit": quota.cleaned_data["limit"]},
                    )
                )
                return redirect("master-delivery-providers")
    return render(
        request,
        "communications/delivery_providers.html",
        {
            "form": form,
            "quota": quota,
            "config": config,
            "limits": TenantDeliverySettings.objects.select_related("tenant"),
        },
    )


@login_required
def tenant_channels(request):
    require_any_capability(request.user, "communications.manage")
    if not request.user.tenant_id or request.user.role in {"professional", "reception"}:
        raise PermissionDenied
    settings, _ = TenantDeliverySettings.objects.get_or_create(
        tenant=request.user.tenant
    )
    if request.method == "POST":
        settings.sms_enabled = request.POST.get("enabled") == "on"
        settings.save(update_fields=["sms_enabled", "updated_at"])
        return redirect("tenant-delivery-channels")
    return render(request, "communications/tenant_channels.html", {"config": settings})
