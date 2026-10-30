from django.core.exceptions import PermissionDenied
from django.test import RequestFactory,TestCase,override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from legal.models import LegalAcceptance,LegalDocument
from legal.views import privacy_center,privacy_export


class LegalAcceptanceFlowTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user(email="legal@example.com",password="StrongPassword123!")
        self.doc=LegalDocument.objects.create(
            type=LegalDocument.Type.TERMS,version="1",title="Termos",
            content="Conteúdo",status=LegalDocument.Status.PUBLISHED,published_at=timezone.now(),
        )
        self.client.force_login(self.user)

    def test_user_is_redirected_until_acceptance(self):
        response=self.client.get("/")
        self.assertRedirects(response,reverse("legal-accept"),fetch_redirect_response=False)
        response=self.client.post(reverse("legal-accept"),{"accept":"yes"})
        self.assertEqual(response.status_code,302)
        self.assertTrue(LegalAcceptance.objects.filter(user=self.user,document=self.doc).exists())

    def test_acceptance_rejects_external_redirect_destinations(self):
        for destination in ("https://external.example/", "//external.example/", "///external.example/"):
            with self.subTest(destination=destination):
                LegalAcceptance.objects.filter(user=self.user).delete()
                response=self.client.post(
                    reverse("legal-accept"),{"accept":"yes"},QUERY_STRING="next="+destination,
                )
                self.assertRedirects(response,"/",fetch_redirect_response=False)
                self.assertTrue(LegalAcceptance.objects.filter(user=self.user,document=self.doc).exists())

    def test_acceptance_preserves_internal_redirect_destination(self):
        response=self.client.post(
            reverse("legal-accept")+"?next=/app/agenda/",{"accept":"yes"},
        )
        self.assertRedirects(response,"/app/agenda/",fetch_redirect_response=False)


@override_settings(CACHES={"default":{"BACKEND":"django.core.cache.backends.locmem.LocMemCache"}})
class PrivacyAccountSecurityTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user(email="private-account@example.com",password="StrongPassword123!")

    def test_assisted_actor_cannot_change_consent_or_export_account(self):
        request=RequestFactory().post(reverse("legal-privacy-center"),{"action":"grant_marketing"})
        request.user=self.user
        request.support_actor=object()
        with self.assertRaises(PermissionDenied):
            privacy_center(request)
        self.user.refresh_from_db()
        self.assertFalse(self.user.marketing_consent)
        request=RequestFactory().get(reverse("legal-privacy-export"))
        request.user=self.user
        request.support_actor=object()
        with self.assertRaises(PermissionDenied):
            privacy_export(request)

    def test_owner_can_export_only_own_account_and_response_is_not_cacheable(self):
        other=User.objects.create_user(email="another-private@example.com",password="StrongPassword123!")
        self.client.force_login(self.user)
        response=self.client.get(reverse("legal-privacy-export"))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,self.user.email)
        self.assertNotContains(response,other.email)
        self.assertIn("no-store",response["Cache-Control"])
        self.assertIn("private",response["Cache-Control"])
