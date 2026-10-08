from django.test import TestCase
from django.urls import reverse

from accounts.models import Capability,PlatformRole,RoleCapability,User,UserRole
from tenants.models import Tenant


class CapabilityRouteTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="RBAC",slug="rbac-tenant")
        self.user=User.objects.create_user(email="rbac-route@example.com",password="StrongPassword123!",tenant=self.tenant)
        role=PlatformRole.objects.create(slug="finance-only-test",name="Finance only")
        cap=Capability.objects.create(slug="finance.manage",name="Finance")
        RoleCapability.objects.create(role=role,capability=cap)
        UserRole.objects.create(user=self.user,role=role)
        self.client.force_login(self.user)

    def test_allowed_module(self):
        self.assertEqual(self.client.get(reverse("portal-resource-list",args=["financeiro","produtos"])).status_code,200)

    def test_denied_module(self):
        self.assertEqual(self.client.get(reverse("portal-resource-list",args=["arena","quadras"])).status_code,403)


class MasterAdminGateTests(TestCase):
    def test_anonymous_cannot_see_any_admin_endpoint_or_login(self):
        for path in ['/admin','/admin/','/admin/login/','/admin/accounts/user/']:
            with self.subTest(path=path):
                response=self.client.get(path)
                self.assertEqual(response.status_code,404)
                self.assertNotIn('Location',response)
        self.assertEqual(self.client.post('/admin/login/',{}).status_code,404)

    def test_staff_without_master_privileges_cannot_access_admin(self):
        user=User.objects.create_user(email='staff-admin-test@example.test',password='test-only',is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get('/admin/').status_code,404)
        self.assertEqual(self.client.get('/admin/login/').status_code,404)

    def test_logged_in_master_can_access_admin(self):
        master=User.objects.create_superuser(email='master-admin-test@example.test',password='test-only')
        self.client.force_login(master)
        self.assertEqual(self.client.get('/admin/').status_code,200)

    def test_revoked_master_session_cannot_access_admin(self):
        master=User.objects.create_superuser(email='revoked-admin-test@example.test',password='test-only')
        self.client.force_login(master)
        session=self.client.session
        session['session_version']=master.session_version+1
        session.save()
        self.assertEqual(self.client.get('/admin/').status_code,404)
