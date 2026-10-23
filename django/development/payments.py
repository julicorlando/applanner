"""Isolated payments using the Master's existing, validated platform gateway."""

import base64
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from billing.mercadopago import validate_charge_amount
from billing.models import PaymentGateway
from billing.payment_services import platform_provider
from core.audit import append_audit
from .models import Charge, Client, Delivery, OnlinePayment
from .services import public_url

BUSY = {"creating", "pending", "unknown", "attention"}


def configured_gateway():
    # Test credentials must never settle a real development invoice.
    return PaymentGateway.objects.filter(
        provider="mercadopago",
        environment="production",
        active=True,
        last_test_status="validated",
    ).first()


def payment_note(row):
    return "Pagamento online confirmado pelo provedor: " + row.provider_id


@transaction.atomic
def _allocate(charge_id, method, attempt_id, access_link_id=None):
    customer_id = Charge.objects.values_list("client_id", flat=True).get(pk=charge_id)
    customer = (
        Client.objects.select_for_update().select_related("user").get(pk=customer_id)
    )
    charge = Charge.objects.select_for_update().get(pk=charge_id)
    from .payment_links import link_allows_payment

    if not link_allows_payment(access_link_id, charge_id):
        raise ValidationError(
            "Reabra o link da cobrança e confira o documento antes de pagar."
        )
    if (
        method not in {"pix", "card"}
        or charge.status != "open"
        or not charge.online_payments_enabled
        or not customer.active
        or not customer.user.is_active
        or customer.user.deleted_at
    ):
        raise ValidationError(
            "Esta cobrança não está disponível para pagamento online."
        )
    gateway = configured_gateway()
    if not gateway or (method == "card" and not gateway.public_key):
        raise ValidationError(
            "O provedor de pagamento do Master ainda não está habilitado para este meio."
        )
    validate_charge_amount(charge.amount)
    key = UUID(str(attempt_id))
    previous = OnlinePayment.objects.filter(public_id=key).first()
    if previous:
        if previous.charge_id != charge.pk or previous.method != method:
            raise ValidationError("Tentativa de pagamento inválida.")
        return previous, False
    active = (
        charge.online_payments.filter(status__in=BUSY | {"paid", "refunded"})
        .order_by("-pk")
        .first()
    )
    if active:
        return active, False
    return OnlinePayment.objects.create(
        public_id=key,
        charge=charge,
        gateway=gateway,
        method=method,
        amount=charge.amount,
        charge_revision=charge.revision,
        next_check_at=timezone.now() + timedelta(minutes=5),
    ), True


def start_payment(charge_id, method, attempt_id, card=None, *, access_link_id=None):
    row, created = _allocate(charge_id, method, attempt_id, access_link_id)
    if not created:
        return row
    provider_called = False
    try:
        provider = platform_provider(row.gateway)
        collector = str(provider.test_connection().get("id") or "")
        if not collector.isdecimal():
            raise ValidationError("Não foi possível validar a conta recebedora.")
        # Commit the recipient snapshot before any money-moving API request.
        OnlinePayment.objects.filter(pk=row.pk).update(collector_id=collector)
        row.collector_id = collector
        with transaction.atomic():
            Client.objects.select_for_update().get(pk=row.charge.client_id)
            charge = (
                Charge.objects.select_for_update()
                .select_related("client__user")
                .get(pk=charge_id)
            )
            row = OnlinePayment.objects.select_for_update().get(pk=row.pk)
            from .payment_links import link_allows_payment

            if (
                charge.status != "open"
                or not charge.online_payments_enabled
                or not charge.client.active
                or not charge.client.user.is_active
                or charge.client.user.deleted_at
                or not row.gateway.active
                or not link_allows_payment(access_link_id, charge_id)
            ):
                row.status = "cancelled"
                row.save(update_fields=["status", "updated_at"])
                return row
            payer = {
                "email": charge.client.user.email,
                "identification": {
                    "type": charge.client.kind.upper(),
                    "number": charge.client.document,
                },
            }
            notify = public_url("development-payment-webhook", row.public_id)
            if method == "pix":
                payload = {
                    "transaction_amount": float(row.amount),
                    "description": charge.description,
                    "payment_method_id": "pix",
                    "external_reference": row.reference,
                    "payer": payer,
                    "notification_url": notify,
                    "date_of_expiration": (
                        timezone.now() + timedelta(hours=24)
                    ).isoformat(timespec="seconds"),
                }
                provider_called = True
                remote = provider._request(
                    "POST", "/v1/payments", payload, row.reference
                )
            else:
                provider_called = True
                remote = provider.create_tokenized_card_payment(
                    amount=row.amount,
                    token=card["card_token"],
                    payment_method_id=card["payment_method_id"],
                    payer_email=payer["email"],
                    external_reference=row.reference,
                    installments=card["installments"],
                    issuer_id=card.get("issuer_id", ""),
                    identification=payer["identification"],
                    notification_url=notify,
                    description=charge.description,
                    idempotency_key=row.reference,
                )
            if not str(remote.get("id") or "").isdecimal():
                raise ValidationError("Resposta de pagamento inválida.")
            row.provider_id = str(remote["id"])
            row.save(update_fields=["provider_id", "collector_id", "updated_at"])
            apply_remote(row.pk, remote)
    except Exception:
        # A timeout can happen after capture. Retain the attempt and reconcile;
        # never create a fresh card charge based solely on a lost response.
        OnlinePayment.objects.filter(pk=row.pk).update(
            status="unknown" if provider_called else "failed",
            error_code="provider_unavailable",
            collector_id=getattr(row, "collector_id", ""),
            next_check_at=timezone.now() + timedelta(minutes=1),
            updated_at=timezone.now(),
        )
    return OnlinePayment.objects.get(pk=row.pk)


def validate_remote(row, remote):
    try:
        amount = Decimal(str(remote.get("transaction_amount")))
        valid = (
            amount.is_finite()
            and amount == row.amount
            and remote.get("currency_id") == "BRL"
            and remote.get("external_reference") == row.reference
            and remote.get("live_mode") is True
            and row.gateway.environment == "production"
            and bool(row.collector_id)
            and str(remote.get("collector_id")) == row.collector_id
            and str(remote.get("id") or "").isdecimal()
            and row.provider_id in {"", str(remote.get("id"))}
        )
        method_ok = (
            remote.get("payment_method_id") == "pix"
            if row.method == "pix"
            else remote.get("payment_type_id") in {"credit_card", "debit_card"}
        )
        if not valid or not method_ok:
            raise ValueError
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValidationError(
            "O pagamento não corresponde à cobrança registrada."
        ) from exc


@transaction.atomic
def apply_remote(pk, remote):
    preview = OnlinePayment.objects.select_related("charge").get(pk=pk)
    Client.objects.select_for_update().get(pk=preview.charge.client_id)
    charge = Charge.objects.select_for_update().get(pk=preview.charge_id)
    row = OnlinePayment.objects.select_for_update().select_related("gateway").get(pk=pk)
    validate_remote(row, remote)
    previous = row.status
    status = str(remote.get("status") or "")
    refunded = Decimal(str(remote.get("transaction_amount_refunded", 0) or 0))
    if not refunded.is_finite() or refunded < 0:
        raise ValidationError("Valor estornado inválido.")
    if status in {"refunded", "charged_back"} or refunded > 0:
        state = "refunded"  # Master review; never reopen the debt automatically.
    elif status == "approved":
        state = "paid"
    elif status in {"cancelled", "canceled", "expired"}:
        state = "cancelled"
    elif status == "rejected":
        state = "failed"
    else:
        state = "pending"
    if previous == "refunded" and state != "refunded":
        return row
    if previous == "paid" and state in {"pending", "failed", "cancelled"}:
        return row
    row.provider_id = str(remote["id"])
    row.status, row.error_code = state, ""
    row.next_check_at = timezone.now() + timedelta(minutes=2)
    if row.method == "pix" and state == "pending":
        data = (remote.get("point_of_interaction") or {}).get("transaction_data") or {}
        row.pix_code = str(data.get("qr_code") or row.pix_code)[:5000]
        source = str(data.get("qr_code_base64") or "")
        if source and len(source) <= 300000:
            try:
                if base64.b64decode(source, validate=True).startswith(
                    b"\x89PNG\r\n\x1a\n"
                ):
                    row.pix_image = source
            except (ValueError, TypeError):
                pass
    if state == "paid":
        row.paid_at = row.paid_at or timezone.now()
        if (
            charge.revision != row.charge_revision
            or charge.amount != row.amount
            or charge.status == "cancelled"
        ):
            row.status, row.error_code = "attention", "charge_changed_after_payment"
        elif charge.status == "open":
            charge.status, charge.paid_at, charge.settlement_note = (
                "paid",
                row.paid_at,
                payment_note(row),
            )
            charge.save(
                update_fields=["status", "paid_at", "settlement_note", "updated_at"]
            )
            Delivery.objects.filter(
                charge=charge, status__in=["pending", "failed"]
            ).update(status="cancelled", payload_encrypted="")
        elif charge.settlement_note != payment_note(row):
            row.status, row.error_code = "attention", "possible_duplicate_receipt"
    if row.status != previous:
        append_audit(
            action="development.online-payment-" + row.status,
            entity_type="development.OnlinePayment",
            entity_id=row.pk,
            after={
                "charge_id": charge.pk,
                "provider_id": row.provider_id,
                "status": row.status,
            },
        )
    row.save()
    return row


def reconcile(pk, resource_id=None):
    row = OnlinePayment.objects.select_related("gateway").get(pk=pk)
    provider = platform_provider(row.gateway)
    if resource_id or row.provider_id:
        remote = provider.get_payment(str(resource_id or row.provider_id))
    else:
        results = provider.search_payments(row.reference).get("results") or []
        if len(results) != 1:
            OnlinePayment.objects.filter(pk=pk).update(
                next_check_at=timezone.now() + timedelta(minutes=5)
            )
            return row
        remote = results[0]
    return apply_remote(pk, remote)


def reconcile_online_payments():
    ids = list(
        OnlinePayment.objects.filter(
            status__in=["creating", "pending", "unknown", "paid"],
            next_check_at__lte=timezone.now(),
            created_at__gte=timezone.now() - timedelta(days=30),
        )
        .order_by("next_check_at", "pk")
        .values_list("pk", flat=True)[:50]
    )
    for pk in ids:
        try:
            reconcile(pk)
        except Exception:
            OnlinePayment.objects.filter(pk=pk).update(
                error_code="verification_unavailable",
                next_check_at=timezone.now() + timedelta(minutes=5),
            )
    return len(ids)
