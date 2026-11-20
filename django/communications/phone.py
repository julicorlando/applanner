"""Normalize WhatsApp destinations without changing stored customer records."""
import re


def whatsapp_number(value):
    number=re.sub(r"\D", "", str(value or ""))
    if number.startswith("55") and len(number) in (12, 13):
        return number
    if len(number) in (10, 11) and 11 <= int(number[:2]) <= 99:
        return "55" + number
    return number
