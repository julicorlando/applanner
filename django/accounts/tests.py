import unittest.mock

import bcrypt
from django.test import RequestFactory,SimpleTestCase,TestCase
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.auth import get_user_model

from .middleware import SessionVersionMiddleware
from .models import Capability,PlatformRole,RoleCapability,UserRole
from .permissions import has_capability


User=get_user_model()


class CapabilityTests(TestCase):
    def test_role_grants_capability(self):
        user=User.objects.create_user(email="rbac@example.com",password="StrongPassword!123")
        role=PlatformRole.objects.create(slug="manager-test",name="Manager Test")
        capability=Capability.objects.create(slug="auto.jobs.manage",name="Manage Auto")
        RoleCapability.objects.create(role=role,capability=capability)
        UserRole.objects.create(user=user,role=role)
        self.assertTrue(has_capability(user,"auto.jobs.manage"))
        self.assertFalse(has_capability(user,"master.tenants.manage"))


class SessionVersionTests(TestCase):
    def test_mismatched_session_version_logs_user_out(self):
        user=User.objects.create_user(email="session@example.com",password="StrongPassword!123")
        request=RequestFactory().get("/")
        SessionMiddleware(lambda req: None).process_request(request)
        request.session["session_version"]=user.session_version
        request.session.save()
        request.user=user
        user.session_version+=1
        user.save(update_fields=["session_version"])

        response=SessionVersionMiddleware(lambda req: None)(request)
        self.assertFalse(request.user.is_authenticated)


from .hashers import PHPBcryptPasswordHasher
from .security import totp_for_step,verify_totp


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
