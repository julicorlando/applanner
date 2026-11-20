from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from billing.entitlements import module_enabled
from billing.models import TenantPaymentTransaction
from finance.models import FinancialTransaction

from .models import (
    GamePlayer,
    Reservation,
    ReservationFinance,
    ReservationHistory,
)


def _finance_income(*,tenant,source_type,source_id,description,amount,method):
    if not module_enabled(tenant,"finance"):
        return None
    key=f"{source_type}-{source_id}-{method}"
    tx,_=FinancialTransaction.objects.get_or_create(
        tenant=tenant,
        idempotency_key=key,
        defaults={
            "source_type":source_type,
            "source_id":source_id,
            "type":FinancialTransaction.Type.INCOME,
            "description":description,
            "amount":amount,
            "payment_method":method,
            "status":FinancialTransaction.Status.PAID,
            "competence_at":timezone.localdate(),
            "paid_at":timezone.now(),
        },
    )
    return tx


@transaction.atomic
def reconcile_tenant_transaction(transaction):
    tx=(
        TenantPaymentTransaction.objects
        .select_for_update()
        .select_related("tenant")
        .get(pk=transaction.pk)
    )
    if tx.reconciled_at:
        return tx

    if tx.reference_type=="reservation":
        _reconcile_reservation(tx)
    elif tx.reference_type=="game_player":
        _reconcile_game_player(tx)

    tx.reconciled_at=timezone.now()
    tx.save(update_fields=["reconciled_at","updated_at"])
    return tx


def _reconcile_reservation(tx):
    reservation=Reservation.objects.select_for_update().filter(
        pk=tx.reference_id,tenant=tx.tenant
    ).first()
    if not reservation:
        return

    finance,_=ReservationFinance.objects.select_for_update().get_or_create(
        reservation=reservation,
        defaults={
            "tenant":tx.tenant,
            "gross_amount":reservation.total_amount,
            "deposit_due":reservation.deposit_amount,
        },
    )

    if tx.status==TenantPaymentTransaction.Status.PAID:
        old_status=reservation.status
        paid_total=max(finance.amount_paid,tx.gross_amount)
        state=(
            ReservationFinance.State.PAID
            if paid_total+Decimal("0.01")>=reservation.total_amount
            else ReservationFinance.State.PARTIAL
        )
        finance.payment_state=state
        finance.amount_paid=paid_total
        finance.provider=tx.connection.provider
        finance.external_reference=tx.external_reference
        finance.transaction_id=tx.provider_transaction_id
        finance.fee_amount=tx.fee_amount
        finance.net_amount=tx.net_amount
        finance.paid_at=finance.paid_at or timezone.now()
        finance.reconciled_at=timezone.now()
        finance.save()

        if reservation.status==Reservation.Status.PENDING_PAYMENT:
            reservation.status=Reservation.Status.CONFIRMED
            reservation.confirmed_at=reservation.confirmed_at or timezone.now()
        reservation.payment_status=(
            Reservation.PaymentStatus.PAID
            if state==ReservationFinance.State.PAID
            else Reservation.PaymentStatus.PARTIAL
        )
        reservation.save(update_fields=[
            "status","payment_status","confirmed_at","updated_at",
        ])
        if old_status!=reservation.status or not ReservationHistory.objects.filter(
            reservation=reservation,
            action="payment_confirmed",
            notes__contains=tx.external_reference,
        ).exists():
            ReservationHistory.objects.create(
                reservation=reservation,
                action="payment_confirmed",
                old_status=old_status,
                new_status=reservation.status,
                notes=f"Pagamento {tx.method} validado · {tx.external_reference}"[:500],
            )
        _finance_income(
            tenant=tx.tenant,
            source_type="arena_reservation",
            source_id=reservation.pk,
            description=f"Pagamento de reserva Arena #{reservation.pk}",
            amount=tx.gross_amount,
            method=tx.method,
        )
        return

    terminal={
        TenantPaymentTransaction.Status.EXPIRED:ReservationFinance.State.EXPIRED,
        TenantPaymentTransaction.Status.FAILED:ReservationFinance.State.FAILED,
        TenantPaymentTransaction.Status.CANCELLED:ReservationFinance.State.CANCELLED,
        TenantPaymentTransaction.Status.REFUNDED:ReservationFinance.State.REFUNDED,
        TenantPaymentTransaction.Status.PARTIALLY_REFUNDED:ReservationFinance.State.PARTIALLY_REFUNDED,
    }
    state=terminal.get(tx.status)
    if not state:
        return

    finance.payment_state=state
    if tx.status==TenantPaymentTransaction.Status.REFUNDED:
        finance.amount_refunded=max(finance.amount_refunded,tx.gross_amount)
    elif tx.status==TenantPaymentTransaction.Status.PARTIALLY_REFUNDED:
        finance.amount_refunded=max(finance.amount_refunded,tx.gross_amount)
    finance.reconciled_at=timezone.now()
    finance.save(update_fields=[
        "payment_state","amount_refunded","reconciled_at","updated_at",
    ])

    if tx.status in {
        TenantPaymentTransaction.Status.EXPIRED,
        TenantPaymentTransaction.Status.CANCELLED,
    } and reservation.status==Reservation.Status.PENDING_PAYMENT:
        old=reservation.status
        reservation.status=Reservation.Status.CANCELLED
        reservation.payment_status=Reservation.PaymentStatus.CANCELLED
        reservation.cancelled_at=timezone.now()
        reservation.save(update_fields=[
            "status","payment_status","cancelled_at","updated_at",
        ])
        ReservationHistory.objects.create(
            reservation=reservation,
            action="payment_expired" if tx.status==TenantPaymentTransaction.Status.EXPIRED else "payment_cancelled",
            old_status=old,
            new_status=reservation.status,
            notes="Pagamento não concluído; horário liberado",
        )
    elif tx.status==TenantPaymentTransaction.Status.REFUNDED:
        reservation.payment_status=Reservation.PaymentStatus.REFUNDED
        reservation.save(update_fields=["payment_status","updated_at"])


def _reconcile_game_player(tx):
    player=GamePlayer.objects.select_for_update().filter(
        pk=tx.reference_id,tenant=tx.tenant
    ).first()
    if not player:
        return

    if tx.status==TenantPaymentTransaction.Status.PAID:
        player.payment_status=GamePlayer.PaymentStatus.PAID
        player.amount_paid=max(player.amount_paid,tx.gross_amount)
        player.paid_at=player.paid_at or timezone.now()
        player.save(update_fields=["payment_status","amount_paid","paid_at","updated_at"])
        _finance_income(
            tenant=tx.tenant,
            source_type="arena_game_player",
            source_id=player.pk,
            description=f"Participação em racha #{player.game_id}",
            amount=tx.gross_amount,
            method=tx.method,
        )
    elif tx.status in {
        TenantPaymentTransaction.Status.CANCELLED,
        TenantPaymentTransaction.Status.EXPIRED,
        TenantPaymentTransaction.Status.FAILED,
    } and player.payment_status==GamePlayer.PaymentStatus.PENDING:
        player.payment_status=GamePlayer.PaymentStatus.CANCELLED
        player.save(update_fields=["payment_status","updated_at"])
