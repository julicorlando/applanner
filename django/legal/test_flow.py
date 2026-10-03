from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from legal.models import LegalAcceptance,LegalDocument


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
