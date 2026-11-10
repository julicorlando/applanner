from decimal import Decimal, InvalidOperation


def validate_card_event(tx, remote, resource_id):
    try:
        amount = Decimal(str(remote.get("transaction_amount")))
        valid = (
            amount.is_finite()
            and amount == tx.gross_amount
            and remote.get("currency_id") == "BRL"
            and bool(str(resource_id))
            and str(remote.get("id")) == str(resource_id)
            and tx.provider_transaction_id in ("", str(resource_id))
            and remote.get("external_reference") == tx.external_reference
            and remote.get("live_mode") is (tx.connection.environment == "production")
        )
    except (ValueError, TypeError, InvalidOperation):
        valid = False
    collector = tx.connection.metadata.get("user_id")
    if collector and str(remote.get("collector_id")) != str(collector):
        valid = False
    if tx.status in {"refunded", "cancelled"} and remote.get("status") in {
        "approved",
        "authorized",
    }:
        valid = False
    if (
        tx.status == "partially_refunded"
        and remote.get("status") == "approved"
        and Decimal(str(remote.get("transaction_amount_refunded", 0) or 0)) <= 0
    ):
        valid = False
    if not valid:
        raise ValueError("Evento de cartão não corresponde à cobrança autorizada.")


def card_status(remote):
    status = str(remote.get("status", ""))
    if status == "approved":
        refunded = Decimal(str(remote.get("transaction_amount_refunded", 0) or 0))
        if (
            refunded >= Decimal(str(remote.get("transaction_amount", 0)))
            and refunded > 0
        ):
            return "refunded"
        return "partially_refunded" if refunded > 0 else "paid"
    return {
        "refunded": "refunded",
        "charged_back": "refunded",
        "cancelled": "cancelled",
        "rejected": "failed",
    }.get(status, "pending")
