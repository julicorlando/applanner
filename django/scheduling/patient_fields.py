"""Encrypted administrative identity fields; no plaintext CPF index."""
import re
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.crypto import salted_hmac
from core.crypto import encrypt_text, decrypt_text


class EncryptedPatientField(models.TextField):
    sensitive=True
    def from_db_value(self, value, expression, connection):
        return decrypt_text(value) if value else ''

    def get_prep_value(self, value):
        return encrypt_text(str(value)) if value else ''


def normalize_cpf(value):
    value = re.sub(r'\D', '', value or '')
    if not value:
        return ''
    if len(value) != 11 or len(set(value)) == 1:
        raise ValidationError({'cpf': 'Informe um CPF válido.'})
    for length in (9, 10):
        digit = (sum(int(value[i]) * (length+1-i) for i in range(length)) * 10) % 11
        if int(value[length]) != (0 if digit == 10 else digit):
            raise ValidationError({'cpf': 'Informe um CPF válido.'})
    return value


def cpf_fingerprint(value):
    return salted_hmac('patient-cpf-v1', value, secret=settings.FIELD_ENCRYPTION_KEY, algorithm='sha256').hexdigest() if value else ''
