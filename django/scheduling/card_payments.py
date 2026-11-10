import json, re
from decimal import Decimal
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.utils import timezone
from accounts.login_limits import attempt_budget, limited_response
from billing.models import TenantPaymentTransaction
from billing.payment_services import (
    connected_tenant_gateway,
    create_tenant_card_payment,
)
from .availability import AvailabilityService
from .public_views import _appointment


class CardForm(forms.Form):
    card_token = forms.RegexField(r"^[A-Za-z0-9_-]{8,200}$")
    payment_method_id = forms.RegexField(r"^[A-Za-z0-9_-]{1,60}$")
    issuer_id = forms.RegexField(r"^[0-9]{0,30}$", required=False)
    installments = forms.IntegerField(min_value=1, max_value=12, initial=1)
    attempt_id = forms.RegexField(r"^[A-Za-z0-9_-]{16,100}$")


def eligible(row):
    from barber.models import BarberCommandPayment

    if (
        row.tenant.deleted_at
        or row.tenant.archived_at
        or BarberCommandPayment.objects.filter(
            command__appointment=row,
            tenant=row.tenant,
            voided_at__isnull=True,
            external_payment__isnull=True,
        ).exists()
    ):
        raise ValidationError(
            "A reserva não pode iniciar outro pagamento online. Confira a comanda com o estabelecimento."
        )
    config = AvailabilityService().settings(row.tenant, unit=row.unit)
    if (
        not config.online_booking_payments_enabled
        or not config.card_booking_payments_enabled
        or row.booking_payment == "on_site"
        or row.status not in {"pending", "confirmed"}
        or row.starts_at <= timezone.now()
        or not row.customer.email
    ):
        raise ValidationError("Cartão antecipado indisponível para esta reserva.")
    connection = connected_tenant_gateway(row.tenant)
    key = str(connection.metadata.get("public_key") or "")
    if not key or not re.fullmatch(r"[A-Za-z0-9_-]{8,200}", key):
        raise ValidationError(
            "O estabelecimento precisa configurar a chave pública do provedor."
        )
    return connection, key


@never_cache
def page(request, token):
    row = _appointment(token)
    try:
        connection, key = eligible(row)
    except (ValidationError, RuntimeError, ValueError):
        return render(
            request,
            "scheduling/card_payment.html",
            {"appointment": row, "token": token, "unavailable": True},
        )
    from uuid import uuid4

    data = {
        "publicKey": key,
        "amount": str(
            row.booking_payment_amount
            or row.service_price_snapshot
            or row.service.price
        ),
        "submitUrl": reverse("public-appointment-card-submit", args=[token]),
        "attemptId": uuid4().hex,
        "email": row.customer.email,
    }
    return render(
        request,
        "scheduling/card_payment.html",
        {"appointment": row, "token": token, "card_config": data},
    )


@never_cache
@require_POST
@transaction.atomic
def submit(request, token):
    preview = _appointment(token)
    from barber.models import BarberCommand

    list(
        BarberCommand.objects.select_for_update()
        .filter(tenant=preview.tenant, appointment=preview)
        .order_by("pk")
    )
    row = _appointment(token, lock=True)
    _, wait = attempt_budget(request, "booking-card", row.pk)
    if wait:
        return limited_response(wait)
    try:
        connection, _ = eligible(row)
        data = json.loads(request.body)
        if not isinstance(data, dict) or set(data) - {
            "card_token",
            "payment_method_id",
            "issuer_id",
            "installments",
            "attempt_id",
            "identification",
        }:
            raise ValueError
        form = CardForm(data)
        if not form.is_valid():
            raise ValueError
        identification = data.get("identification")
        if identification and (
            not isinstance(identification, dict)
            or identification.get("type") not in {"CPF", "CNPJ"}
            or not re.fullmatch(r"\d{11}|\d{14}", str(identification.get("number", "")))
        ):
            raise ValueError
        # Serialize every payment method for this appointment, including Pix created by the existing page.
        paid = TenantPaymentTransaction.objects.filter(
            tenant=row.tenant,
            reference_type="appointment",
            reference_id=row.pk,
            status="paid",
        ).first()
        if paid:
            return JsonResponse(
                {"status": "paid", "detail": "Pagamento já confirmado."}
            )
        amount = Decimal(
            row.booking_payment_amount
            or row.service_price_snapshot
            or row.service.price
        )
        attempt = form.cleaned_data["attempt_id"]
        import hashlib

        key = (
            "card-"
            + hashlib.sha256(
                f"{row.tenant_id}|appointment|{row.pk}|{amount.quantize(Decimal('.01'))}|{attempt}".encode()
            ).hexdigest()[:64]
        )
        prior = TenantPaymentTransaction.objects.filter(
            tenant=row.tenant, idempotency_key=key
        ).first()
        if prior:
            return JsonResponse(
                {
                    "status": prior.status,
                    "detail": "Tentativa já registrada. Atualize o acompanhamento.",
                }
            )
        if TenantPaymentTransaction.objects.filter(
            tenant=row.tenant,
            reference_type="appointment",
            reference_id=row.pk,
            status__in=["created", "pending"],
        ).exists():
            raise ValidationError(
                "Já existe um pagamento em processamento. Aguarde sua confirmação ou expiração antes de iniciar outro."
            )
        data = form.cleaned_data
        data.pop("attempt_id")
        tx = create_tenant_card_payment(
            tenant=row.tenant,
            reference_type="appointment",
            reference_id=row.pk,
            amount=amount,
            payer_email=row.customer.email,
            attempt_id=attempt,
            identification=identification,
            notification_url=settings.PUBLIC_BASE_URL.rstrip("/")
            + reverse(
                "payment-tenant-webhook",
                args=[row.tenant.public_slug or row.tenant.slug],
            ),
            **data,
        )
        return JsonResponse(
            {
                "status": tx.status,
                "detail": "Pagamento registrado. Acompanhe a confirmação nesta reserva.",
            }
        )
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return JsonResponse(
            {
                "detail": " ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else "Dados tokenizados inválidos."
            },
            status=400,
        )
    except Exception:
        # Never return provider payload, token or card data to logs/UI.
        return JsonResponse(
            {
                "detail": "Não foi possível confirmar o pagamento. Atualize o acompanhamento antes de tentar novamente."
            },
            status=502,
        )
