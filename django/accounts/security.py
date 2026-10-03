import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from datetime import timedelta

from cryptography.fernet import Fernet
from django.conf import settings
from django.utils import timezone

from .models import RecoveryCode, TrustedDevice


def _fernet():
    return Fernet(settings.FIELD_ENCRYPTION_KEY.encode("utf-8"))


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")


def generate_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")


def _decode_base32(secret: str) -> bytes:
    padded=secret + ("=" * ((8 - len(secret) % 8) % 8))
    return base64.b32decode(padded,casefold=True)


def totp_for_step(secret: str, step: int, digits: int = 6) -> str:
    key=_decode_base32(secret)
    msg=struct.pack(">Q",step)
    digest=hmac.new(key,msg,hashlib.sha1).digest()
    offset=digest[-1] & 0x0F
    code=(struct.unpack(">I",digest[offset:offset+4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def verify_totp(secret: str, code: str, *, last_step: int = 0, window: int = 1):
    if not code or not code.isdigit():
        return None
    current=int(time.time() // 30)
    for offset in range(-window,window+1):
        step=current+offset
        if step <= last_step:
            continue
        expected=totp_for_step(secret,step)
        if hmac.compare_digest(expected,code):
            return step
    return None


def generate_recovery_codes(user, count: int = 8):
    RecoveryCode.objects.filter(user=user).delete()
    raw=[]
    objects=[]
    for _ in range(count):
        code=secrets.token_hex(5).upper()
        raw.append(code)
        objects.append(RecoveryCode(user=user,code_hash=hashlib.sha256(code.encode()).hexdigest()))
    RecoveryCode.objects.bulk_create(objects)
    return raw


def consume_recovery_code(user, code: str) -> bool:
    digest=hashlib.sha256(code.strip().upper().encode()).hexdigest()
    row=RecoveryCode.objects.filter(user=user,code_hash=digest,used_at__isnull=True).first()
    if not row:
        return False
    row.used_at=timezone.now()
    row.save(update_fields=["used_at"])
    return True


def issue_trusted_device(user, *, label="", user_agent="", ip_address=None):
    selector=secrets.token_hex(16)
    verifier=secrets.token_urlsafe(32)
    TrustedDevice.objects.create(
        user=user,
        selector=selector,
        verifier_hash=hashlib.sha256(verifier.encode()).hexdigest(),
        label=label[:180],
        user_agent=user_agent[:500],
        ip_address=ip_address,
        session_version=user.session_version,
        expires_at=timezone.now()+timedelta(days=settings.TRUSTED_DEVICE_DAYS),
    )
    return f"{selector}.{verifier}"


def validate_trusted_device(user, token: str) -> bool:
    try:
        selector,verifier=token.split(".",1)
    except ValueError:
        return False
    device=TrustedDevice.objects.filter(
        user=user,
        selector=selector,
        expires_at__gt=timezone.now(),
        session_version=user.session_version,
        revoked_at__isnull=True,
    ).first()
    if not device:
        return False
    expected=device.verifier_hash
    actual=hashlib.sha256(verifier.encode()).hexdigest()
    if not hmac.compare_digest(expected,actual):
        return False
    device.last_used_at=timezone.now()
    device.save(update_fields=["last_used_at"])
    return True
