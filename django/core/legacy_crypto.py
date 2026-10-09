import base64
import json

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def decrypt_php_aes_gcm(value: str, app_key_b64: str) -> dict:
    """
    Compatível com app/Core/Encryption.php do legado:
    base64(iv[12] + tag[16] + ciphertext), AES-256-GCM.
    """
    raw=base64.b64decode(value,validate=True)
    key=base64.b64decode(app_key_b64,validate=True)
    if len(key)!=32:
        raise ValueError("LEGACY_APP_KEY deve decodificar para exatamente 32 bytes.")
    if len(raw)<29:
        raise ValueError("Payload legado inválido.")
    iv=raw[:12]
    tag=raw[12:28]
    ciphertext=raw[28:]
    plain=AESGCM(key).decrypt(iv,ciphertext+tag,None)
    data=json.loads(plain.decode("utf-8"))
    if not isinstance(data,dict):
        raise ValueError("Payload legado não contém objeto JSON.")
    return data
