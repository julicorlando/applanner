from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory,SimpleTestCase,TestCase,override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.login_limits import attempt_budget
from accounts.models import User


CACHE={"default":{"BACKEND":"django.core.cache.backends.locmem.LocMemCache","LOCATION":"auth-limit-tests"}}
STORAGE={"default":{"BACKEND":"django.core.files.storage.FileSystemStorage"},"staticfiles":{"BACKEND":"django.contrib.staticfiles.storage.StaticFilesStorage"}}


@override_settings(CACHES=CACHE,LOGIN_ATTEMPT_LIMIT=2,AUTH_ATTEMPT_WINDOW_SECONDS=300)
class AttemptBudgetTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.request=RequestFactory().post("/account/login/",REMOTE_ADDR="192.0.2.1")

    def test_limit_isolated_by_ip_and_identity_and_expires(self):
        with patch("accounts.login_limits.time.time",return_value=601):
            key,wait=attempt_budget(self.request,"login","Person@Example.com")
            self.assertEqual(wait,0)
            self.assertNotIn("person",key)
            self.assertEqual(attempt_budget(self.request,"login","person@example.com")[1],0)
            self.assertEqual(attempt_budget(self.request,"login","person@example.com")[1],299)
            self.assertEqual(attempt_budget(self.request,"login","other@example.com")[1],0)
            other=RequestFactory().post("/account/login/",REMOTE_ADDR="192.0.2.2")
            self.assertEqual(attempt_budget(other,"login","person@example.com")[1],0)
        with patch("accounts.login_limits.time.time",return_value=901):
            self.assertEqual(attempt_budget(self.request,"login","person@example.com")[1],0)


@override_settings(CACHES=CACHE,STORAGES=STORAGE,LOGIN_ATTEMPT_LIMIT=2,TWO_FACTOR_ATTEMPT_LIMIT=2)
class AuthenticationAttemptTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user=User.objects.create_user(email="limit@example.com",password="StrongPassword123!")

    def test_password_limit_stops_authentication_and_has_retry_header(self):
        with patch("accounts.views.authenticate",return_value=None) as authenticate:
            for _ in range(2):
                self.assertEqual(self.client.post(reverse("accounts:login"),{"email":self.user.email,"password":"wrong"}).status_code,400)
            response=self.client.post(reverse("accounts:login"),{"email":self.user.email,"password":"wrong"})
            self.assertEqual(response.status_code,429)
            self.assertGreater(int(response["Retry-After"]),0)
            self.assertEqual(authenticate.call_count,2)
            self.assertNotContains(response,self.user.email,status_code=429)

    def test_successful_password_clears_failed_attempt_budget(self):
        self.client.post(reverse("accounts:login"),{"email":self.user.email,"password":"wrong"})
        response=self.client.post(reverse("accounts:login"),{"email":self.user.email,"password":"StrongPassword123!"})
        self.assertEqual(response.status_code,302)
        self.client.logout()
        for _ in range(2):
            self.assertEqual(self.client.post(reverse("accounts:login"),{"email":self.user.email,"password":"wrong"}).status_code,400)

    def test_two_factor_limit_stops_secret_and_recovery_verification(self):
        self.user.two_factor_enabled_at=timezone.now()
        self.user.two_factor_secret_encrypted="encrypted-test-secret"
        self.user.save(update_fields=["two_factor_enabled_at","two_factor_secret_encrypted"])
        session=self.client.session
        session["pre_2fa_user_id"]=self.user.pk
        session.save()
        with patch("accounts.views.decrypt_secret",return_value="secret"),patch("accounts.views.verify_totp",return_value=None) as verify,patch("accounts.views.consume_recovery_code",return_value=False) as recovery:
            for _ in range(2):
                self.assertEqual(self.client.post(reverse("accounts:two-factor-challenge"),{"code":"000000"}).status_code,400)
            response=self.client.post(reverse("accounts:two-factor-challenge"),{"code":"000000"})
            self.assertEqual(response.status_code,429)
            self.assertEqual(verify.call_count,2)
            self.assertEqual(recovery.call_count,2)

    def test_two_factor_cannot_claim_step_already_consumed_by_another_request(self):
        self.user.two_factor_enabled_at=timezone.now()
        self.user.two_factor_secret_encrypted="encrypted-test-secret"
        self.user.save(update_fields=["two_factor_enabled_at","two_factor_secret_encrypted"])
        session=self.client.session
        session["pre_2fa_user_id"]=self.user.pk
        session.save()

        def concurrent_claim(*args,**kwargs):
            User.objects.filter(pk=self.user.pk).update(two_factor_last_step=12345)
            return 12345

        with patch("accounts.views.decrypt_secret",return_value="secret"),patch("accounts.views.verify_totp",side_effect=concurrent_claim):
            response=self.client.post(reverse("accounts:two-factor-challenge"),{"code":"123456"})
        self.assertEqual(response.status_code,400)
        self.assertNotIn("_auth_user_id",self.client.session)

    def test_recovery_code_atomic_claim_accepts_only_once(self):
        from accounts.models import RecoveryCode
        from accounts.security import consume_recovery_code
        import hashlib
        code="ABCD123456"
        RecoveryCode.objects.create(user=self.user,code_hash=hashlib.sha256(code.encode()).hexdigest())
        # A stale caller still performs the conditional write rather than saving a fetched row.
        stale_user=User.objects.get(pk=self.user.pk)
        self.assertTrue(consume_recovery_code(self.user,code))
        self.assertFalse(consume_recovery_code(stale_user,code))
