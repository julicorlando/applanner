import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.test import SimpleTestCase

from .legacy_crypto import decrypt_php_aes_gcm


class LegacyCryptoTests(SimpleTestCase):
    def test_php_aes_gcm_payload_can_be_decrypted(self):
        key=os.urandom(32)
        iv=os.urandom(12)
        payload={"secret":"ABC123","template":"test"}
        encrypted=AESGCM(key).encrypt(iv,json.dumps(payload).encode(),None)
        ciphertext,tag=encrypted[:-16],encrypted[-16:]
        legacy=base64.b64encode(iv+tag+ciphertext).decode()
        decoded=decrypt_php_aes_gcm(legacy,base64.b64encode(key).decode())
        self.assertEqual(decoded,payload)
