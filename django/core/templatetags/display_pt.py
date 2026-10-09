"""Apresentação de códigos legados sem alterar o valor salvo no banco."""

from django import template


register = template.Library()


@register.filter
def single_checkbox(field):
    from django.forms import CheckboxInput
    return isinstance(field.field.widget,CheckboxInput)


@register.filter
def checkbox_group(field):
    from django.forms import CheckboxSelectMultiple
    return isinstance(field.field.widget,CheckboxSelectMultiple)


@register.filter
def homologation_record(obj):
    """Visual hint for explicitly named fixtures; does not change business rules."""
    import re
    values=[getattr(obj,name,"") for name in ("name","customer_name_snapshot","customer_name")]
    if getattr(getattr(obj,"_meta",None),"label_lower","") in {"scheduling.appointment","arena.reservation"}:
        values.extend(getattr(getattr(obj,name,None),"name","") for name in ("customer","service","professional"))
    return any(re.match(r"^(?:Homologa[çc][ãa]o\b|(?:Cliente|Servi[çc]o|Profissional|Corte)\s+QA\b|QA\b)",str(value or ""),re.I) for value in values)


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
