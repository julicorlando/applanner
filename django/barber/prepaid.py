from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from billing.models import TenantPaymentTransaction
from .models import BarberCommand, BarberCommandPayment


def pending_card(appointment):
    return (
        appointment
        and TenantPaymentTransaction.objects.filter(
            tenant=appointment.tenant,
            reference_type="appointment",
            reference_id=appointment.pk,
            method="card",
            status__in=["created", "pending"],
        ).exists()
    )


@transaction.atomic
def sync_card_credit(command):
    command = BarberCommand.objects.select_for_update().get(pk=command.pk)
    if command.status != "open" or not command.appointment_id:
        return
    appointment = command.appointment
    for tx in TenantPaymentTransaction.objects.filter(
        tenant=command.tenant,
        reference_type="appointment",
        reference_id=appointment.pk,
        method="card",
        status="paid",
    ):
        BarberCommandPayment.objects.get_or_create(
            external_payment=tx,
            defaults={
                "tenant": command.tenant,
                "command": command,
                "method": "prepaid_card",
                "amount": tx.gross_amount,
                "user": command.opened_by,
                "received_at": tx.paid_at or timezone.now(),
            },
        )


def require_resolved(command):
    if command.appointment_id and pending_card(command.appointment):
        raise ValidationError(
            "Existe cartão antecipado em processamento. Aguarde a conciliação antes de receber outro pagamento ou fechar a comanda."
        )
    if command.payments.filter(
        external_payment__status__in=["refunded", "partially_refunded"]
    ).exists():
        raise ValidationError(
            "O cartão antecipado recebeu estorno. Confira o provedor e os lançamentos antes de concluir esta comanda."
        )
