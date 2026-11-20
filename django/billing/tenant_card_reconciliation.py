from decimal import Decimal
from celery import shared_task
from django.db import transaction
from django.utils import timezone
from .models import TenantPaymentTransaction
from .payment_services import tenant_provider
from .tenant_card_integrity import validate_card_event, card_status


@transaction.atomic
def reconcile(pk):
    tx = TenantPaymentTransaction.objects.select_for_update().get(pk=pk, method="card")
    if tx.status not in {"created", "pending"}:
        return tx
    provider = tenant_provider(tx.connection)
    if tx.provider_transaction_id:
        remote = provider.get_payment(tx.provider_transaction_id)
    else:
        results = provider.search_payments(tx.external_reference).get("results", [])
        if len(results) != 1:
            return tx
        remote = results[0]
    identity = str(remote.get("id", ""))
    validate_card_event(tx, remote, identity)
    tx.provider_transaction_id = identity
    tx.status = card_status(remote)
    tx.fee_amount = sum(
        (
            Decimal(str(f.get("amount", 0)))
            for f in remote.get("fee_details", [])
            if isinstance(f, dict)
        ),
        Decimal(0),
    )
    tx.net_amount = Decimal(
        str(
            (remote.get("transaction_details") or {}).get(
                "net_received_amount", tx.gross_amount - tx.fee_amount
            )
        )
    )
    if tx.status == "paid":
        tx.paid_at = tx.paid_at or timezone.now()
    tx.reconciled_at = timezone.now()
    tx.save()
    return tx


@shared_task
def reconcile_pending_tenant_cards():
    ids = list(
        TenantPaymentTransaction.objects.filter(
            method="card", status__in=["created", "pending"]
        )
        .order_by("created_at")
        .values_list("pk", flat=True)[:50]
    )
    changed = 0
    for pk in ids:
        try:
            changed += int(reconcile(pk).status not in {"created", "pending"})
        except Exception:
            continue
    return changed
