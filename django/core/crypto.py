import json

from cryptography.fernet import Fernet
from django.conf import settings


def _fernet():
    return Fernet(settings.FIELD_ENCRYPTION_KEY.encode("utf-8"))


def encrypt_text(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_text(value: str) -> str:
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")


def encrypt_json(value: dict) -> str:
    return encrypt_text(json.dumps(value,separators=(",",":"),ensure_ascii=False))


def decrypt_json(value: str) -> dict:
    data=json.loads(decrypt_text(value))
    if not isinstance(data,dict):
        raise ValueError("Payload criptografado inválido.")
    return data
