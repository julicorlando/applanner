"""Apresentação de códigos legados sem alterar o valor salvo no banco."""

from django import template


register = template.Library()


PAYMENT_METHODS = {
    "cash": "Dinheiro", "dinheiro": "Dinheiro", "pix": "Pix",
    "card": "Cartão", "credit_card": "Cartão de crédito", "debit_card": "Cartão de débito",
    "credit": "Cartão de crédito", "debit": "Cartão de débito",
    "mixed": "Pagamento misto", "transfer": "Transferência", "bank_transfer": "Transferência",
    "onsite": "Pagamento na unidade", "on_site": "Pagamento na unidade",
    "other": "Outro", "outro": "Outro",
}

NOTIFICATION_TYPES = {
    "appointment": "Agendamento", "appointment_confirmation": "Confirmação de agendamento",
    "appointment_reminder": "Lembrete de agendamento", "appointment_cancelled": "Agendamento cancelado",
    "payment": "Pagamento", "payment_received": "Pagamento recebido",
    "support": "Suporte", "security": "Segurança", "system": "Sistema",
    "marketing": "Campanha", "subscription": "Assinatura",
}


@register.filter
def payment_method_pt(value):
    return PAYMENT_METHODS.get(str(value or "").lower(), value or "—")


@register.filter
def notification_type_pt(value):
    return NOTIFICATION_TYPES.get(str(value or "").lower(), value or "—")


@register.filter
def money_pt(value):
    """Format numeric values and serialized billing amounts consistently."""
    from decimal import Decimal, InvalidOperation
    from django.utils.formats import number_format
    try:
        return number_format(Decimal(str(value)), decimal_pos=2, use_l10n=True, force_grouping=True)
    except (InvalidOperation, TypeError, ValueError):
        return "—"
