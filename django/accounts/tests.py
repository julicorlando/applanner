import unittest.mock

import bcrypt
from django.test import SimpleTestCase

from .hashers import PHPBcryptPasswordHasher
from .security import totp_for_step, verify_totp


class LegacyPasswordHasherTests(SimpleTestCase):
    def test_php_bcrypt_hash_is_verified(self):
        raw=bcrypt.hashpw(b"sample-password",bcrypt.gensalt()).decode()
        encoded="php_bcrypt$"+raw
        self.assertTrue(PHPBcryptPasswordHasher().verify("sample-password",encoded))
        self.assertFalse(PHPBcryptPasswordHasher().verify("different",encoded))


class TotpTests(SimpleTestCase):
    def test_totp_accepts_step_and_rejects_replay(self):
        secret="JBSWY3DPEHPK3PXP"
        step=123456
        code=totp_for_step(secret,step)
        with unittest.mock.patch("accounts.security.time.time",return_value=step*30):
            self.assertEqual(verify_totp(secret,code,last_step=0,window=0),step)
            self.assertIsNone(verify_totp(secret,code,last_step=step,window=0))
