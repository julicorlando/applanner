from django.test import RequestFactory,TestCase
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
